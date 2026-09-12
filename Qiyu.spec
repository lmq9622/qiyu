# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/Codex projects/ai-companion-codex/ai-companion/client.py'],
    pathex=[],
    binaries=[('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/ggml-base.dll', 'llama_cpp/lib'), ('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/ggml-cpu.dll', 'llama_cpp/lib'), ('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/ggml-vulkan.dll', 'llama_cpp/lib'), ('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/ggml.dll', 'llama_cpp/lib'), ('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/llama.dll', 'llama_cpp/lib'), ('C:/Users/lmq20/AppData/Local/Programs/Python/Python313/Lib/site-packages/llama_cpp/lib/mtmd.dll', 'llama_cpp/lib')],
    datas=[('D:/Codex projects/ai-companion-codex/ai-companion/characters', 'characters'), ('D:/Codex projects/ai-companion-codex/ai-companion/config', 'config'), ('D:/Codex projects/ai-companion-codex/ai-companion/channels', 'channels'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/static', 'gateway/static'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/router.py', 'gateway'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/__init__.py', 'gateway'), ('D:/Codex projects/ai-companion-codex/ai-companion/ui2', 'ui2'), ('D:/Codex projects/ai-companion-codex/ai-companion/ui2_server.py', '.'), ('D:/Codex projects/ai-companion-codex/ai-companion/demo.py', '.')],
    hiddenimports=['fastapi', 'uvicorn', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.protocols.websockets.websockets_impl', 'pydantic', 'pydantic.deprecated.decorator', 'ui2_server', 'httpx', 'loguru', 'yaml', 'dotenv', 'characters', 'config', 'gateway.router', 'anyio._backends._asyncio', 'starlette.middleware.cors', 'starlette.staticfiles', 'channels', 'channels.base', 'channels.store', 'channels.registry', 'channels.clawbot', 'channels.wechaty_channel', 'channels.wechatauto_channel', 'channels.qqbot_channel', 'channels.feishu_channel', 'psutil', 'channels.placeholders', 'companion', 'companion.constants', 'companion.state', 'companion.models', 'companion.settings', 'companion.relations', 'companion.conv', 'companion.emotions', 'companion.behavior', 'companion.active', 'companion.llm', 'companion.topic', 'companion.scheduler', 'runtime', 'runtime.providers', 'runtime.hardware', 'runtime.manager', 'runtime.realtime', 'runtime.minimindo', 'runtime.minimindo.model_omni', 'runtime.minimindo.model_minimind', 'runtime.memory', 'runtime.toolagent', 'runtime.logging_setup', 'runtime.perf', 'runtime.concurrency', 'runtime.benchmark', 'runtime.vision', 'runtime.stt', 'runtime.tts', 'runtime.embedding_provider', 'runtime.avatar', 'runtime.platform', 'runtime.db', 'runtime.main_brain', 'runtime.ggml_probe', 'runtime.classifier', 'runtime.realtime_unified', 'runtime.brain', 'runtime.brain.router', 'runtime.brain.decision', 'runtime.brain.pipeline', 'runtime.brain.quality', 'runtime.gateway', 'runtime.voice_pipeline', 'companion.pipeline', 'accelerate', 'pythonnet', 'clr', 'tools', 'tools.web', 'tools.install_models', 'llama_cpp', 'llama_cpp.llama_cpp', 'llama_cpp.llama', 'llama_cpp._ctypes_extensions', 'llama_cpp.llama_chat_format', 'torch', 'transformers', 'transformers.modeling_outputs', 'transformers.generation', 'tokenizers', 'safetensors', 'huggingface_hub', 'filelock', 'regex', 'fsspec', 'qrcode', 'PIL', 'PIL.Image', 'wechatauto', 'wechatauto.wx', 'wechatauto.db', 'wechatauto.guia', 'wechatauto.media', 'wechatauto.sender', 'wechatauto.msgs', 'wechatauto.ui', 'wechatauto.uia', 'wechatauto.utils', 'uiautomation', 'comtypes', 'pyautogui', 'email_validator', 'zstandard', 'imageio_ffmpeg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torchvision', 'torchaudio', 'functorch', 'sentence_transformers', 'datasets', 'hf_xet', 'onnxruntime', 'IPython', 'traitlets', 'pyreadline3', 'prompt_toolkit', 'matplotlib', 'mpl_toolkits', 'pandas', 'scipy', 'sklearn', 'nltk', 'networkx', 'joblib', 'narwhals', 'ddtrace', 'sentry_sdk', 'opentelemetry', 'sqlalchemy', 'clickhouse_connect', 'openai', 'anthropic', 'tiktoken', 'grpc', 'grpc_tools', 'google.protobuf', 'google.auth', 'polars', 'duckdb', 'ibis', 'dask', 'modin', 'tensorflow'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Qiyu',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Qiyu',
)
