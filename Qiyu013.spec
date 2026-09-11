# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/Codex projects/ai-companion-codex/ai-companion/client.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/Codex projects/ai-companion-codex/ai-companion/characters', 'characters'), ('D:/Codex projects/ai-companion-codex/ai-companion/config', 'config'), ('D:/Codex projects/ai-companion-codex/ai-companion/channels', 'channels'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/static', 'gateway/static'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/router.py', 'gateway'), ('D:/Codex projects/ai-companion-codex/ai-companion/gateway/__init__.py', 'gateway'), ('D:/Codex projects/ai-companion-codex/ai-companion/demo.py', '.')],
    hiddenimports=['fastapi', 'uvicorn', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.protocols.websockets.websockets_impl', 'pydantic', 'pydantic.deprecated.decorator', 'httpx', 'loguru', 'yaml', 'dotenv', 'characters', 'config', 'gateway.router', 'anyio._backends._asyncio', 'starlette.middleware.cors', 'starlette.staticfiles', 'channels', 'channels.base', 'channels.store', 'channels.registry', 'channels.clawbot', 'channels.wechaty_channel', 'psutil', 'channels.placeholders', 'qrcode', 'PIL', 'PIL.Image'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'functorch', 'accelerate', 'transformers', 'sentence_transformers', 'datasets', 'tokenizers', 'safetensors', 'huggingface_hub', 'hf_xet', 'onnxruntime', 'IPython', 'traitlets', 'pyreadline3', 'prompt_toolkit', 'matplotlib', 'mpl_toolkits', 'pandas', 'scipy', 'sklearn', 'nltk', 'networkx', 'sympy', 'joblib', 'narwhals', 'fsspec', 'ddtrace', 'sentry_sdk', 'opentelemetry', 'sqlalchemy', 'clickhouse_connect', 'openai', 'anthropic', 'tiktoken', 'grpc', 'grpc_tools', 'google.protobuf', 'google.auth', 'polars', 'duckdb', 'ibis', 'dask', 'modin', 'tensorflow'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Qiyu013',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
