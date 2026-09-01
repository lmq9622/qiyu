"""
栖语 (Qiyu) - RAG 文档处理器
自动监控目录、读取文档、分块索引
"""

import os
import time
import threading
from pathlib import Path
from typing import Set
from datetime import datetime

from loguru import logger

from pathutil import get_data_dir

# 监控的目录
UPLOADS_DIR = get_data_dir() / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


class DirectoryWatcher:
    """目录监控器（轮询方式，不依赖 watchdog）"""
    
    def __init__(self, watch_dir: Path, interval: int = 5):
        self.watch_dir = watch_dir
        self.interval = interval
        self._known_files: Set[str] = set()
        self._callbacks = []
        self._running = False
        self._thread: threading.Thread = None
    
    def on_change(self, callback):
        """注册文件变化回调"""
        self._callbacks.append(callback)
    
    def _scan(self):
        """扫描目录变化"""
        current_files = set()
        for filepath in self.watch_dir.rglob("*"):
            if filepath.is_file():
                try:
                    mtime = filepath.stat().st_mtime
                    current_files.add(f"{filepath}:{mtime}")
                except Exception:
                    pass
        
        # 检测新增或修改的文件
        new_files = current_files - self._known_files
        if new_files:
            for item in new_files:
                filepath = Path(item.split(":")[0])
                for callback in self._callbacks:
                    try:
                        callback(filepath)
                    except Exception as e:
                        logger.error(f"RAG 回调错误: {e}")
        
        self._known_files = current_files
    
    def start(self):
        """启动监控"""
        self._running = True
        
        def watch_loop():
            # 首次扫描
            self._scan()
            while self._running:
                time.sleep(self.interval)
                self._scan()
        
        self._thread = threading.Thread(target=watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"[RAG] 开始监控目录: {self.watch_dir}")
    
    def stop(self):
        """停止监控"""
        self._running = False


class RAGManager:
    """RAG 管理器"""
    
    def __init__(self):
        self.watcher = DirectoryWatcher(UPLOADS_DIR, interval=10)
        self._knowledge_base = None
    
    def setup(self, knowledge_base):
        """设置知识库"""
        self._knowledge_base = knowledge_base
        
        # 注册文件变化回调
        def on_file_changed(filepath: Path):
            if self._knowledge_base:
                self._knowledge_base.index_document(filepath)
        
        self.watcher.on_change(on_file_changed)
    
    def start(self):
        """启动 RAG 监控"""
        # 先索引已有文件
        if self._knowledge_base:
            count = self._knowledge_base.index_directory(UPLOADS_DIR)
            logger.info(f"[RAG] 初始索引完成，共 {count} 个文档块")
        
        self.watcher.start()
    
    def stop(self):
        self.watcher.stop()


# ============ 全局实例 ============
_rag_manager = None

def get_rag_manager() -> RAGManager:
    global _rag_manager
    if _rag_manager is None:
        _rag_manager = RAGManager()
    return _rag_manager
