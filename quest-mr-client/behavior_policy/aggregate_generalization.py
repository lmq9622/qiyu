"""合并多个分块 OOD/Long-Horizon 报告。"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _weighted_dicts(items, weights):
    keys = set()
    for value in items:
        keys.update(value.keys())
    out = {}
    total = sum(weights) or 1.0
    for key in sorted(keys):
        out[key] = sum(float(value.get(key, 0.0)) * weight
                       for value, weight in zip(items, weights)) / total
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.reports]

    iid_reports = [r for r in reports if r["counts"]["iid_groups"] > 0] or reports[:1]
    ood_reports = [r for r in reports if r["counts"]["ood_groups"] > 0] or reports[:1]
    long_reports = [r for r in reports if r["counts"]["long_steps"] > 0] or reports[:1]
    iid_weights = [max(1, r["counts"]["iid_groups"]) for r in iid_reports]
    ood_weights = [max(1, r["counts"]["ood_groups"]) for r in ood_reports]
    long_weights = [max(1, r["counts"]["long_steps"]) for r in long_reports]

    iid = _weighted_dicts([r["iid"] for r in iid_reports], iid_weights)
    ood = _weighted_dicts([r["ood"] for r in ood_reports], ood_weights)
    long_horizon = _weighted_dicts([r["long_horizon"] for r in long_reports], long_weights)
    params = {"iid": {}, "ood": {}}
    param_names = sorted(reports[0]["params"]["iid"].keys())
    params["iid"] = {
        name: _weighted_dicts(
            [r["params"]["iid"][name] for r in iid_reports], iid_weights)
        for name in param_names
    }
    params["ood"] = {
        name: _weighted_dicts(
            [r["params"]["ood"][name] for r in ood_reports], ood_weights)
        for name in param_names
    }
    delta = {
        key: ood.get(key, 0.0) - iid.get(key, 0.0)
        for key in ("top1", "top3", "hard_negative_rejection",
                    "invalid_action_rate", "goal_abandonment_rate",
                    "action_contradiction_rate")
    }
    arbitration_counts = Counter(
        (r["arbitration"]["switch_margin"], r["arbitration"]["hard_penalty"])
        for r in reports)
    arbitration = arbitration_counts.most_common(1)[0][0]
    recommendation = reports[0]["recommendation"]
    needs_training = (
        ood["top1"] < 0.55 or
        ood["invalid_action_rate"] > 0.05 or
        long_horizon["action_oscillation_rate"] > 0.12 or
        long_horizon["stale_goal_rate"] > 0.15
    )
    report = {
        "sources": args.reports,
        "counts": {
            "iid_groups": sum(r["counts"]["iid_groups"] for r in reports),
            "ood_groups": sum(r["counts"]["ood_groups"] for r in reports),
            "long_steps": sum(r["counts"]["long_steps"] for r in reports),
        },
        "iid": iid,
        "ood": ood,
        "delta_ood_minus_iid": delta,
        "params": params,
        "long_horizon": long_horizon,
        "arbitration": {
            "switch_margin": arbitration[0],
            "hard_penalty": arbitration[1],
        },
        "recommendation": {
            "continue_training": bool(needs_training),
            "reason": ("OOD 或 Long-Horizon 低于阈值，需要继续训练/升级"
                       if needs_training else
                       "当前轻量 Behavior Scorer + Utility + Reflex 指标稳定，保持 v1 并优先真机验证"),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
