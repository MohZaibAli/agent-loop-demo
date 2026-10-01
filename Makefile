.PHONY: install test test-unit test-api test-e2e test-e2b smoke run build-template docker

export LLM_PROVIDER ?= mock
export SANDBOX_PROVIDER ?= local
PW := PLAYWRIGHT_BROWSERS_PATH=$${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}

install:
	uv sync --group dev

# Unit + API + E2E. Mock provider, local sandbox: never calls a real LLM or E2B.
test: test-unit test-api test-e2e

test-unit:
	LLM_PROVIDER=mock SANDBOX_PROVIDER=local uv run pytest tests/unit -q

test-api:
	LLM_PROVIDER=mock SANDBOX_PROVIDER=local uv run pytest tests/integration/test_api.py -q

test-e2e:
	LLM_PROVIDER=mock SANDBOX_PROVIDER=local $(PW) uv run pytest tests/e2e -q

# Real E2B sandboxes, scripted provider only (no LLM calls). Needs E2B_API_KEY.
test-e2b:
	LLM_PROVIDER=mock SANDBOX_PROVIDER=e2b uv run pytest tests/integration/test_e2b.py -q -m e2b

build-template:
	uv run python scripts/build_e2b_template.py

run:
	uv run uvicorn api.main:app --host 0.0.0.0 --port $${PORT:-8000} --reload

# One real run with the cheap configured model. Spends real credit. Requires typing "run real".
smoke:
	@printf 'This will call OpenRouter with real credit. Type "run real" to continue: '; \
	read confirm; test "$$confirm" = "run real" || { echo "aborted"; exit 1; }
	LLM_PROVIDER=openrouter SANDBOX_PROVIDER=$${SANDBOX_PROVIDER:-e2b} uv run python scripts/parallel_demo.py --count 1 --real

docker:
	docker build -t agent-loop-demo .
