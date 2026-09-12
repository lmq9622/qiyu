#!/usr/bin/env python3
"""
栖语 (Qiyu) - PyInstaller 打包脚本
====================================
运行: python build.py
输出: dist/Qiyu/Qiyu.exe
====================================
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# ============ 配置 ============
PROJECT_ROOT = Path(__file__).parent
ENTRY_SCRIPT = PROJECT_ROOT / "client.py"
OUTPUT_NAME = os.environ.get("QIYU_OUTPUT_NAME", "Qiyu")
ICON_FILE = PROJECT_ROOT / "assets" / "icon.ico"  # 如果有图标的话
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / f"{OUTPUT_NAME}.spec"

# ============ 版本号（单一来源：companion/version.py） ============
# 版本体系 v2（2026-09-11 重编），详见 docs/VERSION_SCHEME.md：
#   - 默认打「产品主线包」：0.1.x，本机 Realtime Omni 架构；
#   - 设 QIYU_LEGACY_MINIMIND_O=1 时打「旧小脑专线包」：0.05.24（废案）。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from companion.version import APP_VERSION, MINIMIND_O_LEGACY_VERSION
except Exception:  # 兜底：打包环境异常时不让 build.py 直接挂掉
    APP_VERSION, MINIMIND_O_LEGACY_VERSION = "0.1.0", "0.05.24"

LEGACY_MINIMIND_O = os.environ.get("QIYU_LEGACY_MINIMIND_O") == "1"
VERSION = MINIMIND_O_LEGACY_VERSION if LEGACY_MINIMIND_O else APP_VERSION
# 小脑专线整包需要 dense（D6）+ MoE 全部入包；主线只随包 Omni/后端组件。
PACK_MOE_ONLY = not LEGACY_MINIMIND_O


def _llama_lib_dir():
    """本机 llama-cpp-python 的 DLL 目录（打包时拷入 sidecar backends/）。"""
    try:
        import llama_cpp
        d = Path(llama_cpp.__file__).resolve().parent / "lib"
        return d if d.is_dir() else None
    except Exception:
        return None

# ============ 检查环境 ============
def check_env():
    """检查打包环境"""
    print("=" * 60)
    print("栖语 - 打包检查")
    print("=" * 60)
    
    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[FAIL] PyInstaller 未安装")
        print("  请运行: pip install pyinstaller")
        return False
    
    # 检查 pywebview
    try:
        import webview
        ver = getattr(webview, '__version__', 'unknown')
        print(f"[OK] pywebview {ver}")
    except ImportError:
        print("[WARN] pywebview 未安装，桌面窗口将无法使用")
        print("  请运行: pip install pywebview")
    
    # 检查入口文件
    if not ENTRY_SCRIPT.exists():
        print(f"[FAIL] 入口文件不存在: {ENTRY_SCRIPT}")
        return False
    print(f"[OK] 入口文件: {ENTRY_SCRIPT}")
    
    # 检查关键资源
    resources = [
        "characters/__init__.py",
        "config/__init__.py",
        "config/settings.yaml",
        "config/routes.yaml",
        "memory/__init__.py",
        "rag/__init__.py",
        "wechat/__init__.py",
        "gateway/__init__.py",
        "gateway/router.py",
        "gateway/static/index.html",
        "demo.py",
    ]
    resources = [
        "characters/__init__.py",
        "config/__init__.py",
        "config/settings.yaml",
        "config/routes.yaml",
        "gateway/__init__.py",
        "gateway/router.py",
        "gateway/static/index.html",
        "demo.py",
    ]
    
    all_ok = True
    for res in resources:
        path = PROJECT_ROOT / res
        if path.exists():
            print(f"[OK] {res}")
        else:
            print(f"[MISS] {res}")
            all_ok = False
    
    print("=" * 60)
    return all_ok


# ============ 构建命令 ============
def build():
    """执行 PyInstaller 打包"""
    
    # 清理旧构建
    if BUILD_DIR.exists():
        print("清理旧构建目录...")
        shutil.rmtree(BUILD_DIR)
    
    if SPEC_FILE.exists():
        print("清理旧 spec 文件...")
        SPEC_FILE.unlink()
    
    # 收集 --add-data 参数 (Windows 用 ; 分隔)
    sep = ";" if sys.platform == "win32" else ":"
    add_data = []
    
    # 资源目录映射（ui2 = 新版整机前端；demo.py 通过相对路径挂载 /app2）
    resources = [
        ("characters", "characters"),
        ("config", "config"),
        ("channels", "channels"),
        ("gateway/static", "gateway/static"),
        ("gateway/router.py", "gateway"),
        ("gateway/__init__.py", "gateway"),
        ("ui2", "ui2"),
        ("ui2_server.py", "."),
        ("demo.py", "."),
    ]
    
    for src, dst in resources:
        src_path = PROJECT_ROOT / src
        if src_path.exists():
            add_data.append(f"--add-data")
            add_data.append(f"{src_path}{sep}{dst}")
    
    # Hidden imports (PyInstaller 可能分析不到的模块)
    hidden_imports = [
        "fastapi",
        "uvicorn",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.protocols.websockets.websockets_impl",
        "pydantic",
        "pydantic.deprecated.decorator",
        "ui2_server",
        "httpx",
        "loguru",
        "yaml",
        "dotenv",
        "characters",
        "config",
        "gateway.router",
        "anyio._backends._asyncio",
        "starlette.middleware.cors",
        "starlette.staticfiles",
        # 外部通讯通道层（channels）
        "channels",
        "channels.base",
        "channels.store",
        "channels.registry",
        "channels.clawbot",
        "channels.wechaty_channel",
        "channels.wechatauto_channel",
        "channels.qqbot_channel",
        "channels.feishu_channel",
        "psutil",
        "channels.placeholders",
        # M1/M3/M4：companion 包 + runtime Provider 层（函数级惰性 import 需要显式收集）
        "companion",
        "companion.constants",
        "companion.state",
        "companion.models",
        "companion.settings",
        "companion.relations",
        "companion.conv",
        "companion.emotions",
        "companion.behavior",
        "companion.active",
        "companion.llm",
        "companion.topic",
        "companion.scheduler",
        "runtime",
        "runtime.providers",
        "runtime.hardware",
        "runtime.manager",
        "runtime.realtime",
        "runtime.minimindo",
        "runtime.minimindo.model_omni",
        "runtime.minimindo.model_minimind",
        "runtime.memory",
        "runtime.toolagent",
        # M6：Realtime Brain 多组件 / 视觉 / 语音 / Avatar / 平台 / DB / 日志 / 性能 / 并发（函数级惰性 import）
        "runtime.logging_setup",
        "runtime.perf",
        "runtime.concurrency",
        "runtime.benchmark",
        "runtime.vision",
        "runtime.stt",
        "runtime.tts",
        "runtime.embedding_provider",
        "runtime.avatar",
        "runtime.platform",
        "runtime.db",
        "runtime.main_brain",
        "runtime.ggml_probe",
        "runtime.classifier",
        "runtime.realtime_unified",
        "runtime.brain",
        "runtime.brain.router",
        "runtime.brain.decision",
        "runtime.brain.pipeline",
        "runtime.brain.quality",
        "runtime.gateway",
        "runtime.voice_pipeline",
        "companion.pipeline",
        "accelerate",
        "pythonnet",
        "clr",
        # Tool Agent 联网工具箱（tools/ 目录被 .gitignore 忽略，必须显式收集）
        "tools",
        "tools.web",
        "tools.install_models",
        # M12：llama.cpp 真实推理（CPU/Vulkan，函数级惰性 import）
        "llama_cpp",
        "llama_cpp.llama_cpp",
        "llama_cpp.llama",
        "llama_cpp._ctypes_extensions",
        "llama_cpp.llama_chat_format",
        # M12：官方 MiniMind-O（runtime/minimindo 函数级惰性 import torch/transformers）
        "torch",
        "transformers",
        "transformers.modeling_outputs",
        "transformers.generation",
        "tokenizers",
        "safetensors",
        "huggingface_hub",
        "filelock",
        "regex",
        "fsspec",
        # ClawBot 二维码生成（demo.py 运行时惰性导入，PyInstaller 静态分析不到）
        "qrcode",
        "PIL",
        "PIL.Image",
        # wechatauto 本机接管（运行时惰性导入）
        "wechatauto",
        "wechatauto.wx",
        "wechatauto.db",
        "wechatauto.guia",
        "wechatauto.media",
        "wechatauto.sender",
        "wechatauto.msgs",
        "wechatauto.ui",
        "wechatauto.uia",
        "wechatauto.utils",
        "uiautomation",
        "comtypes",
        "pyautogui",
        "email_validator",
        "zstandard",
        "imageio_ffmpeg",
    ]

    # 排除运行时不需要的重型可选依赖。
    # M12 注意：torch/transformers/tokenizers/safetensors/huggingface_hub 是
    # MiniMind-O 官方权重必需的运行库，必须保留；这里只排除未用的重型加速/视觉/科学栈。
    excluded_modules = [
        "torchvision", "torchaudio", "functorch",
        "sentence_transformers", "datasets", "hf_xet", "onnxruntime",
        "IPython", "traitlets", "pyreadline3", "prompt_toolkit",
        "matplotlib", "mpl_toolkits", "pandas", "scipy", "sklearn",
        "nltk", "networkx", "joblib", "narwhals",
        "ddtrace", "sentry_sdk", "opentelemetry", "sqlalchemy",
        "clickhouse_connect", "openai", "anthropic", "tiktoken",
        "grpc", "grpc_tools", "google.protobuf", "google.auth",
        "polars", "duckdb", "ibis", "dask", "modin", "tensorflow",
    ]
    
    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", OUTPUT_NAME,
        # M12：onedir —— MiniMind-O 官方权重 + torch 等运行库不再塞进单个 exe
        # （规格§10：Qiyu.exe + runtime/ + backends/ + models/，启动更快、可独立更新）
        "--onedir",
        "--windowed",          # 不显示控制台窗口
        "--noconfirm",         # 不确认覆盖
        "--clean",             # 清理临时文件
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
    ]
    
    # 添加 hidden imports
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    # 添加排除模块
    for mod in excluded_modules:
        cmd.extend(["--exclude-module", mod])

    # M12：onedir 下关闭 UPX —— UPX 会压缩 torch 的 c10/torch_cpu 等 DLL，
    # PyInstaller onedir 运行时不解压 DLL，导致 [WinError 1114] DLL 初始化失败。
    
    # 添加资源
    cmd.extend(add_data)

    # llama.cpp DLL：放进 _internal/llama_cpp/lib（运行时加载路径与源码一致）。
    # 逐文件添加、只拷 *.dll（目录整体添加会把 .lib 也带进包）。
    llama_lib = _llama_lib_dir()
    if llama_lib is not None:
        sep = ";" if sys.platform == "win32" else ":"
        dlls = sorted(llama_lib.glob("*.dll"))
        for _dll in dlls:
            cmd.extend(["--add-binary", f"{_dll}{sep}llama_cpp/lib"])
        print(f"[OK] llama.cpp DLL 目录: {llama_lib}")
    else:
        print("[WARN] 未找到 llama_cpp/lib，包内 CPU/Vulkan 后端不可用（仍需 sidecar backends/）")
    
    # 图标
    if ICON_FILE.exists():
        cmd.extend(["--icon", str(ICON_FILE)])
    
    # 入口文件
    cmd.append(str(ENTRY_SCRIPT))
    
    print("\n" + "=" * 60)
    print("开始打包...")
    print("=" * 60)
    print("命令:")
    print(" \\\n".join(cmd))
    print("=" * 60 + "\n")
    
    # 执行
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    
    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("打包成功!")
        print("=" * 60)
        exe_path = DIST_DIR / OUTPUT_NAME / f"{OUTPUT_NAME}.exe"
        if exe_path.exists():
            print(f"输出文件: {exe_path}")
            print(f"文件大小: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        else:
            # onefile 模式
            exe_path = DIST_DIR / f"{OUTPUT_NAME}.exe"
            if exe_path.exists():
                print(f"输出文件: {exe_path}")
                print(f"文件大小: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        exe_base = DIST_DIR / OUTPUT_NAME
        # M12：把 runtime/minimindo 的源码 .py 放进 _internal/runtime/minimindo/
        # MiniMindOmni 继承的 transformers 基类在打包进程里需要 inspect 源码，
        # 只放 PYZ（.pyc）会导致 FileNotFoundError: model_omni.py。
        try:
            src_mm = PROJECT_ROOT / "runtime" / "minimindo"
            dst_mm = exe_base / "_internal" / "runtime" / "minimindo"
            if src_mm.is_dir():
                dst_mm.mkdir(parents=True, exist_ok=True)
                for fname in ("__init__.py", "model_omni.py", "model_minimind.py"):
                    f = src_mm / fname
                    if f.exists():
                        shutil.copy2(f, dst_mm / fname)
                print(f"[OK] MiniMind-O 运行库源码: {dst_mm}")
        except Exception as e:
            print(f"[WARN] 复制 MiniMind-O 源码失败: {e}")
        # 复制 Wechaty 网关目录（gateway.js / package.json / install.bat，不含 node_modules）
        try:
            src_gw = PROJECT_ROOT / "wechaty"
            dst_gw = exe_base / "wechaty"
            if src_gw.exists():
                dst_gw.mkdir(parents=True, exist_ok=True)
                for fname in ("gateway.js", "package.json", "install.bat"):
                    f = src_gw / fname
                    if f.exists():
                        shutil.copy2(f, dst_gw / fname)
                print(f"[OK] Wechaty 网关目录已复制到 {dst_gw}（运行 install.bat 安装依赖后即可用）")
        except Exception as e:
            print(f"[WARN] 复制 Wechaty 网关目录失败: {e}")
        # M5：可独立更新的 sidecar 目录（runtime/backends/models/assets/config/tools）
        try:
            create_sidecars()
        except Exception as e:
            print(f"[WARN] 创建 sidecar 目录失败: {e}")
        print("=" * 60)
        return True
    else:
        print(f"\n[ERROR] 打包失败，返回码: {result.returncode}")
        return False


# ============ 快速模式（用 spec 文件） ============
def build_fast():
    """使用已有 spec 文件快速构建（第二次以后）"""
    if not SPEC_FILE.exists():
        print("没有找到 .spec 文件，请先运行完整构建")
        return False
    
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm", "--clean"]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0


def create_sidecars():
    """M5（规格§10）：构建可独立更新的 sidecar 目录。
    Qiyu.exe + runtime/ + backends/ + models/ + assets/ + config/ + tools/ + wechaty/
    模型 / 后端 / 配置不物理塞进 EXE：更新 Vulkan backend 不用重新下载整个模型。"""
    base = DIST_DIR / OUTPUT_NAME
    base.mkdir(parents=True, exist_ok=True)
    # 版本标记
    try:
        (base / "VERSION.txt").write_text(f"{VERSION}\n", encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 写 VERSION.txt 失败: {e}")
    # 可独立更新的目录（附说明）
    sidecar_notes = {
        "runtime": "runtime 资源目录（可独立更新）。",
        "backends": "推理后端目录（llama.cpp 等，可独立更新）。",
        "models": "本地模型目录（GGUF 等，可独立更新）。",
        "assets": "资源目录（图标等，可独立更新）。",
        "tools": "辅助工具目录（可独立更新）。",
    }
    for name, note in sidecar_notes.items():
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        readme = d / "README.txt"
        readme.write_text(note + "\n", encoding="utf-8")
        print(f"[OK] sidecar: {d}")
    # 0.1.0 产品主线：Omni 专属 sidecar 目录（运行时 + 权重，都可独立更新）
    for sub in ("models/omni", "backends/omni"):
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "README.txt").write_text(
            "Realtime Omni 目录（0.1.x 产品主线，可独立更新）。\n"
            "把 llama.cpp-omni 运行时放 backends/omni/，"
            "把 MiniCPM-o 4.5 Q4_K_M 权重放 models/omni/。\n"
            "AMD 支持必须用 runtime/omni/verify_amd_backend.py --run 实测，不要凭推断。\n",
            encoding="utf-8")
        print(f"[OK] sidecar(Omni): {d}")
    # M6：把模型安装器与联网工具箱放进 sidecar tools/（可独立更新）
    try:
        tool_srcs = [PROJECT_ROOT / "tools" / "web.py", PROJECT_ROOT / "tools" / "install_models.py"]
        tools_dir = base / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for _f in tool_srcs:
            if _f.exists():
                shutil.copy2(_f, tools_dir / _f.name)
        print(f"[OK] sidecar tools: web.py / install_models.py 已复制")
    except Exception as e:
        print(f"[WARN] 复制 tools 工具失败: {e}")
    # M6/M12：models/ 说明 + 直接随包拷贝真实权重（Zero Setup：不要求用户先跑安装器）
    try:
        models_readme = base / "models" / "README.txt"
        models_readme.write_text(
            "本地模型目录（可独立更新）。\n"
            "Realtime Omni（产品主线，0.1.x）：\n"
            "  models/omni/ —— MiniCPM-o 4.5 Q4_K_M 等原生 omni 权重"
            "（本地推理；AMD 支持必须实测，勿凭推断）\n"
            "  运行时放在 backends/omni/（llama.cpp-omni），"
            "或用 QIYU_OMNI_SERVER / QIYU_OMNI_GGUF 指定\n"
            "ASR（语音识别）：models/asr/sherpa-onnx-paraformer-zh-small-2024-03-09/\n"
            "Main Brain：由用户配置 OpenAI 兼容 API / 本地 GGUF（models/main/），"
            "仅在 Omni 判定需要深度推理时调用。\n"
            "历史（0.05.x 小脑专线，已废案，不进主线包）：models/realtime/minimind-*\n",
            encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 写 models README 失败: {e}")
    # M12：官方 MiniMind-O 3o 权重直接入包（找到就拷，缺失不阻断）
    try:
        if PACK_MOE_ONLY:
            raise RuntimeError("PACK_MOE_ONLY：跳过官方 dense 权重")
        omni_src = PROJECT_ROOT / "models" / "realtime" / "minimind-3o"
        omni_dst = base / "models" / "realtime" / "minimind-3o"
        if omni_src.is_dir():
            omni_dst.mkdir(parents=True, exist_ok=True)
            for _f in omni_src.iterdir():
                if _f.is_file() and _f.name not in ("__pycache__",):
                    shutil.copy2(_f, omni_dst / _f.name)
            print(f"[OK] MiniMind-O 官方权重: {omni_dst}")
        else:
            print("[WARN] models/realtime/minimind-3o 不存在，跳过官方权重")
    except Exception as e:
        print(f"[WARN] 拷贝 MiniMind-O 官方权重失败: {e}")
    # v4/D6：完整合并 D6 权重（minimind-tag-D6）随包。
    # Parity 修复（2026-09-06）：不再随包 D5 base + D6 LoRA + 运行时 peft，
    # 而直接随包“由 D5 + final exp-tag-D6 在受控环境正确合并”的全量权重。
    # 理由：1) PyInstaller 冻结环境此前漏集 peft → official 后端整条加载失败，
    #        悄悄回退到未 SFT 的 GGUF；2) 旧 D6-local/x99 合并文件不是由 final
    #        adapter 正确合并，行为与评测链路不等价（草 → “草：草”）。
    # 现在运行时无需 peft：模型目录本身就是最终权重。
    try:
        if PACK_MOE_ONLY:
            raise RuntimeError("PACK_MOE_ONLY：跳过 D6 dense 权重")
        d6_src = PROJECT_ROOT / "models" / "realtime" / "minimind-tag-D6"
        d6_dst = base / "models" / "realtime" / "minimind-tag-D6"
        if d6_src.is_dir():
            d6_dst.mkdir(parents=True, exist_ok=True)
            for _f in d6_src.iterdir():
                if _f.is_file() and _f.name != "__pycache__":
                    shutil.copy2(_f, d6_dst / _f.name)
            print(f"[OK] MiniMind D6 合并权重（无运行时 peft 依赖）: {d6_dst}")
    except Exception as e:
        print(f"[WARN] 拷贝 D6 合并权重失败: {e}")
    # 2026-09-11：MiniMind-O MoE 首轮反应模型（默认 Realtime Brain）。
    # 只随包 MoE 版本，避免 dense/D6 抢占默认选择。
    try:
        moe_src = PROJECT_ROOT / "models" / "realtime" / "minimind-sft-qiyu-backchannel-moe"
        moe_dst = base / "models" / "realtime" / "minimind-sft-qiyu-backchannel-moe"
        if moe_src.is_dir():
            moe_dst.mkdir(parents=True, exist_ok=True)
            for _f in moe_src.iterdir():
                if _f.is_file() and _f.name != "__pycache__":
                    shutil.copy2(_f, moe_dst / _f.name)
            print(f"[OK] Qiyu MoE 首轮反应模型: {moe_dst}")
        else:
            print("[WARN] models/realtime/minimind-sft-qiyu-backchannel-moe 不存在，跳过 MoE 模型")
    except Exception as e:
        print(f"[WARN] 拷贝 Qiyu MoE 首轮反应模型失败: {e}")
    # M12：GGUF Thinker 备选（llama.cpp CPU/Vulkan）
    try:
        gguf_src = PROJECT_ROOT / "models" / "realtime" / "thinker.gguf"
        rt_dst = base / "models" / "realtime"
        rt_dst.mkdir(parents=True, exist_ok=True)
        if gguf_src.exists() and gguf_src.stat().st_size > 1024 * 1024:
            shutil.copy2(gguf_src, rt_dst / "thinker.gguf")
            print(f"[OK] GGUF Thinker: {rt_dst / 'thinker.gguf'}")
    except Exception as e:
        print(f"[WARN] 拷贝 GGUF Thinker 失败: {e}")
    # M12：ASR 模型（sherpa-onnx）直接入包
    try:
        asr_src = PROJECT_ROOT / "models" / "asr" / "sherpa-onnx-paraformer-zh-small-2024-03-09"
        asr_dst = base / "models" / "asr" / "sherpa-onnx-paraformer-zh-small-2024-03-09"
        if asr_src.is_dir():
            asr_dst.mkdir(parents=True, exist_ok=True)
            for _f in asr_src.rglob("*"):
                if _f.is_file():
                    rel = _f.relative_to(asr_src)
                    (asr_dst / rel.parent).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(_f, asr_dst / rel)
            print(f"[OK] ASR 模型: {asr_dst}")
    except Exception as e:
        print(f"[WARN] 拷贝 ASR 模型失败: {e}")
    # M12：llama.cpp CPU+Vulkan 动态库 sidecar（可独立更新；exe 优先读这里）
    try:
        llama_lib = _llama_lib_dir()
        if llama_lib is not None:
            lib_dst = base / "backends" / "llama" / "lib"
            lib_dst.mkdir(parents=True, exist_ok=True)
            for _f in llama_lib.glob("*.dll"):
                shutil.copy2(_f, lib_dst / _f.name)
            print(f"[OK] llama.cpp 后端: {lib_dst} (CPU + Vulkan)")
        (base / "backends" / "README.txt").write_text(
            "推理后端目录（可独立更新）。\n"
            "llama/lib/ —— llama.cpp CPU + Vulkan 动态库（ggml-vulkan.dll 等）\n",
            encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 拷贝 llama.cpp 后端失败: {e}")
    # 用户可编辑配置副本（exe 启动时优先读 exe 同目录 config/）
    cfg_dir = base / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("settings.yaml", "routes.yaml"):
        src = PROJECT_ROOT / "config" / fname
        if src.exists():
            dst = cfg_dir / fname
            if not dst.exists():
                shutil.copy2(src, dst)
            print(f"[OK] 配置副本: {dst}")
    if ICON_FILE.exists():
        try:
            shutil.copy2(ICON_FILE, base / "assets" / "icon.ico")
        except Exception as e:
            print(f"[WARN] 复制图标失败: {e}")
    print("[OK] sidecar 结构完成: runtime/ backends/ models/ assets/ config/ tools/")


# ============ 主入口 ============
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="栖语 打包工具")
    parser.add_argument("--fast", action="store_true", help="使用已有 spec 快速构建")
    parser.add_argument("--check-only", action="store_true", help="只检查环境不打包")
    args = parser.parse_args()
    
    if args.check_only:
        check_env()
        sys.exit(0)
    
    if not check_env():
        print("\n环境检查未通过，请修复上述问题后重试")
        sys.exit(1)
    
    if args.fast:
        success = build_fast()
    else:
        success = build()
    
    sys.exit(0 if success else 1)
