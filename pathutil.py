"""
栖语 (Qiyu) - 数据目录统一解析
开发模式：项目根 /data
exe 模式（PyInstaller）：~/.ai_companion/data（持久化，避免写入临时解压目录）
可用环境变量 QIYU_DATA_DIR 覆盖
"""
import os
import sys
from pathlib import Path


def get_data_dir() -> Path:
    env_data = os.getenv("QIYU_DATA_DIR", "")
    if env_data:
        d = Path(env_data)
    elif hasattr(sys, "_MEIPASS"):
        d = Path(os.path.expanduser("~")) / ".ai_companion" / "data"
    else:
        d = Path(__file__).resolve().parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
