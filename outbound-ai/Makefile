.PHONY: install test test-unit test-api test-e2e run docker

export SERVICE_PROVIDER ?= mock
export SHEETS_PROVIDER ?= fixture
PW := $(if $(wildcard /opt/pw-browsers),PLAYWRIGHT_BROWSERS_PATH=$${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers},)

install:
	uv sync --group dev

# Everything runs against mock providers. Never sends a real SMS or places a real call.
test: test-unit test-api test-e2e

test-unit:
	uv run pytest tests/unit -q

test-api:
	uv run pytest tests/integration -q

test-e2e:
	$(PW) uv run pytest tests/e2e -q

run:
	uv run uvicorn api.main:app --host 0.0.0.0 --port $${PORT:-8000} --reload

docker:
	docker build -t outbound-ai .
