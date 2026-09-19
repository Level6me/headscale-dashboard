FROM python:3.12-slim

WORKDIR /app

# 安装基础运行依赖
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码与前端静态文件
COPY backend ./backend
COPY frontend/dist ./frontend/dist

WORKDIR /app/backend

ENV PORT=8086
ENV HEADSCALE_URL=http://127.0.0.1:8085

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://127.0.0.1:8086/api/v1/health || exit 1

CMD ["python", "main.py"]
