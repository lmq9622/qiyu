# -*- coding: utf-8 -*-
"""显存/内存采样器：在跑真模型时记录 GPU 专用显存峰值。

Windows 上用性能计数器：
  \GPU Adapter Memory(*)\Dedicated Usage   —— 适配器视角的专用显存占用
  \GPU Process Memory(*)\Dedicated Usage   —— 进程视角
再叠加进程 RSS。

用法：
  python -m runtime.omni.smoke.vram_probe -- <要跑的命令...>
  python -m runtime.omni.smoke.vram_probe --sample 5          # 只采 5 秒基线
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import threading
import time
from pathlib import Path


def _ps(cmd: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def read_gpu_dedicated_mb() -> float:
    """GPU 适配器专用显存总占用（MB）。"""
    out = _ps("(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory "
              "-ErrorAction SilentlyContinue | "
              "Measure-Object -Property DedicatedUsage -Sum).Sum")
    try:
        return round(float(out.strip()) / 1048576.0, 1)
    except Exception:
        return 0.0


def read_gpu_committed_mb() -> float:
    """GPU 提交内存（含共享），MB。"""
    out = _ps("(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory "
              "-ErrorAction SilentlyContinue | "
              "Measure-Object -Property DedicatedUsage -Sum).Sum")
    try:
        return round(float(out.strip()) / 1048576.0, 1)
    except Exception:
        return 0.0


def read_proc_rss_mb(pid: int) -> float:
    out = _ps(f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).WorkingSet64")
    try:
        return round(float(out.strip()) / 1048576.0, 1)
    except Exception:
        return 0.0


def read_proc_gpu_mb(pid: int) -> float:
    """该进程自己的 GPU 专用显存占用（MB）。

    只看整机合计没有意义：本机 iGPU(780M) 与 ToDesk/GameViewer 虚拟显示器
    会让「全适配器合计」长期停在 ~10GB。真正要测的是 omni 进程自己吃了多少。
    实例名形如 ``pid_12345_luid_0x00000000_0x0000ABCD_phys_0``。
    """
    if not pid:
        return 0.0
    cmd = ("(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory "
           f"-ErrorAction SilentlyContinue | Where-Object {{ $_.Name -like 'pid_{pid}_*' }} | "
           "Measure-Object -Property DedicatedUsage -Sum).Sum")
    out = _ps(cmd, timeout=25)
    try:
        return round(float(out.strip()) / 1048576.0, 1)
    except Exception:
        return 0.0


class Sampler:
    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self.samples: list = []
        self._stop = threading.Event()
        self._t: threading.Thread | None = None
        self.peak_gpu = 0.0
        self.peak_rss = 0.0
        self.peak_proc_gpu = 0.0
        self._pid = 0

    def watch_pid(self, pid: int) -> None:
        self._pid = pid

    def _loop(self) -> None:
        while not self._stop.is_set():
            gpu = read_gpu_dedicated_mb()
            rss = read_proc_rss_mb(self._pid) if self._pid else 0.0
            pgpu = read_proc_gpu_mb(self._pid)
            self.samples.append((round(time.time(), 2), gpu, rss))
            self.peak_gpu = max(self.peak_gpu, gpu)
            self.peak_rss = max(self.peak_rss, rss)
            self.peak_proc_gpu = max(self.peak_proc_gpu, pgpu)
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=5)

    def summary(self) -> dict:
        return {
            "peak_gpu_dedicated_mb": round(self.peak_gpu, 1),
            "peak_proc_gpu_mb": round(self.peak_proc_gpu, 1),
            "peak_proc_rss_mb": round(self.peak_rss, 1),
            "samples": len(self.samples),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="显存采样器")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--sample", type=float, default=0.0, help="只采基线 N 秒")
    ap.add_argument("--out", default="", help="采样 CSV 输出路径")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- 之后的命令")
    args = ap.parse_args()

    base = read_gpu_dedicated_mb()
    print(f"基线 GPU 专用显存: {base} MB")

    if args.sample and not args.cmd:
        s = Sampler(args.interval)
        s.start()
        time.sleep(args.sample)
        s.stop()
        print("采样:", s.summary())
        return 0

    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        ap.error("需要 -- <命令>")

    s = Sampler(args.interval)
    s.start()
    t0 = time.time()
    proc = subprocess.Popen(cmd)
    s.watch_pid(proc.pid)
    rc = proc.wait()
    s.stop()
    dur = time.time() - t0

    # 峰值还可能出现在进程退出后一瞬间（释放前），补采一次
    peak = max(s.peak_gpu, read_gpu_dedicated_mb())

    print("-" * 60)
    print(f"命令退出码 : {rc}")
    print(f"耗时       : {dur:.1f}s")
    print(f"基线显存   : {base} MB")
    print(f"峰值显存   : {round(peak,1)} MB   (净增 {round(peak - base,1)} MB)")
    print(f"进程GPU峰值: {s.peak_proc_gpu} MB   <-- 这才是模型自身占用")
    print(f"进程 RSS峰 : {s.peak_rss} MB")
    print("-" * 60)

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "gpu_dedicated_mb", "proc_rss_mb"])
            w.writerows(s.samples)
        print("采样已写入", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
