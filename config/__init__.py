"""
栖语 (Qiyu) - 配置管理器
支持 YAML 配置加载、热重载、运行时修改
"""

import os
import sys
import yaml
import time
import threading
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

def _config_dir() -> Path:
    """配置目录：exe 模式优先使用 exe 同目录 config/（用户可编辑、独立更新，不随包重建），
    否则使用内置（PyInstaller 解压目录 / 源码目录）。"""
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).resolve().parent
        sidecar = exe_dir / "config"
        if (sidecar / "settings.yaml").exists() or (sidecar / "routes.yaml").exists():
            return sidecar
    return Path(__file__).parent


CONFIG_DIR = _config_dir()


class ConfigManager:
    """配置管理器，支持热重载"""
    
    def __init__(self):
        self._settings: dict = {}
        self._routes: dict = {}
        self._last_load_time: float = 0
        self._lock = threading.RLock()
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_watching = threading.Event()
        
        self._load_all()
        self._start_watcher()
    
    def _load_all(self):
        """加载所有配置文件"""
        with self._lock:
            # 加载设置
            settings_path = CONFIG_DIR / "settings.yaml"
            if settings_path.exists():
                with open(settings_path, "r", encoding="utf-8") as f:
                    self._settings = yaml.safe_load(f) or {}
                logger.info(f"加载设置配置: {settings_path}")
            else:
                logger.warning(f"设置配置文件不存在: {settings_path}")
                self._settings = {}
            
            # 加载路由规则
            routes_path = CONFIG_DIR / "routes.yaml"
            if routes_path.exists():
                with open(routes_path, "r", encoding="utf-8") as f:
                    self._routes = yaml.safe_load(f) or {}
                logger.info(f"加载路由配置: {routes_path}")
            else:
                logger.warning(f"路由配置文件不存在: {routes_path}")
                self._routes = {}
            
            self._last_load_time = time.time()
    
    def _start_watcher(self):
        """启动文件监控线程"""
        def watch():
            while not self._stop_watching.is_set():
                time.sleep(5)
                try:
                    settings_mtime = (CONFIG_DIR / "settings.yaml").stat().st_mtime
                    routes_mtime = (CONFIG_DIR / "routes.yaml").stat().st_mtime
                    
                    if settings_mtime > self._last_load_time or routes_mtime > self._last_load_time:
                        logger.info("检测到配置文件变更，正在热重载...")
                        self._load_all()
                except FileNotFoundError:
                    pass
                except Exception as e:
                    logger.warning(f"配置文件监控出错: {e}")
        
        self._watcher_thread = threading.Thread(target=watch, daemon=True)
        self._watcher_thread.start()
    
    def reload(self):
        """手动重载配置"""
        logger.info("手动重载配置...")
        self._load_all()
    
    # ============ 设置访问 ============
    
    def get(self, key: str, default: Any = None) -> Any:
        """通过点号路径获取设置值，如 'llm.model'"""
        with self._lock:
            keys = key.split(".")
            value = self._settings
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            return value
    
    def set(self, key: str, value: Any, persist: bool = True):
        """设置值并可选持久化到文件"""
        with self._lock:
            keys = key.split(".")
            target = self._settings
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            
            if persist:
                self._save_settings()
    
    def _save_settings(self):
        """保存设置到文件"""
        settings_path = CONFIG_DIR / "settings.yaml"
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.dump(self._settings, f, allow_unicode=True, sort_keys=False)
        self._last_load_time = time.time()
    
    @property
    def settings(self) -> dict:
        with self._lock:
            return dict(self._settings)
    
    @property
    def routes(self) -> dict:
        with self._lock:
            return dict(self._routes)
    
    def get_user_character(self, user_id: str) -> str:
        """获取用户当前角色"""
        overrides = self.get("character.user_overrides", {})
        return overrides.get(user_id, self.get("character.default", "xiaoban"))
    
    def set_user_character(self, user_id: str, char_id: str):
        """设置用户角色"""
        overrides = self.get("character.user_overrides", {})
        overrides[user_id] = char_id
        self.set("character.user_overrides", overrides)
    
    def stop(self):
        """停止监控"""
        self._stop_watching.set()


# 全局实例
_config_manager: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


if __name__ == "__main__":
    cfg = get_config()
    print("当前设置:")
    print(f"  默认角色: {cfg.get('character.default')}")
    print(f"  LLM 模型: {cfg.get('llm.model')}")
    print(f"  Qdrant 端口: {cfg.get('qdrant.port')}")
    print(f"  路由规则数: {len(cfg.routes.get('rules', []))}")
