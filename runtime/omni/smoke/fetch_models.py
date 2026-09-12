# -*- coding: utf-8 -*-
"""栖语 · MiniCPM-o 4.5 GGUF 权重获取（规格 §二）。

**不要只下载一个 5GB 的 Q4_K_M 就以为 Omni 能跑。** 完整的 Omni 需要 6 类文件：

| 模块 | 文件 | 作用 | 加载方式 |
|---|---|---|---|
| LLM | ``MiniCPM-o-4_5-Q4_K_M.gguf`` | Qwen3-8B 底座，出文本 token | 主模型 ``-m`` |
| VPM | ``vision/…-vision-F16.gguf`` | SigLip2 视觉编码器 + Resampler | ``--vision`` |
| APM | ``audio/…-audio-F16.gguf`` | Whisper-medium 音频编码器 | ``--audio`` |
| TTS | ``tts/…-tts-F16.gguf`` | LLaMA 445M，出语音 token | ``--tts`` |
| TTS Projector | ``tts/…-projector-F16.gguf`` | LLM hidden → TTS 输入 | ``--projector`` |
| Token2Wav | ``token2wav-gguf/*.gguf`` | Flow-Matching + HiFiGAN 声码器（5 个文件） | 自动按目录发现 |

```bash
python -m runtime.omni.smoke.fetch_models --plan          # 只打印清单
python -m runtime.omni.smoke.fetch_models --download      # 开始下载（支持断点续传）
python -m runtime.omni.smoke.fetch_models --verify        # 校验完整性
```
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO = "openbmb/MiniCPM-o-4_5-gguf"
DEFAULT_ENDPOINT = os.environ.get("QIYU_HF_ENDPOINT", "https://hf-mirror.com")
# 实测（2026-09-11）：hf-mirror.com 单连接 ~200 KB/s，huggingface.co 被墙，
# ModelScope 同仓库 ~37 MB/s。默认走 ModelScope。
MODELSCOPE_ENDPOINT = "https://www.modelscope.cn/models"
SOURCES = ("modelscope", "hf")

# name, 作用, 是否为运行必需, 备注
MANIFEST = (
    ("MiniCPM-o-4_5-Q4_K_M.gguf", "LLM 主模型（Qwen3-8B，Q4_K_M）", True,
     "主推理权重；-m 传入"),
    ("vision/MiniCPM-o-4_5-vision-F16.gguf", "VPM 视觉编码器（SigLip2+Resampler）", True,
     "图像/视频理解必需"),
    ("audio/MiniCPM-o-4_5-audio-F16.gguf", "APM 音频编码器（Whisper-medium）", True,
     "语音输入必需"),
    ("tts/MiniCPM-o-4_5-tts-F16.gguf", "TTS talker（LLaMA 445M）", True,
     "语音输出必需；--no-tts 可跳过"),
    ("tts/MiniCPM-o-4_5-projector-F16.gguf", "TTS Projector（LLM hidden→TTS）", True,
     "语音输出必需"),
    ("token2wav-gguf/encoder.gguf", "Token2Wav encoder", True, "声码器前端"),
    ("token2wav-gguf/flow_matching.gguf", "Token2Wav flow matching", True, "DiT 主干"),
    ("token2wav-gguf/flow_extra.gguf", "Token2Wav flow extra", True, "辅助"),
    ("token2wav-gguf/hifigan2.gguf", "Token2Wav HiFiGAN 声码器", True, "mel→waveform"),
    ("token2wav-gguf/prompt_cache.gguf", "Token2Wav prompt 缓存", True, "零样本音色"),
)


def dest_dir() -> Path:
    env = os.environ.get("QIYU_OMNI_MODEL_DIR")
    if env:
        return Path(env)
    d = PROJECT_ROOT / "models" / "omni" / "MiniCPM-o-4_5-gguf"
    return d


def url_for(rel: str, endpoint: str = DEFAULT_ENDPOINT, source: str = "hf") -> str:
    if source == "modelscope":
        return f"{MODELSCOPE_ENDPOINT}/{REPO}/resolve/master/{rel}"
    return f"{endpoint}/{REPO}/resolve/main/{rel}"


def head_size(url: str, timeout: int = 30) -> Optional[int]:
    """远端文件大小。

    ModelScope 的 HEAD 不返回 Content-Length，所以要退回「Range: bytes=0-0」，
    从 ``Content-Range: bytes 0-0/4683073056`` 里读总长度。
    """
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "qiyu-fetch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = r.headers.get("Content-Length")
            if n and int(n) > 0:
                return int(n)
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "qiyu-fetch",
                                                   "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr:
                try:
                    return int(cr.rsplit("/", 1)[1])
                except ValueError:
                    pass
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:
        return None


def download_one(rel: str, dest: Path, endpoint: str, retries: int = 6,
                 source: str = "modelscope") -> dict:
    url = url_for(rel, endpoint, source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = head_size(url)
    for attempt in range(1, retries + 1):
        have = dest.stat().st_size if dest.exists() else 0
        if total and have >= total:
            return {"file": rel, "ok": True, "gb": round(total / 1073741824, 2), "skipped": True}
        headers = {"User-Agent": "qiyu-fetch"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "ab") as f:
                chunk = 1024 * 256
                last = time.time()
                while True:
                    buf = r.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    if time.time() - last > 5:
                        last = time.time()
                        cur = dest.stat().st_size
                        pct = f"{cur / total * 100:5.1f}%" if total else "  ?  "
                        print(f"    {rel}  {pct}  {cur / 1073741824:.2f} GB", flush=True)
            got = dest.stat().st_size
            if total is None or got >= total:
                return {"file": rel, "ok": True, "gb": round(got / 1073741824, 2)}
            print(f"    [重试 {attempt}] {rel}: {got}/{total}", flush=True)
        except urllib.error.HTTPError as e:
            if e.code == 416:
                # 416 = 请求的 Range 超出文件末尾 → 本地文件已完整
                got = dest.stat().st_size if dest.exists() else 0
                if got > 0:
                    return {"file": rel, "ok": True, "gb": round(got / 1073741824, 2),
                            "note": "416 → 已完整"}
            print(f"    [重试 {attempt}] {rel}: HTTP {e.code}", flush=True)
            time.sleep(min(30, 3 * attempt))
        except Exception as e:
            print(f"    [重试 {attempt}] {rel}: {e!r}", flush=True)
            time.sleep(min(30, 3 * attempt))
    return {"file": rel, "ok": False, "error": "下载失败（重试用尽）"}


def plan() -> dict:
    d = dest_dir()
    rows = []
    total = 0.0
    for rel, purpose, required, note in MANIFEST:
        p = d / rel.replace("/", os.sep)
        size = p.stat().st_size if p.exists() else 0
        total += size
        rows.append({"file": rel, "purpose": purpose, "required": required, "note": note,
                     "present": p.exists(), "gb": round(size / 1073741824, 2)})
    return {"dest": str(d), "files": rows, "present_gb": round(total / 1073741824, 2),
            "expected_gb_approx": 8.26}


def main() -> int:
    ap = argparse.ArgumentParser(description="MiniCPM-o 4.5 GGUF 获取")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--source", default="modelscope", choices=SOURCES,
                    help="下载源；实测 modelscope 最快（~37MB/s），hf 镜像 ~200KB/s")
    ap.add_argument("--only", default="", help="只下载名字里包含该子串的文件（用于修复单文件）")
    ap.add_argument("--redo", action="store_true", help="配合 --only，先删除再重下")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    d = dest_dir()
    info = plan()

    if args.plan or not (args.download or args.verify):
        print("=" * 78)
        print("  MiniCPM-o 4.5 GGUF 清单（完整 Omni 需要全部 6 类，不是只有主模型）")
        print("=" * 78)
        print(f"  目标目录: {d}")
        print(f"  预期总量: 约 {info['expected_gb_approx']} GB")
        print("-" * 78)
        for r in info["files"]:
            flag = "OK " if r["present"] else "-- "
            print(f"  [{flag}] {r['file']:<44} {r['purpose']}")
        print("-" * 78)
        print(f"  已就绪: {info['present_gb']} GB")
        print("=" * 78)

    if args.download:
        print(f"\n开始下载 → {d}（端点 {args.endpoint}）", flush=True)
        results = []
        t0 = time.time()
        for rel, purpose, required, note in MANIFEST:
            if args.only and args.only not in rel:
                continue
            target = d / rel.replace("/", os.sep)
            if args.redo and target.exists():
                target.unlink()
            print(f"  > {rel}", flush=True)
            results.append(download_one(rel, target, args.endpoint, source=args.source))
        ok = all(r.get("ok") for r in results)
        print(f"\n完成: {sum(1 for r in results if r.get('ok'))}/{len(results)}"
              f"  用时 {(time.time() - t0) / 60:.1f} 分钟")
        if args.json:
            Path(args.json).write_text(json.dumps({"plan": info, "results": results},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if ok else 1

    if args.verify:
        missing = [r["file"] for r in info["files"] if not r["present"]]
        print(f"缺失 {len(missing)} 个文件")
        for m in missing:
            print("   -", m)
        return 0 if not missing else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
