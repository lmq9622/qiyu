# -*- coding: utf-8 -*-
"""Qiyu Runtime · 分层日志（规格§48）。

日志至少分六类，各自独立文件（同时保留默认控制台输出）：
- runtime.log       运行生命周期 / Provider / backend 状态
- conversation.log  聊天（用户消息 / AI 回复 / 主动消息 / 会话状态机）
- tool.log          工具 / 搜索 / 联网 / Agent 执行
- memory.log        记忆写入 / 检索 / 分级 / 整理
- performance.log   性能指标（TTFT / tok/s / 延迟 / 资源占用，见 runtime/perf.py）
- error.log         异常 / 堆栈（用户 UI 不展示内部错误堆栈，只落盘）

用法：各业务模块调用 `from runtime.logging_setup import get_logger, logger_conv, logger_tool, logger_mem`，
或直接使用带 tag 的 `log_conv(...)` / `log_tool(...)` / `log_mem(...)` 便捷函数。
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_configured = False
_LOG_DIR: Path | None = None


def configure_logging(log_dir: Path | None = None) -> Path:
    """初始化分层日志（幂等）。返回日志目录。

    - 默认目录：数据目录下 logs/（dev 模式 project/data/logs，exe 模式用户目录 logs）。
    - 保留 loguru 默认 stderr sink，另加五个分层文件 + 一个 error 专属文件。
    """
    global _configured, _LOG_DIR
    if _configured:
        return _LOG_DIR or log_dir
    if log_dir is None:
        try:
            from companion.state import get_data_dir
            base = get_data_dir()
        except Exception:
            from pathlib import Path as _P
            base = _P("data")
        log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_DIR = log_dir
    # 移除默认 sink 会影响现有 logger 输出，保留；文件用 filter 按 tag 分流
    _add_sink("runtime.log", lambda rec: rec["extra"].get("layer", "runtime") == "runtime")
    _add_sink("conversation.log", lambda rec: rec["extra"].get("layer") == "conversation")
    _add_sink("tool.log", lambda rec: rec["extra"].get("layer") == "tool")
    _add_sink("memory.log", lambda rec: rec["extra"].get("layer") == "memory")
    _add_sink("performance.log", lambda rec: rec["extra"].get("layer") == "performance")
    _add_sink("error.log", lambda rec: rec["level"].name == "ERROR" or rec["level"].name == "CRITICAL")
    _configured = True
    logger.info(f"[日志] 分层日志就绪: {log_dir}（runtime/conversation/tool/memory/performance/error）")
    return log_dir


def _add_sink(name: str, filt):
    try:
        logger.add(
            str(_LOG_DIR / name),
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
            enqueue=True,
            filter=filt,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name} | {message}",
        )
    except Exception as e:
        logger.warning(f"[日志] 添加 {name} sink 失败: {e}")


def get_logger(layer: str):
    """返回一个带固定 layer tag 的 logger（调用方直接 logger.info(...) 即可分流）。"""
    return logger.bind(layer=layer)


logger_conv = get_logger("conversation")
logger_tool = get_logger("tool")
logger_mem = get_logger("memory")
logger_perf = get_logger("performance")
logger_runtime = get_logger("runtime")

__all__ = [
    "configure_logging",
    "get_logger",
    "logger",
    "logger_conv",
    "logger_mem",
    "logger_perf",
    "logger_runtime",
    "logger_tool",
]
