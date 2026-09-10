"""自动生成 Behavior Policy 训练数据。

用法：
    python -m behavior_policy.generate_data --episodes 500 --steps 12
    python -m behavior_policy.generate_data --episodes 5000 --steps 20
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .schema import BEHAVIOR_NAMES, FEATURE_NAMES, PARAM_NAMES
from .simulator import generate_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--output", type=str,
                        default="behavior_policy/data/behavior_train.npz")
    args = parser.parse_args()

    data = generate_dataset(seed=args.seed, episodes=args.episodes,
                            steps_per_episode=args.steps)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        features=np.asarray(data["features"], dtype=np.float32),
        labels=np.asarray(data["labels"], dtype=np.float32),
        soft_targets=np.asarray(data["soft_targets"], dtype=np.float32),
        params=np.asarray(data["params"], dtype=np.float32),
        hard_negatives=np.asarray(data["hard_negatives"], dtype=np.int8),
        groups=np.asarray(data["groups"], dtype=np.int32),
    )
    meta = {
        "episodes": args.episodes,
        "steps_per_episode": args.steps,
        "rows": len(data["features"]),
        "groups": len(data["group_meta"]),
        "feature_names": FEATURE_NAMES,
        "behavior_names": BEHAVIOR_NAMES,
        "param_names": PARAM_NAMES,
        "sample_meta": data["group_meta"][:200],
    }
    meta_path = output.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output} rows={len(data['features'])} groups={len(data['group_meta'])}")
    print(f"wrote {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
