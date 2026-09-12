# 栖语 (Qiyu) · Linux 服务器分支 Docker 镜像
# 构建: docker build -t qiyu-server -f deploy/Dockerfile .
# 运行: docker run -d --name qiyu -p 8765:8765 -v qiyu-data:/data qiyu-server
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    QIYU_HOST=0.0.0.0 \
    QIYU_PORT=8765 \
    QIYU_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=4).status==200 else 1)"

CMD ["python", "server_entry.py"]
