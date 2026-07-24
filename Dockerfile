FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 mozhou \
    && useradd --uid 10001 --gid 10001 --create-home mozhou \
    && mkdir -p /app/data /app/frontend \
    && chown -R 10001:10001 /app

COPY --chown=10001:10001 backend/ ./backend/
COPY --chown=10001:10001 publish_gzh.py md_to_html.py main.py ./
COPY --from=frontend-builder --chown=10001:10001 \
    /build/frontend/dist/ ./frontend/dist/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

USER 10001:10001

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]

# 单 worker：自动同步/发布调度器不能在多个进程中重复运行。
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
