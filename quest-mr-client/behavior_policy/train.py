"""训练轻量 Behavior Scorer（行为克隆 + 偏好排序 + 硬负样本）。

训练在 GPU 上做整批张量计算，不在 Python 里逐组循环。

用法（x99 CUDA）：
    /home/lmq/ComfyUI/.venv/bin/python -m behavior_policy.train \
        --data behavior_policy/data/behavior_train.npz \
        --out behavior_policy/artifacts/behavior_policy_v1.json \
        --device cuda --batch-groups 1024 --epochs 24
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from .model import BehaviorScorer, export_weights_json


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _group_indices(groups: np.ndarray, selected: set[int] | None = None
                   ) -> dict[int, np.ndarray]:
    result: dict[int, np.ndarray] = {}
    targets = selected if selected is not None else set(int(x) for x in np.unique(groups))
    for group in targets:
        indices = np.where(groups == group)[0]
        if len(indices):
            result[int(group)] = indices
    return result


def _make_batch(features: np.ndarray, labels: np.ndarray, soft_targets: np.ndarray,
                params: np.ndarray, hard_negatives: np.ndarray,
                group_map: dict[int, np.ndarray], batch_groups: list[int],
                device: torch.device):
    """把变长候选组 padding 成 [B, L, D] 张量，一次前向/一次 loss。"""
    max_len = max(len(group_map[g]) for g in batch_groups)
    batch_size = len(batch_groups)
    dim = features.shape[1]
    param_dim = params.shape[1]
    x = np.zeros((batch_size, max_len, dim), dtype=np.float32)
    label = np.zeros((batch_size, max_len), dtype=np.float32)
    soft = np.zeros((batch_size, max_len), dtype=np.float32)
    hard = np.zeros((batch_size, max_len), dtype=np.float32)
    param = np.zeros((batch_size, max_len, param_dim), dtype=np.float32)
    param_mask = np.zeros((batch_size, max_len), dtype=np.float32)
    mask = np.zeros((batch_size, max_len), dtype=np.float32)

    for row, group in enumerate(batch_groups):
        indices = group_map[group]
        length = len(indices)
        x[row, :length] = features[indices]
        label[row, :length] = labels[indices]
        soft[row, :length] = soft_targets[indices]
        hard[row, :length] = hard_negatives[indices]
        mask[row, :length] = 1.0
        positive = np.where(labels[indices] > 0.5)[0]
        if len(positive):
            pos = positive[0]
            param[row, pos] = params[indices[pos]]
            param_mask[row, pos] = 1.0
    return {
        "x": torch.from_numpy(x).to(device),
        "label": torch.from_numpy(label).to(device),
        "soft": torch.from_numpy(soft).to(device),
        "hard": torch.from_numpy(hard).to(device),
        "param": torch.from_numpy(param).to(device),
        "param_mask": torch.from_numpy(param_mask).to(device),
        "mask": torch.from_numpy(mask).to(device),
    }


def _batch_loss(model: BehaviorScorer, batch: dict) -> torch.Tensor:
    logits, pred_params = model(batch["x"])
    mask = batch["mask"]

    # listwise soft-target cross entropy（每个 group 内做 softmax）。
    log_probs = F.log_softmax(logits.masked_fill(mask < 0.5, -1e9), dim=1)
    listwise = -(batch["soft"] * log_probs).sum(dim=1)

    # 正样本 BCE + 硬负样本拒绝。
    bce = F.binary_cross_entropy_with_logits(
        logits, batch["label"], reduction="none") * mask
    bce = bce.sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)

    # 正样本 vs 每个硬负样本的 margin ranking。
    positive_logit = (logits * batch["label"]).sum(dim=1, keepdim=True)
    margin = F.relu(positive_logit - logits - 0.8) * batch["hard"]
    rank = margin.sum(dim=1) / batch["hard"].sum(dim=1).clamp_min(1.0)

    # 连续参数只监督每个 group 的专家正样本。
    param_err = (pred_params - batch["param"]) ** 2
    param_mask = batch["param_mask"].unsqueeze(-1)
    param_loss = (param_err * param_mask).sum() / (param_mask.sum() * pred_params.shape[-1]).clamp_min(1.0)

    return (listwise + 0.25 * bce + 0.35 * rank).mean() + 0.2 * param_loss


@torch.no_grad()
def _evaluate(model: BehaviorScorer, features: np.ndarray, labels: np.ndarray,
              soft_targets: np.ndarray, params: np.ndarray,
              hard_negatives: np.ndarray, group_map: dict[int, np.ndarray],
              device: torch.device, batch_groups: int = 512) -> dict:
    model.eval()
    order = list(group_map.keys())
    top1 = 0
    total = 0
    hard_total = 0
    hard_rejected = 0
    param_errors = []
    for start in range(0, len(order), batch_groups):
        batch_groups_list = order[start:start + batch_groups]
        batch = _make_batch(features, labels, soft_targets, params, hard_negatives,
                            group_map, batch_groups_list, device)
        logits, pred_params = model(batch["x"])
        mask = batch["mask"]
        masked = logits.masked_fill(mask < 0.5, -1e9)
        best = masked.argmax(dim=1)
        rows = torch.arange(logits.shape[0], device=device)
        top1 += int((batch["label"][rows, best] > 0.5).sum().item())
        total += len(batch_groups_list)
        # 每个硬负样本只要低于组内最大值即视为被拒绝。
        group_max = masked.max(dim=1, keepdim=True).values
        hard_rejected += int(((logits < group_max) & (batch["hard"] > 0.5)).sum().item())
        hard_total += int((batch["hard"] > 0.5).sum().item())
        pos_mask = batch["param_mask"] > 0.5
        if pos_mask.any():
            err = torch.abs(pred_params - batch["param"]).mean(dim=-1)
            param_errors.append(err[pos_mask].mean().item())
    return {
        "top1_accuracy": top1 / max(1, total),
        "hard_negative_rejection": hard_rejected / max(1, hard_total),
        "param_mae": float(np.mean(param_errors)) if param_errors else 0.0,
        "groups": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str,
                        default="behavior_policy/data/behavior_train.npz")
    parser.add_argument("--out", type=str,
                        default="behavior_policy/artifacts/behavior_policy_v1.json")
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--device", type=str,
                        default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--batch-groups", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--unity-resources", type=str,
                        default="../unity-client/Assets/QiyuQuest/Resources/Qiyu/behavior_policy_v1.json")
    args = parser.parse_args()
    _set_seed(args.seed)

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("指定了 cuda，但 torch.cuda.is_available()=False")
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        print(f"device={device} gpu={torch.cuda.get_device_name(0)} "
              f"count={torch.cuda.device_count()}")

    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(f"训练数据不存在: {data_path}")
    raw = np.load(data_path)
    features = raw["features"].astype(np.float32)
    labels = raw["labels"].astype(np.float32)
    soft_targets = raw["soft_targets"].astype(np.float32)
    params = raw["params"].astype(np.float32)
    hard_negatives = raw["hard_negatives"].astype(np.int8)
    groups = raw["groups"].astype(np.int32)

    group_ids = np.unique(groups)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(group_ids)
    split = max(1, int(len(group_ids) * 0.82))
    train_groups = set(int(x) for x in group_ids[:split])
    val_groups = set(int(x) for x in group_ids[split:])
    if not val_groups:
        val_groups = {int(group_ids[-1])}
        train_groups.discard(int(group_ids[-1]))
    train_map = _group_indices(groups, train_groups)
    val_map = _group_indices(groups, val_groups)

    model = BehaviorScorer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    best_state = None
    best_score = -1e9
    history = []

    for epoch in range(args.epochs):
        model.train()
        order = list(train_map.keys())
        random.shuffle(order)
        total_loss = 0.0
        batches = 0
        for start in range(0, len(order), args.batch_groups):
            batch_groups_list = order[start:start + args.batch_groups]
            batch = _make_batch(features, labels, soft_targets, params,
                                hard_negatives, train_map, batch_groups_list, device)
            optimizer.zero_grad()
            loss = _batch_loss(model, batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total_loss += float(loss.item())
            batches += 1

        metrics = _evaluate(model, features, labels, soft_targets, params,
                            hard_negatives, val_map, device)
        score = (metrics["top1_accuracy"] * 0.55 +
                 metrics["hard_negative_rejection"] * 0.35 +
                 max(0.0, 1.0 - metrics["param_mae"]) * 0.10)
        history.append({"epoch": epoch + 1, "loss": total_loss / max(1, batches),
                        "val": metrics, "selection_score": score})
        if score > best_score:
            best_score = score
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        if (epoch + 1) % 2 == 0 or epoch == args.epochs - 1:
            print(f"epoch={epoch + 1:02d} loss={total_loss / max(1, batches):.4f} "
                  f"top1={metrics['top1_accuracy']:.3f} "
                  f"hard_neg={metrics['hard_negative_rejection']:.3f} "
                  f"param_mae={metrics['param_mae']:.3f}", flush=True)

    if best_state is not None:
        model.load_state_dict(best_state)
    final_metrics = _evaluate(model, features, labels, soft_targets, params,
                              hard_negatives, val_map, device)
    out_path = Path(args.out)
    export_weights_json(model, out_path, metrics={
        "validation": final_metrics,
        "epochs": args.epochs,
        "training_rows": int(len(features)),
        "training_groups": int(len(group_ids)),
        "device": str(device),
    })
    out_path.with_suffix(".metrics.json").write_text(
        json.dumps({"validation": final_metrics, "history": history,
                    "artifact": str(out_path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"exported {out_path}")
    print(f"validation={json.dumps(final_metrics, ensure_ascii=False)}")

    unity_path = Path(args.unity_resources)
    if not unity_path.is_absolute():
        unity_path = (Path.cwd() / unity_path).resolve()
    if unity_path.parent.exists():
        unity_path.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"copied to Unity Resources: {unity_path}")
    else:
        print(f"Unity Resources 路径不存在，跳过复制: {unity_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
