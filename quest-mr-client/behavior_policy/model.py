"""轻量 Behavior Scorer 模型与权重导出。

不是 VLA，也不是 diffusion policy：
- 输入固定行为特征；
- 输出候选行为得分 + 连续参数；
- 在 Quest 上用 C# 纯矩阵运算执行。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import torch
from torch import nn

from .schema import (
    BEHAVIOR_NAMES,
    FEATURE_NAMES,
    INPUT_DIM,
    MODEL_TYPE,
    MODEL_VERSION,
    PARAM_NAMES,
    PARAM_OFFSET,
    PARAM_SCALE,
    SCHEMA_VERSION,
)


class BehaviorScorer(nn.Module):
    def __init__(self, hidden_sizes=(256, 128)) -> None:
        super().__init__()
        layers = []
        last = INPUT_DIM
        for size in hidden_sizes:
            layers += [nn.Linear(last, size), nn.ReLU()]
            last = size
        self.trunk = nn.Sequential(*layers)
        self.score_head = nn.Linear(last, 1)
        self.param_head = nn.Linear(last, len(PARAM_NAMES))

    def forward(self, features: torch.Tensor):
        hidden = self.trunk(features)
        score = self.score_head(hidden).squeeze(-1)
        params = torch.sigmoid(self.param_head(hidden))
        return score, params


def export_weights_json(model: BehaviorScorer, output_path: str | Path,
                        *, metrics: Dict | None = None) -> Path:
    """导出 Unity TinyBehaviorPolicy 可解析的 JSON。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    linears = [m for m in model.trunk if isinstance(m, nn.Linear)]
    if len(linears) != 2:
        raise ValueError("第一版导出器要求正好 2 层隐藏层")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "model_version": MODEL_VERSION,
        "input_dim": INPUT_DIM,
        "hidden_sizes": [layer.out_features for layer in linears],
        "layers": [
            {
                "w": layer.weight.detach().cpu().tolist(),
                "b": layer.bias.detach().cpu().tolist(),
            }
            for layer in linears
        ],
        "score_layer": {
            "w": model.score_head.weight.detach().cpu().tolist(),
            "b": model.score_head.bias.detach().cpu().tolist(),
        },
        "param_layer": {
            "w": model.param_head.weight.detach().cpu().tolist(),
            "b": model.param_head.bias.detach().cpu().tolist(),
        },
        "feature_names": FEATURE_NAMES,
        "behavior_names": BEHAVIOR_NAMES,
        "param_names": PARAM_NAMES,
        "param_scale": PARAM_SCALE,
        "param_offset": PARAM_OFFSET,
        "metrics": metrics or {},
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return output_path


def load_weights_json(path: str | Path) -> BehaviorScorer:
    """从 Unity 同格式 JSON 还原 PyTorch 模型（用于离线评估）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    hidden_sizes = tuple(int(x) for x in payload.get("hidden_sizes", [128, 64]))
    model = BehaviorScorer(hidden_sizes=hidden_sizes)
    linears = [m for m in model.trunk if isinstance(m, nn.Linear)]
    with torch.no_grad():
        for layer, data in zip(linears, payload["layers"]):
            layer.weight.copy_(torch.tensor(data["w"], dtype=torch.float32))
            layer.bias.copy_(torch.tensor(data["b"], dtype=torch.float32))
        model.score_head.weight.copy_(torch.tensor(payload["score_layer"]["w"],
                                                   dtype=torch.float32))
        model.score_head.bias.copy_(torch.tensor(payload["score_layer"]["b"],
                                                 dtype=torch.float32))
        model.param_head.weight.copy_(torch.tensor(payload["param_layer"]["w"],
                                                   dtype=torch.float32))
        model.param_head.bias.copy_(torch.tensor(payload["param_layer"]["b"],
                                                 dtype=torch.float32))
    model.eval()
    return model


__all__ = ["BehaviorScorer", "export_weights_json", "load_weights_json"]
