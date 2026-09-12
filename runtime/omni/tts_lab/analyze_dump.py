#!/usr/bin/env python3
"""分析 QIYU_T2W_DUMP 落盘证据：mel 逐帧能量 vs 波形逐 10ms 包络、
跨窗重叠一致性、削顶统计。

用法:
  python analyze_dump.py <dump_dir> [--calls 0 1 2] [--ascii]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

MEL_C = 80
SR = 24000
SAMPLES_PER_MEL = 480


def load_f32(path: Path) -> np.ndarray:
    return np.fromfile(path, dtype="<f4")


def mel_frames(x: np.ndarray) -> np.ndarray:
    return x.reshape(-1, MEL_C).T  # [C, T]


def wave_env(x: np.ndarray, ms: int = 10) -> np.ndarray:
    hop = int(SR * ms / 1000)
    n = len(x) // hop
    return np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)


def ascii_env(env: np.ndarray, floor_db: float = -60.0, per_line: int = 100) -> list[str]:
    db = 20 * np.log10(env + 1e-12)
    chars = " .:-=+*#%@"
    out = []
    for i in range(0, len(db), per_line):
        part = db[i : i + per_line]
        line = "".join(chars[int(np.clip((v - floor_db) / (-floor_db) * (len(chars) - 1), 0, len(chars) - 1))] for v in part)
        out.append(f"{i * 0.01:7.2f}s |{line}|")
    return out


def mel_patch_corr(a: np.ndarray, b: np.ndarray) -> float:
    n = min(a.shape[1], b.shape[1])
    if n < 4:
        return float("nan")
    x, y = a[:, :n].ravel(), b[:, :n].ravel()
    if x.std() < 1e-9 or y.std() < 1e-9:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--calls", type=int, nargs="*")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()
    d = Path(args.dump)

    calls = sorted({int(re.match(r"call(\d+)_", p.name).group(1)) for p in d.glob("call*_meta.txt")})
    if args.calls:
        calls = [c for c in calls if c in args.calls]

    report = {}
    for c in calls:
        mel_new = mel_frames(load_f32(d / f"call{c:04d}_mel_new.bin"))
        mel_in = mel_frames(load_f32(d / f"call{c:04d}_mel_in.bin"))
        w_raw = load_f32(d / f"call{c:04d}_wave_raw.bin")
        w_emit = load_f32(d / f"call{c:04d}_wave_emit.bin")
        env_emit = wave_env(w_emit)
        # mel 逐帧能量（dB）
        mel_e = 10 * np.log10((mel_new ** 2).sum(axis=0) + 1e-12)
        r = {
            "call": c,
            "mel_new_T": int(mel_new.shape[1]),
            "mel_energy_db_min": round(float(mel_e.min()), 2),
            "mel_energy_db_p10": round(float(np.percentile(mel_e, 10)), 2),
            "mel_energy_db_p50": round(float(np.percentile(mel_e, 50)), 2),
            "mel_energy_db_p90": round(float(np.percentile(mel_e, 90)), 2),
            "mel_energy_db_max": round(float(mel_e.max()), 2),
            "mel_energy_dynamic_db": round(float(np.percentile(mel_e, 95) - np.percentile(mel_e, 5)), 2),
            "mel_energy_flat_frac": round(float(np.mean(np.abs(mel_e - np.median(mel_e)) < 3.0)), 3),
            "wav_samples_raw": int(len(w_raw)),
            "wav_samples_emit": int(len(w_emit)),
            "wav_peak_raw": round(float(np.max(np.abs(w_raw))), 5),
            "wav_peak_emit": round(float(np.max(np.abs(w_emit))), 5),
            "wav_clip99_frac_raw": round(float(np.mean(np.abs(w_raw) >= 0.9899)), 5),
            "wav_clip99_frac_emit": round(float(np.mean(np.abs(w_emit) >= 0.9899)), 5),
            "wav_rms_emit": round(float(np.sqrt(np.mean(w_emit ** 2))), 5),
            "env_median": round(float(np.median(env_emit)), 5),
            "env_silent_frac(-45dB)": round(float(np.mean(env_emit < 10 ** (-45 / 20))), 4),
            "env_dynamic_db": round(float(20 * np.log10((np.percentile(env_emit, 95) + 1e-9) / (np.percentile(env_emit, 5) + 1e-9))), 2),
            "mel_frames": int(mel_new.shape[1]),
        }
        report[f"call{c:04d}"] = r
        print(f"--- call{c:04d}  melT={r['mel_new_T']} melE@{r['mel_energy_db_p50']:.1f}dB dyn={r['mel_energy_dynamic_db']}dB flat={r['mel_energy_flat_frac']}"
              f" | wav peak {r['wav_peak_raw']:.4f}->{r['wav_peak_emit']:.4f} clip {r['wav_clip99_frac_raw']*100:.2f}%->{r['wav_clip99_frac_emit']*100:.2f}%"
              f" envmed={r['env_median']:.4f} silent={r['env_silent_frac(-45dB)']*100:.1f}% dyn={r['env_dynamic_db']}dB")
        if args.ascii and c in (calls[0], calls[min(1, len(calls) - 1)]):
            print(f"[mel 逐帧能量 ASCII] call{c:04d} (floor -20/-60 dB rel max)")
            e_db = mel_e - mel_e.max()
            chars = " .:-=+*#%@"
            s = "".join(chars[int(np.clip((v + 40) / 40 * 9, 0, 9))] for v in e_db)
            print("   mel |" + s + "|")
            print(f"[wave 10ms RMS ASCII] call{c:04d}")
            for ln in ascii_env(env_emit):
                print("   " + ln)

    # 跨窗重叠：call k 的 wave_emit 尾部 3840 采样 vs call k+1 的 wave_raw 头部 3840
    overl = []
    for a, b in zip(calls, calls[1:]):
        wa = load_f32(d / f"call{a:04d}_wave_raw.bin")
        wb = load_f32(d / f"call{b:04d}_wave_raw.bin")
        if len(wa) < 3840 or len(wb) < 3840:
            continue
        ta, hb = wa[-3840:], wb[:3840]
        corr = float(np.corrcoef(ta, hb)[0, 1])
        mels = []
        ma = mel_frames(load_f32(d / f"call{a:04d}_mel_in.bin"))
        mb = mel_frames(load_f32(d / f"call{b:04d}_mel_in.bin"))
        mels = mel_patch_corr(ma[:, -8:], mb[:, :8])
        overl.append({"pair": f"{a}->{b}", "wave_tail_head_corr": round(corr, 4),
                      "mel_tail8_head8_corr": None if np.isnan(mels) else round(mels, 4),
                      "rms_tail": round(float(np.sqrt(np.mean(ta ** 2))), 5),
                      "rms_head": round(float(np.sqrt(np.mean(hb ** 2))), 5)})
    print("\n[跨窗重叠一致性] call k 的 vocoder 原始输出尾部 160ms  vs  call k+1 头部 160ms")
    for o in overl:
        print(f"  {o['pair']:>8}  wave_corr={o['wave_tail_head_corr']:+.3f}  mel_corr={o['mel_tail8_head8_corr']}  "
              f"rms {o['rms_tail']:.4f} / {o['rms_head']:.4f}")
    report["overlap"] = overl

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
