"""P4 物体识别：复用 Qiyu VisionProvider（主模型多模态），不新建视觉模型。

输入：Quest Passthrough Camera 的 JPEG 帧 + 分辨率元数据。
输出：objects = [{id,label,confidence,bbox_2d,image_width,image_height}]，
      由 Quest 侧结合深度/场景射线投影到世界坐标。

说明：通用多模态模型能给出语义与粗定位；对“杯子/手机”等小物体，
若需要更高框精度，应切换到 Meta AI Blocks ObjectDetectionAgent
（Unity Inference Engine + YOLO）或专用检测服务，本模块接口保持不变。
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any, Optional

from loguru import logger


class VisionDetectorError(RuntimeError):
    pass


_PROMPT = """你在帮一个 MR 角色识别真实房间里的物体。
只看图片，找出场景 API 没有建模的独立小物体（例如杯子、手机、书、遥控器、钥匙、瓶子、耳机等），
忽略地面/墙/天花板/门/窗/桌子/椅子/沙发/柜子这类场景语义物体。

只输出 JSON，不要 Markdown、不要解释：
{
  "objects": [
    {
      "label": "cup",
      "label_cn": "杯子",
      "confidence": 0.0~1.0,
      "bbox_2d": [xmin, ymin, xmax, ymax]
    }
  ]
}
bbox_2d 用归一化坐标（0~1，左上角为原点）。看不清或没有目标就返回 {"objects": []}。
最多 8 个，宁少勿假。
"""


async def detect_objects(
    image_jpeg: bytes,
    *,
    image_width: int = 0,
    image_height: int = 0,
    prompt: str = "",
) -> dict[str, Any]:
    if not image_jpeg:
        raise VisionDetectorError("empty_image")
    provider = _get_vision_provider()
    if provider is None:
        raise VisionDetectorError("vision_provider_not_registered")
    status = provider.status()
    if not status.available:
        raise VisionDetectorError(f"vision_unavailable:{status.reason}")

    data_url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
    user_prompt = _PROMPT + (f"\n额外关注：{prompt}" if prompt else "")
    t0 = time.time()
    text = await provider.describe(data_url, user_prompt)
    elapsed_ms = int((time.time() - t0) * 1000)
    parsed = _extract_json(text)
    raw_objects = parsed.get("objects") if isinstance(parsed, dict) else None
    objects: list[dict] = []
    if isinstance(raw_objects, list):
        for item in raw_objects[:8]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("label_cn") or "").strip()
            if not label:
                continue
            bbox = _normalize_bbox(item.get("bbox_2d"), image_width, image_height)
            if bbox is None:
                continue
            objects.append({
                "id": f"vision-{uuid.uuid4().hex[:10]}",
                "label": label,
                "label_cn": str(item.get("label_cn") or "").strip(),
                "confidence": _clamp(item.get("confidence"), 0.0, 1.0, 0.5),
                "bbox_2d": bbox,
                "source": "cloud_vision",
            })
    logger.info(f"[QuestVision] 检测完成 objects={len(objects)} took={elapsed_ms}ms")
    return {
        "objects": objects,
        "image_width": int(image_width),
        "image_height": int(image_height),
        "took_ms": elapsed_ms,
        "engine": getattr(provider, "id", "vision"),
    }


def _get_vision_provider():
    try:
        from runtime.manager import get_runtime_manager
        from runtime.providers import ProviderKind
    except Exception as e:
        logger.warning(f"[QuestVision] 无法加载 Runtime Provider: {e}")
        return None
    try:
        manager = get_runtime_manager()
        if manager is None:
            return None
        return manager.registry.get(ProviderKind.VISION)
    except Exception as e:
        logger.warning(f"[QuestVision] 获取 VisionProvider 失败: {e}")
        return None


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_bbox(value: Any, width: int, height: int) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        nums = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    xmin, ymin, xmax, ymax = nums
    # 归一化坐标 → 像素
    if max(abs(v) for v in nums) <= 1.5:
        w = float(width) if width > 0 else 1280.0
        h = float(height) if height > 0 else 960.0
        xmin, xmax = xmin * w, xmax * w
        ymin, ymax = ymin * h, ymax * h
    xmin, xmax = min(xmin, xmax), max(xmin, xmax)
    ymin, ymax = min(ymin, ymax), max(ymin, ymax)
    if xmax - xmin < 1.0 or ymax - ymin < 1.0:
        return None
    return [round(xmin, 1), round(ymin, 1), round(xmax, 1), round(ymax, 1)]


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


__all__ = ["VisionDetectorError", "detect_objects"]
