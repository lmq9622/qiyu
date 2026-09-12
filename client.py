"""
栖语 (Qiyu) - 桌面客户端 (.exe 入口)
======================================
双击运行，无需命令行，自带浏览器内核
======================================
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# 版本号单一来源（版本体系 v2，见 docs/VERSION_SCHEME.md）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from companion.version import APP_TITLE as _APP_TITLE, current_version as _app_version
except Exception:  # 冻结环境兜底，不让窗口起不来
    _APP_TITLE, _app_version = "Qiyu 栖语 · AI 伴侣", (lambda: "0.1.0")

# ============ PyInstaller 多进程兼容 ============
if getattr(sys, 'frozen', False):
    # 打包后的 exe 需要这个，否则子进程会递归启动自己
    import multiprocessing
    multiprocessing.freeze_support()


# ============ 资源路径处理（兼容 PyInstaller） ============
def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径，兼容 PyInstaller 打包"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


# ============ 日志（兼容 windowed 模式） ============
LOG_DIR = os.path.join(os.path.expanduser('~'), '.ai_companion')
LOG_PATH = os.path.join(LOG_DIR, 'client.log')
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg: str):
    """写入日志文件（windowed 模式下不能用 print/input）"""
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except Exception:
        pass


def set_runtime_sidecars():
    """M12：打包版把 llama.cpp CPU/Vulkan DLL 指向 exe 同目录 sidecar。

    - exe 同目录/backends/llama/lib 存在 → LLAMA_CPP_LIB_PATH 指向它（可独立更新）；
    - PyInstaller 已把 DLL 打进 _internal/llama_cpp/lib → llama_cpp 默认相对路径同样可用。
    只在 frozen 环境设置；开发环境不要覆盖本机 site-packages。
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        exe_dir = Path(sys.executable).resolve().parent
        sidecar = exe_dir / "backends" / "llama" / "lib"
        if sidecar.is_dir():
            os.environ["LLAMA_CPP_LIB_PATH"] = str(sidecar)
            log(f"llama.cpp 后端(sidecar): {sidecar}")
            return
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            alt = os.path.join(bundled, "llama_cpp", "lib")
            if os.path.isdir(alt):
                os.environ["LLAMA_CPP_LIB_PATH"] = alt
                log(f"llama.cpp 后端(内置): {alt}")
                return
        log("llama.cpp 后端目录缺失：官方 MiniMind-O 仍可走 CPU")
    except Exception as e:
        log(f"设置 llama.cpp 后端失败: {e}")


# ============ 后端进程管理 ============
backend_proc = None

def start_backend_process():
    """用子进程启动 FastAPI 后端（uvicorn 需要独立进程才能跑 asyncio）"""
    global backend_proc
    
    env = os.environ.copy()
    env['AI_COMPANION_BACKEND'] = '1'
    env['PYTHONPATH'] = get_resource_path('.')
    env['AI_COMPANION_LOG_DIR'] = LOG_DIR
    
    # 在打包后的 exe 中，sys.executable 就是这个 exe 本身
    # 通过环境变量让它进入后端模式而不是前端模式
    exe_path = sys.executable
    
    log(f"启动后端进程: {exe_path}")
    
    # Windows 下隐藏控制台窗口
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
    
    backend_proc = subprocess.Popen(
        [exe_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        startupinfo=startupinfo,
        cwd=get_resource_path('.'),
    )
    
    # 启动一个线程读取后端日志
    def read_backend_log():
        try:
            backend_log_path = os.path.join(LOG_DIR, 'backend.log')
            with open(backend_log_path, 'a', encoding='utf-8') as logf:
                for line in backend_proc.stdout:
                    decoded = line.decode('utf-8', errors='replace').rstrip()
                    logf.write(f'[{time.strftime("%H:%M:%S")}] {decoded}\n')
                    logf.flush()
        except Exception:
            pass
    
    import threading
    threading.Thread(target=read_backend_log, daemon=True).start()
    
    return backend_proc


def is_backend_ready() -> bool:
    """检查后端服务是否就绪"""
    try:
        import urllib.request
        port = int(os.getenv("QIYU_PORT", "8765"))
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
        return True
    except Exception:
        return False


def kill_backend():
    """结束后端进程"""
    global backend_proc
    if backend_proc and backend_proc.poll() is None:
        backend_proc.terminate()
        try:
            backend_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            backend_proc.kill()
        backend_proc = None


# ============ 后端模式入口 ============
def run_backend():
    """子进程入口：只跑 FastAPI 后端"""
    log("[后端模式] 启动 FastAPI 服务...")
    
    # 重新定向 stdout/stderr 到日志文件
    backend_log_path = os.path.join(LOG_DIR, 'backend.log')
    sys.stdout = open(backend_log_path, 'a', encoding='utf-8', buffering=1)
    sys.stderr = sys.stdout
    
    os.environ['AI_COMPANION_CLIENT_MODE'] = '1'
    sys.path.insert(0, get_resource_path('.'))
    
    import uvicorn
    from demo import app
    port = int(os.getenv("QIYU_PORT", "8765"))

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )


# ============ 前端模式入口 ============
def run_frontend():
    """主进程入口：启动后端 + 打开窗口"""
    log("=" * 50)
    log("栖语 桌面客户端启动")
    log("=" * 50)
    
    # 启动后端子进程
    start_backend_process()
    
    # 等待服务就绪
    log("等待后端服务就绪...")
    ready = False
    for i in range(240):  # M12：官方 MiniMind-O 包启动较慢，最多等 120 秒
        if is_backend_ready():
            ready = True
            log("✅ 后端服务已就绪")
            break
        time.sleep(0.5)
        if i > 0 and i % 40 == 0:
            log(f"等待后端服务就绪... {i * 0.5:.0f}s")
    
    if not ready:
        log("❌ 后端服务启动超时")
        kill_backend()
        show_error_and_exit("后端服务启动失败，请检查日志:\n" + LOG_DIR)
        return
    
    # 启动桌面窗口
    log("启动桌面窗口...")
    try:
        import webview

        # 微信式聊天窗口：双击即进入对话页，用户不需要在浏览器里输入本机端口。
        # QIYU_OPEN_BROWSER=1 仅供开发调试时强制走系统浏览器。
        if os.environ.get("QIYU_OPEN_BROWSER") == "1":
            raise ImportError("dev_browser_mode")

        app_url = (f"http://127.0.0.1:{int(os.getenv('QIYU_PORT', '8765'))}"
                   "/app2/#/chat")
        
        window = webview.create_window(
            title=_APP_TITLE,
            url=app_url,
            width=1180,
            height=780,
            min_size=(960, 660),
            text_select=True,
        )
        
        try:
            webview.start(
                debug=False,
                gui='edgechromium',
            )
        except Exception as _we:
            log(f"桌面窗口启动失败: {_we}")
            kill_backend()
            show_error_and_exit(
                f"桌面窗口启动失败：{_we}\n"
                "请不要用浏览器访问本机端口；请重试或检查 WebView2 运行库。")
            return
        
    except ImportError:
        # 不退回系统浏览器：那会让用户看到"本机端口 + 网页"，不是产品形态。
        if os.environ.get("QIYU_OPEN_BROWSER") == "1":
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{int(os.getenv('QIYU_PORT', '8765'))}/app2/#/chat")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        else:
            log("⚠️ pywebview 不可用，拒绝退回浏览器模式")
            kill_backend()
            show_error_and_exit(
                "桌面窗口组件 pywebview 不可用。\n"
                "请确认打包/运行环境已安装 pywebview，不要用浏览器访问端口。\n"
                "（开发调试可设置 QIYU_OPEN_BROWSER=1 临时打开浏览器）")
            return
    except Exception as e:
        log(f"桌面模式异常: {e}")
        kill_backend()
        show_error_and_exit(
            f"桌面模式异常：{e}\n"
            "请不要用浏览器访问本机端口；请查看日志确认问题。")
        return
    
    # 窗口关闭后结束后端
    log("窗口已关闭，结束后端进程...")
    kill_backend()
    log("已退出")


def show_error_and_exit(message: str):
    """显示错误弹窗并退出"""
    log(f"错误: {message}")
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "栖语 启动失败", 0x10)
        else:
            import tkinter.messagebox
            tkinter.messagebox.showerror("栖语 启动失败", message)
    except Exception:
        pass
    sys.exit(1)


# ============ 主入口 ============
if __name__ == "__main__":
    # 进入任何模式前先设置 sidecar 运行库（后端进程会继承）
    set_runtime_sidecars()
    # 检测当前是前端模式还是后端模式
    if os.environ.get('AI_COMPANION_BACKEND') == '1':
        run_backend()
    else:
        run_frontend()
