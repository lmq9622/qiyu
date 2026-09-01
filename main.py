"""
栖语 (Qiyu) - 全自动服务启动器
自动检测依赖、自动启动所有服务、健康监控
"""

import os
import sys
import time
import signal
import subprocess
import threading
import shutil
from pathlib import Path
from typing import Optional, Dict, List

from dotenv import load_dotenv
from loguru import logger

# 加载环境变量
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

# 服务定义
SERVICES = {
    "postgres": {
        "name": "PostgreSQL (Letta 数据库)",
        "check_cmd": None,
        "check_port": 5432,
        "start_cmd": None,  # 本机已有 PostgreSQL 则自动复用；否则请手动启动后配置 LETTA_PG_URI
        "enabled": True,
        "delay": 3,
        "critical": True,
    },
    "qdrant": {
        "name": "Qdrant 向量数据库 (可选)",
        "check_cmd": None,  # 通过端口检查
        "check_port": 6333,
        "start_cmd": None,  # 内置 RAG 使用 numpy 记忆实现，不依赖 Qdrant
        "enabled": False,   # 默认关闭；如需启用请手动启动本地 qdrant 二进制
        "delay": 3,
        "critical": False,
    },
    "letta": {
        "name": "Letta Agent Server",
        "check_cmd": [sys.executable, "-c", "import letta"],
        "check_port": 8283,
        "start_cmd": ["letta", "server", "--port", "8283", "--host", "127.0.0.1"],
        "enabled": True,
        "delay": 5,
        "critical": True,
    },
    "gateway": {
        "name": "适配网关 (FastAPI)",
        "check_cmd": None,
        "check_port": 8000,
        "start_cmd": [sys.executable, "gateway/main.py"],
        "enabled": True,
        "delay": 2,
        "critical": True,
    },
    "rag_watcher": {
        "name": "RAG 文件监控",
        "check_cmd": None,
        "start_cmd": [sys.executable, "rag/indexer.py", "watch"],
        "enabled": True,
        "delay": 1,
        "critical": False,
    },
    "wechat": {
        "name": "微信机器人",
        "check_cmd": None,
        "start_cmd": [sys.executable, "wechat/bot.py"],
        "enabled": os.getenv("WECHAT_ENABLED", "false").lower() == "true",
        "delay": 2,
        "critical": False,
    },
}


class ServiceLauncher:
    """服务启动器"""
    
    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self.project_dir = Path(__file__).parent
    
    def check_command(self, cmd: str) -> bool:
        """检查命令是否可用"""
        if not cmd:
            return False
        exe = shutil.which(cmd)
        return exe is not None
    
    def check_port(self, port: int, host: str = "127.0.0.1") -> bool:
        """检查端口是否被占用（服务是否已运行）"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0  # 端口被占用 = 服务在运行
        except Exception:
            return False
    
    def check_service_running(self, name: str, config: dict) -> bool:
        """检查服务是否已在运行"""
        # 优先检查端口
        if config.get("check_port"):
            if self.check_port(config["check_port"]):
                logger.info(f"{config['name']} 已在运行 (端口 {config['check_port']})")
                return True
        
        # 检查命令
        if config.get("check_cmd"):
            try:
                result = subprocess.run(
                    config["check_cmd"],
                    capture_output=True,
                    timeout=5,
                    cwd=self.project_dir,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                pass
        
        return False
    
    def start_service(self, name: str, config: dict) -> bool:
        """启动单个服务"""
        if not config.get("enabled", True):
            logger.info(f"跳过 {config['name']} (未启用)")
            return True
        
        # 检查是否已在运行
        if self.check_service_running(name, config):
            logger.success(f"{config['name']} 检测到已在运行")
            return True
        
        logger.info(f"启动 {config['name']}...")
        
        # 确定启动命令
        cmd = config.get("start_cmd")
        
        if not cmd:
            logger.warning(f"{config['name']} 未配置启动命令")
            return False
        
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self.project_dir,
            )
            
            self.processes[name] = proc
            
            # 启动日志线程
            log_thread = threading.Thread(
                target=self._log_output,
                args=(name, proc),
                daemon=True,
            )
            log_thread.start()
            self._threads.append(log_thread)
            
            logger.success(f"{config['name']} 已启动 (PID: {proc.pid})")
            return True
            
        except Exception as e:
            logger.error(f"启动 {config['name']} 失败: {e}")
            return False
    
    def _log_output(self, name: str, proc: subprocess.Popen):
        """捕获并输出服务日志"""
        if proc.stdout:
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break
                line = line.rstrip()
                if line:
                    logger.info(f"[{name}] {line}")
    
    def start_all(self):
        """启动所有服务"""
        logger.info("=" * 60)
        logger.info("栖语 - 全自动服务启动")
        logger.info("=" * 60)
        
        # 确保数据目录存在
        data_dir = self.project_dir / "data"
        for subdir in ["qdrant", "sqlite", "uploads", "logs", "postgres"]:
            (data_dir / subdir).mkdir(parents=True, exist_ok=True)
        
        # 按顺序启动服务
        for name, config in SERVICES.items():
            success = self.start_service(name, config)
            
            if not success and config.get("critical"):
                logger.error(f"关键服务 {config['name']} 启动失败！")
                logger.info("请检查上方日志，或运行: python installer/diagnose.py")
            
            if success and config.get("delay", 0) > 0:
                logger.info(f"等待 {config['delay']} 秒...")
                time.sleep(config["delay"])
        
        # 显示访问信息
        gateway_port = os.getenv("GATEWAY_PORT", "8000")
        webui_port = os.getenv("OPEN_WEBUI_PORT", "8080")
        
        logger.info("=" * 60)
        logger.info("服务启动完成！")
        logger.info("=" * 60)
        logger.info(f"角色选择页: http://localhost:{gateway_port}/")
        logger.info(f"Open WebUI:  http://localhost:{webui_port}")
        logger.info(f"适配网关:    http://localhost:{gateway_port}/v1")
        logger.info(f"Qdrant (可选): http://localhost:6333 (未启用时忽略)")
        logger.info("=" * 60)
        logger.info("诊断修复:  python installer/diagnose.py")
        logger.info("按 Ctrl+C 停止所有服务")
    
    def stop_all(self):
        """停止所有服务"""
        logger.info("正在停止所有服务...")
        self._stop_event.set()
        
        # 停止其他进程
        for name, proc in self.processes.items():
            logger.info(f"停止 {name} (PID: {proc.pid})...")
            try:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"强制终止 {name}")
                proc.kill()
            except Exception as e:
                logger.error(f"停止 {name} 时出错: {e}")
        
        logger.info("所有服务已停止")
    
    def run(self):
        """运行启动器"""
        self.start_all()
        
        try:
            while True:
                # 检查子进程状态
                for name, proc in list(self.processes.items()):
                    if proc.poll() is not None:
                        exit_code = proc.returncode
                        config = SERVICES.get(name, {})
                        if config.get("critical"):
                            logger.error(f"关键服务 {name} 已退出 (code: {exit_code})！")
                            logger.info("建议运行诊断: python installer/diagnose.py")
                        else:
                            logger.warning(f"{name} 已退出 (code: {exit_code})")
                
                time.sleep(3)
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            self.stop_all()


def main():
    launcher = ServiceLauncher()
    launcher.run()


if __name__ == "__main__":
    main()
