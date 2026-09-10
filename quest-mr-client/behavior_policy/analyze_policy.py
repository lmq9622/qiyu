"""分析策略的 top-1 / top-3 / 混淆行为，用于判断是否需要扩数据或换模型。"""
from __future__ import annotations

import argparse
from collections import Counter
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
    args = parser.parse_args()
    model = load_weights_json(args.weights)
    raw = np.load(args.data)
    features = raw["features"].astype(np.float32)
    labels = raw["labels"].astype(np.float32)
    groups = raw["groups"].astype(np.int32)

    top1 = 0
    top3 = 0
    total = 0
    confusion = Counter()
    per_expected = Counter()
    per_correct = Counter()
    with torch.no_grad():
        for group in np.unique(groups):
            indices = np.where(groups == group)[0]
            logits, _ = model(torch.from_numpy(features[indices]).float())
            order = torch.argsort(logits, descending=True).tolist()
            expected_index = int(np.argmax(labels[indices]))
            expected = BEHAVIOR_NAMES[expected_index]
            predicted = BEHAVIOR_NAMES[order[0]]
            total += 1
            per_expected[expected] += 1
            if predicted == expected:
                top1 += 1
                per_correct[expected] += 1
            if expected_index in order[:3]:
                top3 += 1
            if predicted != expected:
                confusion[(expected, predicted)] += 1

    print(f"top1={top1 / max(1, total):.4f} top3={top3 / max(1, total):.4f} "
          f"groups={total}")
    print("per_expected:")
    for name, count in per_expected.most_common():
        print(f"  {name:20s} n={count:5d} top1={per_correct[name] / max(1, count):.3f}")
    print("top_confusion:")
    for (expected, predicted), count in confusion.most_common(30):
        print(f"  {expected:20s} -> {predicted:20s} n={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
