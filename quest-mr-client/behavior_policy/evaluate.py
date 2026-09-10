"""Behavior Policy 离线验收。

评价不只看 loss，还看：
- 每个场景的 top-1 行为是否合理；
- 硬负样本拒绝率；
- 连续参数误差；
- 关键场景是否覆盖。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from .model import load_weights_json
from .schema import BEHAVIOR_NAMES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=str,
                        default="behavior_policy/artifacts/behavior_policy_v1.json")
    parser.add_argument("--data", type=str,
                        default="behavior_policy/data/behavior_train.npz")
    parser.add_argument("--out", type=str,
                        default="behavior_policy/artifacts/evaluation_v1.json")
    args = parser.parse_args()

    model = load_weights_json(args.weights)
    raw = np.load(args.data)
    features = raw["features"].astype(np.float32)
    labels = raw["labels"].astype(np.float32)
    params = raw["params"].astype(np.float32)
    hard_negatives = raw["hard_negatives"].astype(np.int8)
    groups = raw["groups"].astype(np.int32)

    group_results = []
    top1 = 0
    hard_total = 0
    hard_rejected = 0
    param_errors = []
    with torch.no_grad():
        for group in np.unique(groups):
            indices = np.where(groups == group)[0]
            x = torch.from_numpy(features[indices]).float()
            logits, pred_params = model(x)
            best = int(torch.argmax(logits).item())
            predicted = BEHAVIOR_NAMES[best]
            expected = BEHAVIOR_NAMES[int(np.argmax(labels[indices]))]
            top1 += int(predicted == expected)
            hn = np.where(hard_negatives[indices] == 1)[0]
            for pos in hn:
                hard_total += 1
                hard_rejected += int(float(logits[pos]) < float(logits.max()))
            pos = int(np.argmax(labels[indices]))
            if labels[indices[pos]] > 0.5:
                param_errors.append(
                    float(torch.abs(pred_params[pos] -
                                    torch.from_numpy(params[indices[pos]]).float()
                                    ).mean().item()))
            if len(group_results) < 200:
                group_results.append({
                    "group": int(group),
                    "expected": expected,
                    "predicted": predicted,
                    "confidence": float(torch.sigmoid(logits[best]).item()),
                })
    report = {
        "top1_accuracy": top1 / max(1, len(np.unique(groups))),
        "hard_negative_rejection": hard_rejected / max(1, hard_total),
        "param_mae": float(np.mean(param_errors)) if param_errors else 0.0,
        "groups": int(len(np.unique(groups))),
        "samples": group_results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("top1_accuracy", "hard_negative_rejection", "param_mae", "groups")},
                     ensure_ascii=False))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
