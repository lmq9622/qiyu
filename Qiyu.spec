# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/Codex projects/ai-companion-codex/publish/_hardened/client.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/Codex projects/ai-companion-codex/publish/_hardened/characters', 'characters'), ('D:/Codex projects/ai-companion-codex/publish/_hardened/config', 'config'), ('D:/Codex projects/ai-companion-codex/publish/_hardened/gateway/static', 'gateway/static'), ('D:/Codex projects/ai-companion-codex/publish/_hardened/_shield', '_shield')],
    hiddenimports=['fastapi', 'uvicorn', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.protocols.websockets.websockets_impl', 'pydantic', 'pydantic.deprecated.decorator', 'httpx', 'loguru', 'yaml', 'dotenv', 'anyio._backends._asyncio', 'starlette.middleware.cors', 'starlette.staticfiles', 'psutil', 'qrcode', 'PIL', 'PIL.Image', 'wechatauto', 'wechatauto.wx', 'wechatauto.db', 'wechatauto.guia', 'wechatauto.media', 'wechatauto.sender', 'wechatauto.msgs', 'wechatauto.ui', 'wechatauto.uia', 'wechatauto.utils', 'uiautomation', 'comtypes', 'pyautogui', 'zstandard', 'imageio_ffmpeg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'functorch', 'accelerate', 'transformers', 'sentence_transformers', 'datasets', 'tokenizers', 'safetensors', 'huggingface_hub', 'hf_xet', 'onnxruntime', 'IPython', 'traitlets', 'pyreadline3', 'prompt_toolkit', 'matplotlib', 'mpl_toolkits', 'pandas', 'scipy', 'sklearn', 'nltk', 'networkx', 'sympy', 'joblib', 'narwhals', 'fsspec', 'ddtrace', 'sentry_sdk', 'opentelemetry', 'sqlalchemy', 'clickhouse_connect', 'openai', 'anthropic', 'tiktoken', 'grpc', 'grpc_tools', 'google.protobuf', 'google.auth', 'polars', 'duckdb', 'ibis', 'dask', 'modin', 'tensorflow', 'pyarmor', 'pyarmor.cli'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('O', None, 'OPTION'), ('O', None, 'OPTION')],
    name='Qiyu',
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
