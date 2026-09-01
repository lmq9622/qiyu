# backends/（推理后端目录，可独立更新）

放置本地推理后端二进制（llama.cpp 等），例如：
- llama.cpp（CPU / Vulkan / CUDA 运行时）

升级 Vulkan/CUDA backend 时只需替换本目录，用户无需重新下载模型。
当前版本默认走远端 OpenAI-compatible API（见设置页 LLM 配置），本地后端按需放置。
