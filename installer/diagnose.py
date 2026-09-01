"""
栖语 (Qiyu) - 诊断修复系统
自动检测问题、提供手动方案、支持一键修复
"""

import os
import sys
import socket
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class FixType(str, Enum):
    AUTO = "auto"       # 可自动修复
    MANUAL = "manual"   # 需要手动操作
    GUIDE = "guide"     # 仅指导


@dataclass
class DiagnoseIssue:
    id: str
    title: str
    description: str
    severity: IssueSeverity
    fix_type: FixType
    fix_command: Optional[str] = None
    fix_description: Optional[str] = None
    manual_steps: List[str] = field(default_factory=list)


class Diagnoser:
    """诊断器"""
    
    def __init__(self):
        self.issues: List[DiagnoseIssue] = []
        self.fixable_count = 0
    
    def check_all(self):
        """运行所有检查"""
        logger.info("=" * 60)
        logger.info("栖语 - 系统诊断")
        logger.info("=" * 60)
        
        self._check_python_version()
        self._check_dependencies()
        self._check_qdrant()
        self._check_letta()
        self._check_gateway_port()
        self._check_webui_port()
        self._check_llm_connection()
        self._check_env_file()
        self._check_data_directories()
        self._check_characters()
        
        self._print_summary()
    
    def _add_issue(self, issue: DiagnoseIssue):
        self.issues.append(issue)
        if issue.fix_type == FixType.AUTO:
            self.fixable_count += 1
    
    # ============ 各项检查 ============
    
    def _check_python_version(self):
        """检查 Python 版本"""
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            self._add_issue(DiagnoseIssue(
                id="python_version",
                title="Python 版本过低",
                description=f"当前 Python {version.major}.{version.minor}，需要 3.10+",
                severity=IssueSeverity.ERROR,
                fix_type=FixType.MANUAL,
                manual_steps=[
                    "1. 安装 Python 3.10 或更高版本: https://python.org",
                    "2. 重新创建虚拟环境: python3.10 -m venv venv",
                    "3. 激活虚拟环境并重新安装依赖",
                ]
            ))
        else:
            logger.success(f"Python 版本: {version.major}.{version.minor}.{version.micro} ✓")
    
    def _check_dependencies(self):
        """检查关键依赖"""
        required = {
            "fastapi": "FastAPI 框架",
            "httpx": "HTTP 客户端",
            "qdrant_client": "Qdrant 客户端",
            "letta": "Letta Agent 框架",
            "sentence_transformers": "Embedding 模型",
            "pydantic": "数据验证",
            "loguru": "日志系统",
        }
        
        missing = []
        for module, desc in required.items():
            try:
                __import__(module)
            except ImportError:
                missing.append((module, desc))
        
        if missing:
            modules_str = ", ".join([m[0] for m in missing])
            self._add_issue(DiagnoseIssue(
                id="missing_dependencies",
                title="缺少关键依赖",
                description=f"未安装的模块: {modules_str}",
                severity=IssueSeverity.ERROR,
                fix_type=FixType.AUTO,
                fix_command="pip install -r requirements.txt",
                fix_description="自动安装所有依赖",
            ))
        else:
            logger.success(f"所有关键依赖已安装 ✓")
    
    def _check_qdrant(self):
        """检查 Qdrant（可选，内置 RAG 不依赖）"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", 6333))
            sock.close()
            
            if result == 0:
                logger.success("Qdrant 正在运行 (端口 6333) ✓")
            else:
                logger.info("Qdrant 未运行（可选，内置 numpy RAG 不依赖 Qdrant）")
        except Exception:
            pass
    
    def _check_letta(self):
        """检查 Letta"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", 8283))
            sock.close()
            
            if result == 0:
                logger.success("Letta Server 正在运行 (端口 8283) ✓")
            else:
                self._add_issue(DiagnoseIssue(
                    id="letta_not_running",
                    title="Letta Server 未运行",
                    description="Letta Agent 服务没有启动",
                    severity=IssueSeverity.ERROR,
                    fix_type=FixType.AUTO,
                    fix_command="letta server",
                    fix_description="启动 Letta Server（需在另一个终端运行）",
                ))
        except Exception:
            pass
    
    def _check_gateway_port(self):
        """检查网关端口"""
        port = int(os.getenv("GATEWAY_PORT", "8000"))
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            
            if result == 0:
                logger.success(f"网关正在运行 (端口 {port}) ✓")
            else:
                self._add_issue(DiagnoseIssue(
                    id="gateway_not_running",
                    title="适配网关未运行",
                    description=f"FastAPI 网关没有启动（端口 {port}）",
                    severity=IssueSeverity.ERROR,
                    fix_type=FixType.AUTO,
                    fix_command="python gateway/main.py",
                    fix_description="启动适配网关",
                ))
        except Exception:
            pass
    
    def _check_webui_port(self):
        """检查 Open WebUI 端口"""
        port = int(os.getenv("OPEN_WEBUI_PORT", "8080"))
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            
            if result == 0:
                logger.success(f"Open WebUI 正在运行 (端口 {port}) ✓")
            else:
                self._add_issue(DiagnoseIssue(
                    id="webui_not_running",
                    title="Open WebUI 未运行",
                    description=f"Open WebUI 没有启动（端口 {port}）",
                    severity=IssueSeverity.WARNING,
                    fix_type=FixType.AUTO,
                    fix_command="open-webui serve",
                    fix_description="启动 Open WebUI（需先安装: pip install open-webui）",
                ))
        except Exception:
            pass
    
    def _check_llm_connection(self):
        """检查 LLM 连接"""
        llm_url = os.getenv("LLM_BASE_URL", "http://192.168.2.6:8081/v1")
        try:
            import httpx
            resp = httpx.get(f"{llm_url}/models", timeout=5)
            if resp.status_code == 200:
                logger.success(f"LLM 服务器连接正常 ✓ ({llm_url})")
            else:
                self._add_issue(DiagnoseIssue(
                    id="llm_connection_error",
                    title="LLM 服务器返回错误",
                    description=f"状态码: {resp.status_code}",
                    severity=IssueSeverity.WARNING,
                    fix_type=FixType.GUIDE,
                    manual_steps=[
                        f"1. 检查 LLM 服务是否正常运行: {llm_url}",
                        "2. 检查 .env 中的 LLM_BASE_URL 配置是否正确",
                        "3. 确认网络可以访问 192.168.2.6:8081",
                    ]
                ))
        except Exception as e:
            self._add_issue(DiagnoseIssue(
                id="llm_unreachable",
                title="无法连接 LLM 服务器",
                description=f"地址: {llm_url}，错误: {str(e)[:50]}",
                severity=IssueSeverity.ERROR,
                fix_type=FixType.MANUAL,
                manual_steps=[
                    "1. 确认 llama.cpp server 已在 192.168.2.6:8081 启动",
                    "2. 检查防火墙/网络是否允许访问",
                    "3. 编辑 .env 修改 LLM_BASE_URL 为正确地址",
                ]
            ))
    
    def _check_env_file(self):
        """检查 .env 文件"""
        env_path = PROJECT_DIR / ".env"
        if not env_path.exists():
            self._add_issue(DiagnoseIssue(
                id="env_missing",
                title="缺少 .env 配置文件",
                description="项目根目录下没有找到 .env 文件",
                severity=IssueSeverity.ERROR,
                fix_type=FixType.AUTO,
                fix_command="cp .env.example .env",
                fix_description="从模板创建 .env 文件",
            ))
        else:
            logger.success(".env 配置文件存在 ✓")
    
    def _check_data_directories(self):
        """检查数据目录"""
        required_dirs = ["data/qdrant", "data/sqlite", "data/uploads", "data/logs"]
        missing = []
        for d in required_dirs:
            if not (PROJECT_DIR / d).exists():
                missing.append(d)
        
        if missing:
            dirs_str = ", ".join(missing)
            self._add_issue(DiagnoseIssue(
                id="missing_data_dirs",
                title="缺少数据目录",
                description=f"未找到: {dirs_str}",
                severity=IssueSeverity.WARNING,
                fix_type=FixType.AUTO,
                fix_command="mkdir -p data/qdrant data/sqlite data/uploads data/logs",
                fix_description="自动创建数据目录",
            ))
        else:
            logger.success("数据目录检查通过 ✓")
    
    def _check_characters(self):
        """检查角色卡"""
        chars_dir = PROJECT_DIR / "characters"
        json_files = list(chars_dir.glob("*.json"))
        
        if len(json_files) == 0:
            self._add_issue(DiagnoseIssue(
                id="no_characters",
                title="没有角色卡",
                description="characters 目录下没有找到角色配置",
                severity=IssueSeverity.WARNING,
                fix_type=FixType.GUIDE,
                manual_steps=[
                    "1. 检查 characters/ 目录是否存在",
                    "2. 参考 .json 模板创建角色卡",
                ]
            ))
        else:
            logger.success(f"已加载 {len(json_files)} 个角色卡 ✓")
    
    def _print_summary(self):
        """打印诊断摘要"""
        logger.info("=" * 60)
        
        if not self.issues:
            logger.success("🎉 所有检查通过！系统状态良好。")
            return
        
        # 分类统计
        errors = [i for i in self.issues if i.severity in (IssueSeverity.ERROR, IssueSeverity.CRITICAL)]
        warnings = [i for i in self.issues if i.severity == IssueSeverity.WARNING]
        
        logger.warning(f"发现问题: {len(errors)} 个错误, {len(warnings)} 个警告")
        logger.info(f"其中 {self.fixable_count} 个问题可以自动修复")
        logger.info("=" * 60)
        
        # 显示问题列表
        for i, issue in enumerate(self.issues, 1):
            severity_emoji = {
                IssueSeverity.INFO: "ℹ️",
                IssueSeverity.WARNING: "⚠️",
                IssueSeverity.ERROR: "❌",
                IssueSeverity.CRITICAL: "🔴",
            }.get(issue.severity, "❓")
            
            fix_emoji = "🔧" if issue.fix_type == FixType.AUTO else "📝"
            
            print(f"\n{severity_emoji} [{i}] {issue.title} {fix_emoji}")
            print(f"   {issue.description}")
            
            if issue.fix_type == FixType.AUTO and issue.fix_command:
                print(f"   🔧 自动修复: {issue.fix_command}")
            elif issue.manual_steps:
                print(f"   📝 手动修复步骤:")
                for step in issue.manual_steps:
                    print(f"      {step}")
        
        logger.info("=" * 60)
        print(f"\n💡 运行以下命令一键修复所有可自动修复的问题:")
        print(f"   python installer/diagnose.py --fix\n")
    
    def fix_all(self):
        """一键修复所有可自动修复的问题"""
        logger.info("=" * 60)
        logger.info("开始自动修复...")
        logger.info("=" * 60)
        
        fixed = 0
        failed = 0
        
        for issue in self.issues:
            if issue.fix_type != FixType.AUTO or not issue.fix_command:
                continue
            
            print(f"\n🔧 修复: {issue.title}")
            print(f"   命令: {issue.fix_command}")
            
            try:
                result = subprocess.run(
                    issue.fix_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=PROJECT_DIR,
                )
                
                if result.returncode == 0:
                    logger.success(f"   ✅ 修复成功！")
                    fixed += 1
                else:
                    logger.error(f"   ❌ 修复失败: {result.stderr[:200]}")
                    failed += 1
            except Exception as e:
                logger.error(f"   ❌ 执行失败: {e}")
                failed += 1
        
        logger.info("=" * 60)
        logger.info(f"修复完成: {fixed} 成功, {failed} 失败")
        logger.info("=" * 60)
        
        if failed > 0:
            logger.info("建议重新运行诊断检查: python installer/diagnose.py")


def main():
    diagnoser = Diagnoser()
    diagnoser.check_all()
    
    # 如果带 --fix 参数，执行自动修复
    if "--fix" in sys.argv:
        diagnoser.fix_all()


if __name__ == "__main__":
    main()
