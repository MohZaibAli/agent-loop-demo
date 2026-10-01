import os

# Tests never reach a real LLM or E2B unless explicitly marked.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SANDBOX_PROVIDER", "local")
os.environ.pop("OPENROUTER_API_KEY", None)
