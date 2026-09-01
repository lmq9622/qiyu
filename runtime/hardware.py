# -*- coding: utf-8 -*-
"""Qiyu Runtime · 硬件检测与 Backend 能力探测（M2）。

- HardwareProfile：CPU / 核心数 / 内存 / GPU / 显存 / 驱动 / OS / 平台。
- BackendCapability：某个 backend 在某设备上的能力矩阵（text/vision/audio/...）。
- 不假设「检测到 GPU 就使用 GPU」：是否启用由 RuntimeManager 结合能力矩阵与
  微基准共同决定；优先级 NVIDIA+CUDA → Vulkan → CPU，但 CPU 在低端设备上
  可能比核显更合适。
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

try:
    import psutil
except Exception:  # pragma: no cover - 无 psutil 时降级为空探测
    psutil = None


@dataclass
class HardwareProfile:
    cpu_name: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    ram_mb: int = 0
    gpu_name: str = ""
    gpu_vendor: str = ""
    vram_mb: int = 0
    cuda_available: bool = False
    vulkan_available: bool = False
    driver: str = ""
    os_name: str = ""
    platform: str = ""

    def to_dict(self) -> dict:
        return {
            "cpu": {"name": self.cpu_name, "cores": self.cpu_cores, "threads": self.cpu_threads},
            "ram_mb": self.ram_mb,
            "gpu": {"name": self.gpu_name, "vendor": self.gpu_vendor, "vram_mb": self.vram_mb},
            "cuda_available": self.cuda_available,
            "vulkan_available": self.vulkan_available,
            "driver": self.driver,
            "os": self.os_name,
            "platform": self.platform,
        }


@dataclass
class BackendCapability:
    """某个 backend / 设备的能力矩阵（不是固定台词，是硬件能力）。"""
    backend: str                 # cpu / vulkan / cuda / metal / android / api
    device: str = ""             # 设备名
    vendor: str = ""
    vram_mb: int = 0
    text: bool = False
    vision: bool = False
    audio: bool = False
    realtime_audio: bool = False
    available: bool = False
    reason: str = ""             # 不可用时说明原因

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "device": self.device,
            "vendor": self.vendor,
            "vram_mb": self.vram_mb,
            "text": self.text,
            "vision": self.vision,
            "audio": self.audio,
            "realtime_audio": self.realtime_audio,
            "available": self.available,
            "reason": self.reason,
        }


class HardwareDetector:
    """设备探测（只读，无副作用；探测结果缓存）。"""

    def __init__(self) -> None:
        self._profile: Optional[HardwareProfile] = None

    def detect(self) -> HardwareProfile:
        if self._profile is not None:
            return self._profile
        prof = HardwareProfile(os_name=platform.system(), platform=platform.platform())
        if psutil is not None:
            try:
                prof.cpu_cores = psutil.cpu_count(logical=False) or 0
                prof.cpu_threads = psutil.cpu_count(logical=True) or 0
                prof.ram_mb = int((psutil.virtual_memory().total or 0) / 1024 / 1024)
            except Exception as e:
                logger.warning(f"[硬件] CPU/RAM 探测失败: {e}")
        prof.cpu_name = self._cpu_name()
        self._probe_gpu(prof)
        self._probe_cuda(prof)
        prof.vulkan_available = self._vulkan_available()
        self._profile = prof
        logger.info(
            f"[硬件] CPU={prof.cpu_name} 核心={prof.cpu_cores} RAM={prof.ram_mb}MB "
            f"GPU={prof.gpu_name or '无'} ({prof.gpu_vendor}) VRAM={prof.vram_mb}MB "
            f"CUDA={prof.cuda_available} Vulkan={prof.vulkan_available}"
        )
        return prof

    def _cpu_name(self) -> str:
        try:
            if platform.system() == "Windows":
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Processor).Name"],
                    capture_output=True, text=True, timeout=10,
                )
                name = (out.stdout or "").strip()
                if name:
                    return name
            if shutil.which("lscpu"):
                out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=10)
                for line in (out.stdout or "").splitlines():
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return platform.processor() or platform.machine()

    def _nvidia_smi(self):
        smi = shutil.which("nvidia-smi")
        if not smi and platform.system() == "Windows":
            for cand in (r"C:\Windows\System32\nvidia-smi.exe",
                         r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
                if os.path.exists(cand):
                    smi = cand
                    break
        return smi

    def _probe_gpu(self, prof: HardwareProfile) -> None:
        smi = self._nvidia_smi()
        if smi:
            try:
                out = subprocess.run(
                    [smi, "--query-gpu=name,memory.total,driver_version",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=15,
                )
                line = (out.stdout or "").strip().splitlines()
                if line:
                    parts = [p.strip() for p in line[0].split(",")]
                    prof.gpu_name = parts[0] if len(parts) > 0 else ""
                    prof.vram_mb = int(float(parts[1])) if len(parts) > 1 and parts[1].isdigit() else 0
                    prof.driver = parts[2] if len(parts) > 2 else ""
                    prof.gpu_vendor = "NVIDIA"
                    return
            except Exception as e:
                logger.debug(f"[硬件] nvidia-smi 探测失败: {e}")
        # 非 NVIDIA / 无 nvidia-smi：Windows 尝试 WMI（枚举全部显卡，跳过虚拟/远程适配器）
        if platform.system() == "Windows":
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_VideoController | "
                     "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"],
                    capture_output=True, text=True, timeout=15,
                )
                data = (out.stdout or "").strip()
                if data and data != "null":
                    import json as _json
                    try:
                        items = _json.loads(data)
                    except Exception:
                        items = []
                    if isinstance(items, dict):
                        items = [items]
                    best = None
                    for it in items:
                        name = str(it.get("Name") or "")
                        low = name.lower()
                        # 跳过虚拟/远程/基础显示适配器
                        if any(k in low for k in ("virtual", "remote", "display adapter",
                                                  "basic display", "todesk", "microsoft remote",
                                                  "rdp", "vnc")):
                            continue
                        try:
                            ram = int(it.get("AdapterRAM") or 0) // (1024 * 1024)
                        except Exception:
                            ram = 0
                        if "nvidia" in low:
                            score = (3, ram)
                        elif "amd" in low or "radeon" in low:
                            score = (2, ram)
                        elif "intel" in low:
                            score = (1, ram)
                        else:
                            score = (0, ram)
                        if best is None or score > best[0]:
                            best = (score, name, ram)
                    if best:
                        _, name, ram = best
                        prof.gpu_name = name
                        prof.vram_mb = ram
                        low = name.lower()
                        if "nvidia" in low:
                            prof.gpu_vendor = "NVIDIA"
                        elif "amd" in low or "radeon" in low:
                            prof.gpu_vendor = "AMD"
                        elif "intel" in low:
                            prof.gpu_vendor = "Intel"
                        else:
                            prof.gpu_vendor = "未知"
            except Exception as e:
                logger.debug(f"[硬件] WMI GPU 探测失败: {e}")

    def _probe_cuda(self, prof: HardwareProfile) -> None:
        if prof.gpu_vendor != "NVIDIA":
            prof.cuda_available = False
            return
        smi = self._nvidia_smi()
        if smi:
            try:
                out = subprocess.run(
                    [smi, "--query-gpu=compute_cap --format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=15,
                )
                cap = (out.stdout or "").strip()
                prof.cuda_available = bool(cap)
            except Exception:
                prof.cuda_available = False

    def _vulkan_available(self) -> bool:
        if shutil.which("vulkaninfo"):
            return True
        if platform.system() == "Windows" and os.path.exists(r"C:\Windows\System32\vulkaninfo.exe"):
            return True
        return False

    def probe_backends(self) -> list[BackendCapability]:
        """产出候选 Backend 能力矩阵（决定用哪个 backend，而不是写死）。"""
        prof = self.detect()
        caps: list[BackendCapability] = []
        # CUDA（仅 NVIDIA + 探测到 driver）
        if prof.gpu_vendor == "NVIDIA" and prof.cuda_available:
            caps.append(BackendCapability(
                backend="cuda", device=prof.gpu_name, vendor="NVIDIA",
                vram_mb=prof.vram_mb, text=True, vision=True, audio=False,
                realtime_audio=False, available=True,
            ))
        # Vulkan（跨 NVIDIA/AMD/Intel；可用性还取决于模型后端是否实现）
        if prof.vulkan_available:
            caps.append(BackendCapability(
                backend="vulkan", device=prof.gpu_name or "vulkan-device",
                vendor=prof.gpu_vendor, vram_mb=prof.vram_mb,
                text=True, vision=True, audio=False, realtime_audio=False,
                available=False,
                reason="Vulkan 驱动存在，但当前分发未内置 Vulkan 推理后端",
            ))
        # CPU：永远可用（Zero Setup 底线），文本能力可靠
        caps.append(BackendCapability(
            backend="cpu", device=prof.cpu_name or "cpu",
            vendor="CPU", vram_mb=0, text=True, vision=False, audio=False,
            realtime_audio=False, available=True,
        ))
        return caps
