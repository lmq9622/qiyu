# models/（模型目录，随包发布，可独立更新）

放置本地大模型文件（GGUF / transformers 权重等），例如：
- 主大脑：qwen / llama / deepseek 系 GGUF（Main Brain）
- Realtime Brain（官方 MiniMind-O）：`models/realtime/minimind-3o/`（transformers 权重，
  含 model_omni.py / model_minimind.py / tokenizer / pytorch_model.bin）
- Realtime Brain（备选 GGUF）：`models/realtime/thinker.gguf`（MiniMind2，llama.cpp）

## MiniMind-O 官方权重（0.1B，CPU 可跑）

下载（ModelScope 优先，HF/hf-mirror 兜底，幂等）：
```
python tools/install_models.py --omni            # minimind-3o（0.1B，默认）
python tools/install_models.py --omni --moe     # minimind-3o-moe（312M-A115M）
```

权重约 216MB（`pytorch_model.bin`，bf16），不入 git（`--omni` 可重新拉取）。
应用启动时自动发现 `models/realtime/minimind-3o/`；缺失时 Realtime Brain 诚实降级
为 GGUF Thinker（llama.cpp）或 Main Brain，绝不假装实时大脑存在。

更新模型 = 替换本目录文件，无需重新下载/安装整个应用。
