# ============================================================
# Production Dockerfile — multi-stage (tiêu chí 1)
#   Stage builder: cài dependencies vào virtualenv /opt/venv
#   Stage runtime: python:3.11-slim + venv + source, user non-root
# Build:  docker build -t agent-prod .
# Run:    docker run -p 8000:8000 -e AGENT_API_KEY=... agent-prod
# ============================================================

# ── STAGE 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Copy requirements trước để tận dụng layer cache
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── STAGE 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    ENVIRONMENT=production

RUN groupadd --system appuser && useradd --system --gid appuser --no-create-home appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health', timeout=3)" || exit 1

# `exec` → uvicorn thay thế shell, trở thành PID 1 và nhận SIGTERM trực tiếp khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
