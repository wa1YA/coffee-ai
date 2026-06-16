# ============================================
# 咖啡大师 AI - Docker 镜像
# ============================================

FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt cryptography

# 复制应用代码
COPY . .

# 创建非 root 用户运行
RUN useradd --create-home --shell /bin/bash appuser
RUN chown -R appuser:appuser /app
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# 暴露端口
EXPOSE 5000

# 生产启动（2 worker）
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "--access-logfile", "-"]
