# -*- coding: utf-8 -*-
"""12 人设 × 核心场景 回测运行器
用法：
  python test_harness/run_personas.py --label runA --scenarios core --personas all --iters 3 --workers 2
  python test_harness/run_personas.py --label runB --scenarios all --personas p_m_bro --iters 1 --workers 4

输出：
  test_harness/report/results_personas_<label>.jsonl
  test_harness/report/summary_personas_<label>.txt
  test_harness/report/report_personas_<label>.md   （亮点 + 不足 + 按人设/按场景统计）
"""
import json
import time
import random
import argparse
import threading
import concurrent.futures
from collections import Counter, defaultdict
from pathlib import Path

import sys
import os
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

BASE = os.getenv("QIYU_TEST_BASE", "http://127.0.0.1:8765")
REPORT_DIR = HERE / "report"
REPORT_DIR.mkdir(exist_ok=True)
LOG_LOCK = threading.Lock()

import scenarios as S
from personas12 import PERSONAS
from run import stream_chat, score_reply, fetch_memory, fetch_history, setup_characters, RECALL_PERFORM_WORDS, REPORT_DIR as _RD  # noqa

# 核心场景：每个类别挑 1~2 个代表性场景，覆盖用户点名的十几个场景类型
CORE_PICKS = {
    "smalltalk": 2, "cold_short": 1, "comfort": 2, "tool": 2, "topic_shift": 2,
    "night": 1, "romance": 2, "fight": 2, "happy": 1, "memory": 2, "inject": 1,
    "small_help": 2, "mistake": 1, "recall_recent": 2, "minimal_input": 1,
    "rejection": 2, "longform": 1, "story_listener": 1, "old_recall": 1,
    "multi_turn": 3, "unfinished_topic": 1, "strong_emotion": 1, "abrupt_shift": 1,
    "natural_shift": 1, "proactive_cooldown": 1, "typo": 1,
}

FOCUSED_IDS = ["s001", "s260", "s042", "s081", "s111", "s300", "s330", "s360", "s449",
              "s142", "s161", "s181", "s501", "s509", "s202", "s504", "s522", "s526"]

def build_scenario_pool(mode="core"):
    if mode == "focused":
        by_id = {sc["id"]: sc for sc in S.SCENARIOS}
        pool = [by_id[i] for i in FOCUSED_IDS if i in by_id]
        return pool

    if mode == "all":
        return list(S.SCENARIOS)
    pool = []
    per_cat = dict(CORE_PICKS)
    for sc in S.SCENARIOS:
        need = per_cat.get(sc["cat"], 0)
        if need > 0:
            pool.append(sc)
            per_cat[sc["cat"]] -= 1
    random.seed(20260831)
    random.shuffle(pool)
    return pool


def ensure_characters(client):
    """注册 12 个人设（先删旧再建，避免残留角色参数）"""
    for p in PERSONAS:
        try:
            client.delete(f"{BASE}/v1/characters/{p['id']}")
        except Exception:
            pass
        body = {
            "id": p["id"], "name": p["name"], "tagline": p["tagline"],
            "description": p["description"], "persona": p["persona"],
            "keywords": p["keywords"], "persona_params": p["persona_params"],
            "resume": p.get("resume") or {}, "temperature": p.get("temperature", 0.8),
        }
        r = client.post(f"{BASE}/v1/characters", json=body, timeout=20)
        if r.status_code != 200:
            print("create fail", p["id"], r.status_code, r.text[:200])


def run_one(p, sc, it, workers=None):
    import httpx
    client = httpx.Client(timeout=60)
    uid = f"e2e_p_{p['id']}_{sc['id']}_{it}"
    result = {
        "persona": p["id"], "pname": p["name"], "gender": p["gender"], "role": p["role"],
        "id": sc["id"], "cat": sc["cat"], "iter": it, "turns": [], "ok": False,
    }
    t0 = time.time()
    try:
        client.post(f"{BASE}/v1/characters/select", json={"user_id": uid, "character_id": p["id"]}, timeout=15)
        sc2 = dict(sc)
        sc2["char"] = p["id"]
        want_tool = sc2["cat"] == "tool"
        meta = {"want_tool": want_tool, "tool_done": False, "cat": sc2["cat"]}
        for tag in sc2.get("tags") or []:
            if tag.startswith("seed:"):
                _parts = tag[5:].split("|")
                _seed = (_parts[0] or "").strip()
                meta["seed_key"] = (_parts[1] if len(_parts) > 1 else "") or _seed[:4]
                if _seed:
                    try:
                        client.post(f"{BASE}/v1/memory/{uid}", params={"char_id": p["id"]}, json={"text": _seed}, timeout=15)
                    except Exception:
                        pass
        if sc2["cat"] == "story_listener" and any("长故事" in t for t in sc2.get("tags") or []):
            meta["long_story"] = True
        all_texts = []
        for turn_idx, user_text in enumerate(sc2["turns"]):
            res = stream_chat(client, p["id"], uid, user_text)
            if res.get("error"):
                result["turns"].append({"user": user_text, "error": res["error"]})
                continue
            pieces = res["pieces"]
            texts = [x["text"] for x in pieces if x.get("text")]
            all_texts.extend(texts)
            meta["last_turn"] = user_text
            meta["last_reply_texts"] = texts
            result["turns"].append({
                "user": user_text, "pieces": pieces,
                "conv_state": res.get("conversation_state", ""),
                "reasoning_len": len(res.get("reasoning") or ""),
                "elapsed": round(res.get("elapsed", 0), 1),
            })
            if want_tool and turn_idx == len(sc2["turns"]) - 1:
                meta["tool_done"] = False
                followups = []
                for _ in range(45):
                    time.sleep(5)
                    hist = fetch_history(client, uid, p["id"], limit=12)
                    asst = [m for m in hist if m.get("role") == "assistant"]
                    followups = asst[1:] if asst else []
                    if followups:
                        break
                for m in followups:
                    content = m.get("content") or ""
                    if any(k in content for k in ["http", "结果", "查到了", "查好了", "查完了", "查好", "查完", "搜到", "找到", "没搜到", "没查到",
                                                  "链接", "价格", "元", "度", "视频", "网页", "登录", "网站崩", "网有点抽", "没刷出来",
                                                  "查不到", "显示空白", "搜不到", "你自己", "打不开", "翻车", "没找到", "搜了一圈"]):
                        meta["tool_done"] = True
                        break
                result["tool_followup"] = len(followups)
        if sc2["cat"] == "memory":
            time.sleep(3)
            short, long, _ = fetch_memory(client, uid, p["id"])
            key = sc2["tags"][0].split(":", 1)[1] if sc2["tags"] and ":" in sc2["tags"][0] else ""
            mem_all = short + long
            result["memory"] = {"short": short[:160], "long": long[:160], "key": key, "found": bool(key and key in mem_all)}
        score = score_reply(p["id"], all_texts, meta, sc2["turns"][-1])
        result["score"] = score
        result["tool_done"] = bool(meta.get("tool_done"))
        result["ok"] = not score["issues"] and not any(t.get("error") for t in result["turns"])
        if sc2["cat"] == "memory" and len(sc2["turns"]) >= 2 and result.get("memory", {}).get("key"):
            key = result["memory"]["key"]
            second_reply = "".join("".join(x["text"] for x in t.get("pieces") or []) for t in result["turns"][1:])
            _tease_ok = any(k in second_reply for k in ["才几分钟", "才说过", "才说", "自己说的", "刚说的", "刚自己", "问一遍", "又问", "？？？", "？？", "这记性", "记性", "忘", "复读机"])
            _perf_bad = any(k in second_reply for k in RECALL_PERFORM_WORDS)
            result["recall_hit"] = (key in second_reply) or (len(key) >= 2 and any(ch in second_reply for ch in key) and len(second_reply) <= 12) or (_tease_ok and not _perf_bad)
    except Exception as e:
        result["error"] = repr(e)
    result["elapsed"] = round(time.time() - t0, 1)
    return result


def write_log(result):
    with LOG_LOCK:
        with open(REPORT_DIR / f"results_personas_{LABEL}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")


def texts_of(r):
    return [x["text"] for t in r.get("turns", []) for x in t.get("pieces", []) if x.get("text")]


def dump_chat(r):
    out = []
    for t in r.get("turns", []):
        out.append(f"  用户：{t['user']}")
        for x in t.get("pieces", []):
            if x.get("text"):
                out.append(f"  {r['pname']}：{x['text']}")
    return "\n".join(out)


def make_report(rows, label):
    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok"))
    issues = defaultdict(list)
    for r in rows:
        for it in (r.get("score") or {}).get("issues", []):
            issues[it.split(":")[0]].append((r["persona"], r["pname"], r["id"], r["iter"], it))
    by_persona = Counter(r["persona"] for r in rows)
    ok_by_persona = Counter(r["persona"] for r in rows if r.get("ok"))
    by_cat = Counter(r["cat"] for r in rows)
    ok_by_cat = Counter(r["cat"] for r in rows if r.get("ok"))
    mem_found = sum(1 for r in rows if r["cat"] == "memory" and r.get("memory", {}).get("found"))
    mem_total = sum(1 for r in rows if r["cat"] == "memory")
    recall_hit = sum(1 for r in rows if r["cat"] == "memory" and r.get("recall_hit"))
    tool_done = sum(1 for r in rows if r["cat"] == "tool" and r.get("tool_done"))
    tool_total = sum(1 for r in rows if r["cat"] == "tool")

    # 亮点：真人感好的样例（无问题 & 短 & 多轮自然）
    good = [r for r in rows if r.get("ok") and not (r.get("score") or {}).get("issues")]
    good.sort(key=lambda r: (r.get("score") or {}).get("total_len", 0))
    highlights = good[:12]

    lines = []
    lines.append(f"# 栖语demo 人设回测报告 · {label}")
    lines.append("")
    lines.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 范围：{len(PERSONAS)} 个人设 × {len(set(r['id'] for r in rows))} 个场景 × 迭代次数不定 = {total} 次调用")
    lines.append(f"> 结果：**{ok}/{total} 通过**（{(ok/total*100 if total else 0):.1f}%）")
    lines.append("")
    lines.append("## 一、总览")
    lines.append("")
    lines.append("| 维度 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 总调用 | {total} |")
    lines.append(f"| 通过 | {ok} |")
    lines.append(f"| 失败 | {total - ok} |")
    lines.append(f"| 记忆写入命中 | {mem_found}/{mem_total} |")
    lines.append(f"| 记忆调用命中 | {recall_hit}/{mem_total} |")
    lines.append(f"| 工具真实执行 | {tool_done}/{tool_total} |")
    lines.append("")
    lines.append("## 二、按人设")
    lines.append("")
    lines.append("| 人设 | 类型 | 性别向 | 场景数 | 通过率 |")
    lines.append("|---|---|---|---|---|")
    for p in PERSONAS:
        t = by_persona.get(p["id"], 0)
        o = ok_by_persona.get(p["id"], 0)
        lines.append(f"| {p['name']}（{p['id']}） | {p['role']} | {'男' if p['gender']=='male' else '女'} | {t} | {o}/{t} |")
    lines.append("")
    lines.append("## 三、按场景")
    lines.append("")
    lines.append("| 场景类别 | 次数 | 通过率 |")
    lines.append("|---|---|---|")
    for k in sorted(set(list(by_cat.keys()) + list(ok_by_cat.keys()))):
        lines.append(f"| {k} | {by_cat.get(k,0)} | {ok_by_cat.get(k,0)}/{by_cat.get(k,0)} |")
    lines.append("")
    lines.append("## 四、亮点示例（真人感好的样本）")
    lines.append("")
    for r in highlights[:8]:
        lines.append(f"### {r['pname']} · {r['cat']} · s{r['id']}（iter {r['iter']}）")
        lines.append("```")
        lines.append(dump_chat(r))
        lines.append("```")
        lines.append("")
    lines.append("## 五、不足项（问题分类）")
    lines.append("")
    if issues:
        for k, v in sorted(issues.items(), key=lambda x: -len(x[1])):
            lines.append(f"### {k}（{len(v)} 次）")
            for persona, pname, sid, it, detail in v[:6]:
                lines.append(f"- {pname} · s{sid} iter{it}：{detail}")
            lines.append("")
    else:
        lines.append("无")
    lines.append("")
    lines.append("## 六、失败样例（前 12 条）")
    lines.append("")
    fails = [r for r in rows if not r.get("ok")]
    for r in fails[:12]:
        lines.append(f"### {r['pname']} · {r['cat']} · s{r['id']} iter{r['iter']}（失败：{(r.get('score') or {}).get('issues')}）")
        lines.append("```")
        lines.append(dump_chat(r))
        lines.append("```")
        lines.append("")
    md = "\n".join(lines)
    (REPORT_DIR / f"report_personas_{label}.md").write_text(md, encoding="utf-8")
    (REPORT_DIR / f"summary_personas_{label}.txt").write_text(
        f"===== {label} =====\n总:{total} 通过:{ok} 失败:{total-ok}\n"
        + "分类: " + ", ".join(f"{k}={v}" for k, v in by_cat.items()) + "\n"
        + "人设: " + ", ".join(f"{k}={ok_by_persona.get(k,0)}/{v}" for k, v in by_persona.items()) + "\n"
        + "高频问题: " + ", ".join(f"{k}({len(v)})" for k, v in issues.items()) + "\n",
        encoding="utf-8",
    )
    print(md[:2500])


def main():
    global LABEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="runA")
    ap.add_argument("--scenarios", default="core", choices=["core", "all", "focused"])
    ap.add_argument("--personas", default="all", help="all 或逗号分隔的人设 id")
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--clear", action="store_true", help="清空上次同 label 的结果")
    ap.add_argument("--resume", action="store_true", help="跳过已完成 (人设,场景,iter)，断点续跑")
    ap.add_argument("--ids", default="", help="只跑指定场景 id（逗号分隔），如 s142,s509")
    args = ap.parse_args()
    LABEL = args.label
    if args.clear and (REPORT_DIR / f"results_personas_{LABEL}.jsonl").exists():
        (REPORT_DIR / f"results_personas_{LABEL}.jsonl").unlink()

    import httpx
    client = httpx.Client(timeout=30)
    ensure_characters(client)
    persona_list = [p for p in PERSONAS if args.personas == "all" or p["id"] in [x.strip() for x in args.personas.split(",")]]
    pool = build_scenario_pool(args.scenarios)
    if args.ids.strip():
        by_id = {sc["id"]: sc for sc in S.SCENARIOS}
        pool = [by_id[x.strip()] for x in args.ids.split(",") if x.strip() in by_id]
    print(f"[personas] {len(persona_list)} 个人设 × {len(pool)} 个场景 × {args.iters} 迭代 = {len(persona_list)*len(pool)*args.iters} 次调用")

    done_keys = set()
    if args.resume and (REPORT_DIR / f"results_personas_{LABEL}.jsonl").exists():
        for line in (REPORT_DIR / f"results_personas_{LABEL}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                done_keys.add((row.get("persona"), row.get("id"), row.get("iter")))
            except Exception:
                pass
        print(f"[resume] 已存在 {len(done_keys)} 条，将跳过重复项")
    tasks = []
    for p in persona_list:
        for sc in pool:
            for it in range(args.iters):
                if (p["id"], sc["id"], it) in done_keys:
                    continue
                tasks.append((p, sc, it))
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, p, sc, it): (p, sc, it) for p, sc, it in tasks}
        for fut in concurrent.futures.as_completed(futs):
            try:
                res = fut.result()
                write_log(res)
                done += 1
                if done % 10 == 0:
                    print(f"  done {done}/{len(tasks)}")
            except Exception as e:
                print("task fail", repr(e))
    print("finish, generating report...")
    rows = [json.loads(l) for l in (REPORT_DIR / f"results_personas_{LABEL}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    make_report(rows, LABEL)


if __name__ == "__main__":
    main()


