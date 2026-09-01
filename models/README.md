# models/（模型目录，随包发布，可独立更新）

放置本地大模型文件（GGUF 等），例如：
- 主大脑：qwen / llama / deepseek 系 GGUF（Main Brain）
- 未来 Realtime Brain：MiniMind-O 系列权重

应用启动时按 Hardware Detection 结果从这里选择模型与 backend。
更新模型 = 替换本目录文件，无需重新下载/安装整个应用。
