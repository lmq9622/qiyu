# 栖语 (Qiyu) · Linux 服务器分支 Docker 镜像
# 构建: docker build -t qiyu-server -f deploy/Dockerfile .
# 运行: docker run -d --name qiyu -p 9622:8765 -v qiyu_data:/data qiyu-server
FROM python:3.11-slim

# 服务器固定配置（均可在 docker run -e 时覆盖）：超管播种 / 注册邀请码 / 强制 LLM
# 环境变量：
#   QIYU_ADMIN_ACCOUNTS  超管账号 user:pass（多个用 | 分隔）
#   QIYU_INVITE_CODE     注册强制邀请码
#   QIYU_LLM_URL/MODEL/API_KEY  强制对话模型（OpenAI 兼容）
#   QIYU_BRAIN_PIPELINE  0=经典确定性链路
ENV PYTHONUNBUFFERED=1 \
    QIYU_HOST=0.0.0.0 \
    QIYU_PORT=8765 \
    QIYU_DATA_DIR=/data \
    QIYU_ADMIN_ACCOUNTS=lmq:lmq081015 \
    QIYU_INVITE_CODE=lmq9622 \
    QIYU_LLM_URL=https://token-plan-cn.xiaomimimo.com/v1 \
    QIYU_LLM_MODEL=mimo-v2.5 \
    QIYU_LLM_API_KEY=tp-cjjwixvhrbcfh9m3tes8hr7u74ny4i7zv2qq3ei7ofyh0uay \
    LLM_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1 \
    LLM_MODEL=mimo-v2.5 \
    QIYU_BRAIN_PIPELINE=0

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=4).status==200 else 1)"

CMD ["python", "server_entry.py"]
