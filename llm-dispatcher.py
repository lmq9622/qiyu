#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 自动切换调度器: 35B <-> Qwen3.8-27B RVN, 双模型均支持视觉 (mmproj), 请求时自动卸载/加载
2026-08-12 fix: SSE 响应加 Connection: close, 修复 Python 3.14 http.server keep-alive 流式响应不结束
2026-08-18: 27B 定版 RVN (MTP+视觉); 35B 增加 mmproj 视觉
2026-08-19: ① Ollama 原生 API 翻译层 (/api/chat, /api/tags) 修复 LobeChat Ollama 提供商 404
           ② RVN 极简模板 -> 覆盖为完整 Qwen3 模板 (--chat-template-file) 恢复工具调用+思考
           ③ --reasoning-format deepseek: <think> 提取到 reasoning_content (LobeChat 思考面板)
2026-08-20: ① 用户要求模型常驻: unload_loop 阈值 300 -> 86400 秒 (不再自动卸载)
           ② --cache-reuse 256 (KV chunk 复用; 注意 mmproj 模型会被 server 强制禁用)
"""
import base64, json, os, subprocess, threading, time, urllib.request, urllib.error, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIN = "/home/lmq/llama.cpp/build/bin/llama-server"
M35 = "/home/lmq/models/Qwen3.6-35B-A3B-uncensored-heretic-Q4_K_M.gguf"
MMPROJ35 = "/home/lmq/models/mmproj-Qwen3.6-35B-A3B-F16.gguf"
MRVN = "/home/lmq/models/RVN-Q4_K_M-mtp.gguf"
MMPROJR = "/home/lmq/models/mmproj-Qwen3.8-27B-Q8_0.gguf"
TPL = "/home/lmq/qwen3.jinja"
A35 = "qwen3.6-35b-a3b-uncensored-heretic"
ARVN = "qwen3.8-27b-rvn-heretic-mtp"

CONFIGS = {
    # 2026-08-20 --cache-reuse 256: 整型=可复用的最小 chunk token 数 (非 0-1 比例; llama.cpp 自家默认 256)。
    # 注意: 带 --mmproj 的模型会被 server 强制禁用 cache_reuse (见 server-context.cpp 日志警告), 此处保留参数待去 mmproj 后生效
    A35: {"port": 18081, "args": [BIN, "-m", M35, "--mmproj", MMPROJ35, "-ngl", "99", "-fa", "on", "-c", "327680", "-np", "4", "--reasoning-format", "deepseek", "--cache-reuse", "256", "--alias", A35, "--host", "127.0.0.1", "--port", "18081"]},
    ARVN: {"port": 18080, "args": [BIN, "-m", MRVN, "--mmproj", MMPROJR, "--spec-type", "draft-mtp", "-ngl", "99", "-fa", "on", "-c", "192000", "-ctk", "q4_0", "-ctv", "q4_0", "--reasoning-format", "deepseek", "--cache-reuse", "256", "--chat-template-file", TPL, "--alias", ARVN, "--host", "127.0.0.1", "--port", "18080"]},
}

state = {"current": None, "proc": None, "lock": threading.Lock()}
last_activity = time.time()  # idle-unload timer
LOG = open("/home/lmq/llm-dispatcher.log", "a", buffering=1)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=LOG, flush=True)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def health(port, timeout=3):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def vram_free(threshold=2048):
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True)
        vals = [int(x) for x in out.strip().splitlines()]
        return min(vals) > threshold
    except Exception:
        return True


def stop_current():
    p = state["proc"]
    if p:
        log("卸载模型:", state["current"], "pid", p.pid)
        p.terminate()
        try:
            p.wait(timeout=20)
        except Exception:
            p.kill()
            try:
                p.wait(timeout=5)
            except Exception:
                pass
        state["proc"] = None
        state["current"] = None
        for i in range(30):
            if vram_free():
                break
            time.sleep(1)
        time.sleep(1)


def start_model(model):
    cfg = CONFIGS[model]
    log("加载模型:", model)
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = "0,1"
    p = subprocess.Popen(cfg["args"], stdout=LOG, stderr=LOG, env=env)
    state["proc"] = p
    state["current"] = model
    for i in range(180):
        if health(cfg["port"]):
            log("就绪:", model)
            return True
        if p.poll() is not None:
            log("模型启动失败:", model, "exit", p.returncode)
            state["proc"] = None
            state["current"] = None
            return False
        time.sleep(1)
    log("加载超时:", model)
    return False


def ensure(model):
    with state["lock"]:
        if state["current"] == model and health(CONFIGS[model]["port"]):
            return True, CONFIGS[model]["port"]
        stop_current()
        return start_model(model), CONFIGS[model]["port"]


def forward_openai(model, port, body_bytes, path="/v1/chat/completions", timeout=300):
    """Forward an OpenAI-format request to llama-server, return (status, ctype, body_bytes)."""
    url = "http://127.0.0.1:%d%s" % (port, path)
    hdrs = {"Content-Type": "application/json"}
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=body_bytes, headers=hdrs, method="POST"), timeout=timeout)
    except urllib.error.HTTPError as e:
        return e.code, "application/json", e.read()
    except Exception as e:
        return 502, "application/json", json.dumps({"error": {"message": str(e)}}).encode()
    ctype = r.headers.get("Content-Type", "application/json")
    if "text/event-stream" in ctype:
        return r.status, ctype, r  # streaming: return raw file object
    return r.status, ctype, r.read()


# ---------------- Ollama native API translation ----------------


def sniff_image_mime(b64):
    """魔数嗅探 MIME: PNG/JPEG/GIF/WebP, 默认 image/png。只用内置 base64, 无第三方依赖。"""
    try:
        raw = base64.b64decode((b64 or "")[:16], validate=False)
    except Exception:
        return "image/png"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"GIF8":
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def convert_ollama_images(messages):
    """Ollama 原生 images:[base64...] -> OpenAI 格式 image_url content parts (llama.cpp 视觉)。

    对每条 message: content(字符串) 变 parts 列表, 首项为原文本, 之后每个 base64 一张图;
    已是 OpenAI 格式(content 为 list)的原样不动; 其他字段不动。
    """
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        imgs = msg.get("images")
        if not isinstance(imgs, list) or not imgs:
            continue
        if isinstance(msg.get("content"), list):
            continue  # 已是 OpenAI 格式, 不重复转换
        text = msg.get("content")
        parts = [{"type": "text", "text": text if isinstance(text, str) else ""}]
        for b in imgs:
            if not isinstance(b, str) or not b:
                continue
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:%s;base64,%s" % (sniff_image_mime(b), b)}})
        msg["content"] = parts
        del msg["images"]
    return messages


def ollama_to_openai(req):
    o = {"model": req.get("model"), "messages": convert_ollama_images(req.get("messages", [])), "stream": bool(req.get("stream", False))}
    if o["stream"]:
        o["stream_options"] = {"include_usage": True}
    opt = req.get("options") or {}
    for ok, ov in [("temperature", "temperature"), ("top_p", "top_p"), ("top_k", "top_k"),
                   ("num_predict", "max_tokens"), ("stop", "stop"), ("frequency_penalty", "frequency_penalty"),
                   ("presence_penalty", "presence_penalty"), ("repeat_penalty", "repeat_penalty"), ("seed", "seed")]:
        if ok in opt:
            o[ov] = opt[ok]
    if req.get("tools"):
        o["tools"] = req["tools"]
    if req.get("format") == "json":
        o["response_format"] = {"type": "json_object"}
    # 思考开关: LobeChat ollama runtime 补丁后发顶层 think(true/false), 兼容 enable_thinking
    think = req.get("think", req.get("enable_thinking"))
    if think is not None:
        o["chat_template_kwargs"] = {"enable_thinking": bool(think)}
    return o


def map_tool_calls(tcs):
    out = []
    for tc in tcs or []:
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        # LobeChat/ollama 期望 arguments 为对象(不是字符串)
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                pass
        out.append({"type": "function", "function": {"name": fn.get("name", ""), "arguments": args}})
    return out


def ollama_ndjson_line(model, **msg_fields):
    m = {"role": "assistant", "content": ""}  # content 必须恒为字符串(LobeChat 直接 .includes/.replaceAll)
    m.update(msg_fields)
    return json.dumps({"model": model, "created_at": now_iso(), "message": m, "done": False}) + "\n"


def handle_ollama_chat(h, body):
    global last_activity
    last_activity = time.time()
    try:
        req = json.loads(body)
    except Exception:
        req = {}
    model = req.get("model") or state["current"]
    if model not in CONFIGS:
        h._send(400, "application/json", json.dumps({"error": "unknown model: %s" % model}).encode())
        return
    log("Ollama请求:", model, "路径:", h.path, "流式:", req.get("stream"), "think:", req.get("think", req.get("enable_thinking")), "from:", h.client_address[0])
    ok, port = ensure(model)
    if not ok:
        h._send(503, "application/json", json.dumps({"error": "model failed to load"}).encode())
        return
    oai = ollama_to_openai(req)
    t0 = time.time()
    try:
        status, ctype, resp = forward_openai(model, port, json.dumps(oai).encode())
    except Exception as e:
        h._send(502, "application/json", json.dumps({"error": str(e)}).encode())
        return

    # 非流式: 直接转换 JSON
    if not hasattr(resp, "read"):
        # bytes body
        if status != 200:
            h._send(status, "application/json", resp)
            return
        try:
            od = json.loads(resp)
        except Exception:
            h._send(status, "application/json", resp)
            return
        ch = od.get("choices", [{}])[0]
        msg = ch.get("message", {})
        om = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("reasoning_content"):
            om["thinking"] = msg["reasoning_content"]
        if msg.get("tool_calls"):
            om["tool_calls"] = map_tool_calls(msg["tool_calls"])
        u = od.get("usage") or {}
        tmg = od.get("timings") or {}
        out = {"model": model, "created_at": now_iso(), "message": om, "done": True,
               "total_duration": int((time.time() - t0) * 1e9), "load_duration": 0,
               "prompt_eval_count": u.get("prompt_tokens") or tmg.get("prompt_n") or 0,
               "prompt_eval_duration": int((tmg.get("prompt_ms") or 0) * 1e6),
               "eval_count": u.get("completion_tokens") or tmg.get("predicted_n") or 0,
               "eval_duration": int((tmg.get("predicted_ms") or 0) * 1e6)}
        h._send(status, "application/json", json.dumps(out).encode())
        return

    # 流式: SSE -> NDJSON
    h.send_response(status)
    h.send_header("Content-Type", "application/x-ndjson")
    h.send_header("Connection", "close")
    h.end_headers()
    tool_acc = {}
    u_usage = {}
    u_timings = {}
    try:
        buf = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload in (b"[DONE]", b""):
                    continue
                try:
                    dj = json.loads(payload)
                except Exception:
                    continue
                ch0 = (dj.get("choices") or [{}])[0]
                delta = ch0.get("delta", {})
                if delta.get("content") is not None:
                    h.wfile.write(ollama_ndjson_line(model, content=delta["content"]).encode())
                    h.wfile.flush()
                elif delta.get("reasoning_content"):
                    h.wfile.write(ollama_ndjson_line(model, thinking=delta["reasoning_content"]).encode())
                    h.wfile.flush()
                elif delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        acc = tool_acc.setdefault(idx, {"name": "", "arguments": ""})
                        fn = tc.get("function", {})
                        acc["name"] += fn.get("name") or ""
                        acc["arguments"] += fn.get("arguments") or ""
                if dj.get("usage"):
                    u_usage = dj["usage"]
                if dj.get("timings"):
                    u_timings = dj["timings"]
        # 收尾: 先发 tool_calls 行(done:false, LobeChat 先查 done 再查 tool_calls), 再发 done 行
        if tool_acc:
            tc_line = {"model": model, "created_at": now_iso(), "done": False,
                       "message": {"role": "assistant", "content": "", "tool_calls": [
                           {"type": "function", "function": {"name": a["name"], "arguments": (json.loads(a["arguments"]) if a["arguments"].strip() else {})}}
                           for a in tool_acc.values()]}}
            h.wfile.write(json.dumps(tc_line).encode() + b"\n")
            h.wfile.flush()
        tmg = u_timings or {}
        fin = {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": ""}, "done": True,
               "total_duration": int((time.time() - t0) * 1e9), "load_duration": 0,
               "prompt_eval_count": u_usage.get("prompt_tokens") or tmg.get("prompt_n") or 0,
               "prompt_eval_duration": int((tmg.get("prompt_ms") or 0) * 1e6),
               "eval_count": u_usage.get("completion_tokens") or tmg.get("predicted_n") or 0,
               "eval_duration": int((tmg.get("predicted_ms") or 0) * 1e6)}
        h.wfile.write(json.dumps(fin).encode() + b"\n")
        h.wfile.flush()
    except Exception as e:
        log("Ollama 流式转发异常:", e)
    finally:
        h.close_connection = True
        try:
            resp.close()
        except Exception:
            pass


def unload_loop():
    while True:
        time.sleep(30)
        try:
            with state["lock"]:
                # 2026-08-20 用户要求模型常驻: 阈值 300 -> 86400 秒 (不再自动卸载, 省去每次加载)
                if state["current"] and time.time() - last_activity > 86400:
                    log("空闲24小时，自动卸载")
                    stop_current()
        except Exception as e:
            log("unload_loop error:", e)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            ok = bool(state["current"]) and health(CONFIGS[state["current"]]["port"])
            self._send(200 if ok else 503, "application/json",
                       json.dumps({"status": "ok" if ok else "loading"}).encode())
            return
        if self.path in ("/v1/models", "/models"):
            data = {"object": "list", "data": [{"id": k, "object": "model", "created": 0, "owned_by": "local"} for k in CONFIGS]}
            self._send(200, "application/json", json.dumps(data).encode())
            return
        if self.path in ("/api/tags", "/v1/api/tags"):
            now = now_iso()
            models = []
            for k in CONFIGS:
                size = os.path.getsize(MRVN) if k == ARVN else os.path.getsize(M35)
                models.append({"name": k, "model": k, "modified_at": now, "size": size,
                               "digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                               "details": {"parameter_size": "27B" if k == ARVN else "35B", "quantization_level": "Q4_K_M"}})
            self._send(200, "application/json", json.dumps({"models": models}).encode())
            return
        self._send(404, "application/json", b'{"error":"not found"}')

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(ln) if ln else b"{}"
        if self.path in ("/api/chat", "/v1/api/chat"):
            handle_ollama_chat(self, body)
            return
        if self.path in ("/api/generate", "/v1/api/generate"):
            self._send(400, "application/json", json.dumps({"error": "generate endpoint not supported, use /api/chat"}).encode())
            return
        try:
            req = json.loads(body)
        except Exception:
            req = {}
        model = req.get("model") or state["current"]
        global last_activity
        last_activity = time.time()
        if model not in CONFIGS:
            self._send(400, "application/json",
                       json.dumps({"error": {"message": "unknown model: %s" % model}}).encode())
            return
        log("请求模型:", model, "路径:", self.path, "当前:", state["current"])
        ok, port = ensure(model)
        if not ok:
            self._send(503, "application/json", json.dumps({"error": {"message": "model failed to load"}}).encode())
            return
        url = "http://127.0.0.1:%d%s" % (port, self.path)
        hdrs = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdrs, method="POST"), timeout=300)
        except urllib.error.HTTPError as e:
            err = e.read()
            self._send(e.code, "application/json", err)
            return
        except Exception as e:
            self._send(502, "application/json", json.dumps({"error": {"message": str(e)}}).encode())
            return
        ctype = r.headers.get("Content-Type", "application/json")
        if "text/event-stream" in ctype:
            self.send_response(r.status)
            self.send_header("Content-Type", ctype)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = r.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception as e:
                log("SSE 转发异常:", e)
            finally:
                self.close_connection = True
                try:
                    r.close()
                except Exception:
                    pass
            return
        data = r.read()
        self.send_response(r.status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    log("调度器启动(2026-08-19 新版: Ollama API + 完整模板 + reasoning), 预加载:", A35)
    start_model(A35)
    last_activity = time.time()
    threading.Thread(target=unload_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", 8081), H)
    log("监听 0.0.0.0:8081")
    srv.serve_forever()
