# agent-loop-demo

Demo monorepo. Each directory is a standalone project with its own `pyproject.toml`, `Dockerfile`,
`Makefile` and tests, and is deployed as its own Railway service (root directory set per service).

| Directory | Project | Railway service |
|---|---|---|
| [`sandbox-agents/`](sandbox-agents/) | Cloud coding agent that runs as a workflow node (E2B sandbox + OpenRouter) | `api` → sandbox-cloud-agents.up.railway.app |
| [`outbound-ai/`](outbound-ai/) | Voice Flow Agent: Google Sheets → Twilio SMS → Retell AI outbound call → sheet update | `outbound-ai` → outbound-ai.up.railway.app |

All default runs, tests and CI use mock providers and never spend real credit.
