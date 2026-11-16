# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Capa de dependencias: solo se reconstruye si cambian pyproject.toml o uv.lock.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-editable --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "insumap.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
