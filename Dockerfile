# =============================================================================
# 入境定制游多 Agent 系统——Docker 镜像
# =============================================================================
# 构建：docker build -t travel-agent .
# 或直接：docker-compose up --build
# =============================================================================

FROM python:3.12-slim

WORKDIR /app

# 系统依赖（使用阿里云 Debian 镜像加速）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（分层缓存）
# 使用阿里云 PyPI 镜像加速（国内网络环境）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
