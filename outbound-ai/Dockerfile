# Stage 1: resolve and install dependencies with uv into a self-contained venv.
FROM python:3.12-slim-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: runtime image with only the venv and application code.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY agent ./agent
COPY api ./api
COPY fixtures ./fixtures
COPY config.yaml ./

# Mock by default. Real SMS/calls need SERVICE_PROVIDER=retell plus a valid X-Demo-Key.
ENV SERVICE_PROVIDER=mock SHEETS_PROVIDER=fixture SPEND_FILE=/data/spend.json PORT=8000
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
