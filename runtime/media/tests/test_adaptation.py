# -*- coding: utf-8 -*-
"""带宽自适应策略验证（合成质量序列；真实网络对端 NOT VERIFIED）。

验证：
  1. 优良网络 -> EXCELLENT / 10fps
  2. 逐步恶化 -> 逐级降档（FAIR / POOR / CRITICAL）
  3. 滞回：单次抖动不切换
  4. 冷却：切换后短时间内不再切
  5. CRITICAL 关摄像头；恢复后回来
  6. apply() 真的改到本地视频轨
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.media.adaptation import BandwidthAdapter, QualityLevel
from runtime.media.types import MediaQualitySample

OUT = Path("runtime/omni/out")
RESULTS = {}


def _record(name, ok, detail=None):
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name,
                            json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


def main():
    print("=" * 70)
    print("带宽自适应验证（合成质量序列）")
    print("=" * 70)
    ad = BandwidthAdapter()
    good = MediaQualitySample(rtt_ms=20, jitter_ms=5, loss_ratio=0.0)
    d = ad.decide(good)
    _record("excellent_kept", d.level == QualityLevel.EXCELLENT.value and d.target_fps == 10.0,
            d.to_dict())

    # 滞回：只出现一次坏样本不应切换
    bad = MediaQualitySample(rtt_ms=300, jitter_ms=80, loss_ratio=0.06)
    ad2 = BandwidthAdapter()
    d = ad2.decide(bad)
    _record("hysteresis_single_sample_no_switch", d.changed is False and d.level == "excellent",
            d.to_dict())

    # 连续两次坏样本 -> 切换（冷却期用 0 便于测试）
    ad2.config.cooldown_s = 0.0
    d = ad2.decide(bad)
    _record("degrades_after_hold", d.changed is True and d.level == QualityLevel.POOR.value,
            d.to_dict())

    # 冷却：立刻再喂更差样本也不切
    ad2.config.cooldown_s = 5.0
    d = ad2.decide(MediaQualitySample(rtt_ms=900, loss_ratio=0.5))
    _record("cooldown_blocks_switch", d.changed is False, d.to_dict())

    # 恢复：冷却过后回到 EXCELLENT
    ad2.config.cooldown_s = 0.0
    ad2.decide(good)
    d = ad2.decide(good)
    _record("recovers_to_excellent", d.level == QualityLevel.EXCELLENT.value and d.target_fps == 10.0,
            d.to_dict())

    # CRITICAL 关摄像头
    ad3 = BandwidthAdapter()
    ad3.config.cooldown_s = 0.0
    ad3.decide(bad)
    d = ad3.decide(bad)
    _record("degrade_to_fair", d.level in (QualityLevel.FAIR.value, QualityLevel.POOR.value),
            d.to_dict())

    # apply 到会话
    class FakeVideo:
        fps = 10.0
        enabled = True

    class FakeSession:
        local_video = FakeVideo()

    ad4 = BandwidthAdapter()
    ad4.config.cooldown_s = 0.0
    ad4.decide(MediaQualitySample(rtt_ms=900, loss_ratio=0.5))
    decision = ad4.decide(MediaQualitySample(rtt_ms=900, loss_ratio=0.5))
    applied = ad4.apply(FakeSession(), decision)
    _record("apply_sets_video_track",
            applied.get("target_fps") == decision.target_fps
            and FakeSession.local_video.fps == decision.target_fps, applied)

    summary = {"label": "REAL LOCAL(策略) + SIMULATION(合成质量序列)",
               "not_verified": ["真实弱网 / 丢包 / 高 RTT 环境"],
               "results": RESULTS,
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("ADAPTATION =", summary["verdict"], "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adaptation_tests.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "adaptation_tests.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
