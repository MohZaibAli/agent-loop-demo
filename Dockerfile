FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agent ./agent
COPY api ./api
COPY seed_repo ./seed_repo
COPY tests/fixtures ./tests/fixtures
COPY config.yaml ./

# Runtime configuration comes from the environment (see .env.example).
ENV LLM_PROVIDER=mock SANDBOX_PROVIDER=e2b MODEL_ROUTER=typesafe/jev-router SPEND_FILE=/data/spend.json MAX_CONCURRENT_RUNS=3 PORT=8000
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
