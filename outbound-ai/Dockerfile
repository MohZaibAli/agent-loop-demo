FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agent ./agent
COPY api ./api
COPY fixtures ./fixtures
COPY config.yaml ./

ENV SERVICE_PROVIDER=mock SHEETS_PROVIDER=fixture SPEND_FILE=/data/spend.json PORT=8000
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
