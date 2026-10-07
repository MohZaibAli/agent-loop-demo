# Voice Flow Agent (outbound-ai)

Outbound voice calling and pre-call SMS workflow: Google Sheets → Twilio SMS → wait → Retell AI call →
sheet update. Standalone Python (FastAPI + static HTML/CSS/JS), no n8n. Live at
https://outbound-ai.up.railway.app

```
FETCH_SHEETS → FILTER_LEADS → SEND_SMS → WAIT → RETELL_CALL → UPDATE_SHEET
```

## Safety rules

- Everything defaults to `SERVICE_PROVIDER=mock`. Tests, CI, Docker and every UI action never send a real
  SMS or place a real call. Mock runs cost $0 and never touch the network.
- A real run needs `SERVICE_PROVIDER=retell` (or `twilio`) **and** header `X-Demo-Key: <DEMO_KEY>` **and**
  the Retell/Twilio credentials set. Anything else falls back to mock and the top bar shows `MOCK`.
- Spend is tracked in `SPEND_FILE` (`/data/spend.json` on Railway, `./data/spend.json` locally) with a
  global ceiling of $4.00 (`config.yaml`). Never committed.

## Architecture

| Component | Location |
|---|---|
| Workflow engine | `agent/workflow.py`: the six steps, per-lead loop, WAIT ticker, budget guard |
| Sheets | `agent/sheets.py`: `FixtureSheet` (in-memory, from `fixtures/leads.json`) and `GoogleSheet` (gspread) |
| Twilio | `agent/twilio_client.py`: `POST /2010-04-01/Accounts/{sid}/Messages.json`, mock twin |
| Retell | `agent/retell.py`: `POST https://api.retellai.com/v2/create-phone-call` with Bearer token, deterministic mock |
| Providers | `agent/providers.py`: mock vs live resolution from env + demo key |
| Events | `agent/events.py`: `{event_id, seq, timestamp, type, step, data}`, replayable, streamed over SSE |
| Budget | `agent/budget.py`: file-locked spend file, per-lead cost estimate |
| API + UI | `api/main.py`, `api/static/` |

## API

| Endpoint | Purpose |
|---|---|
| `POST /runs` (`?wait=true`, body `{lead_row?, max_leads?, wait_seconds?}`) | Run the pipeline over pending leads |
| `POST /runs/batch` (`{count: 3}`) | Three parallel single-lead runs with isolated event streams |
| `GET /runs/{id}/events` | SSE stream of the run's events |
| `GET /runs`, `GET /runs/{id}` | Run list and status |
| `GET /budget` | Spent, remaining and ceiling |
| `GET /leads?pending=true`, `POST /leads`, `POST /leads/reset` | Sheet rows, add a self-service lead, reload fixture |
| `GET /mode`, `GET /health`, `GET /config` | Mode resolution, health, SMS template |

`wait_seconds` in the body is honoured only in mock mode; real runs always use `WAIT_SECONDS` (600).

## UI

Editorial developer workbench: fixed top bar (mode, sheet, provider, budget, hidden key indicator), a
"Get a call on your phone" stepped form that adds you as a lead and runs the pipeline on that row, the
pipeline strip, a vertical execution trace with click-to-expand JSON payloads, three side-by-side lanes
for batch runs, and a sticky instrumentation panel. Press `r` `r` outside an input to reveal the
`X-Demo-Key` field.

## Run

```bash
uv sync --group dev
cp .env.example .env
make test          # unit + api + playwright e2e, all mock (screenshots in tests/e2e/screenshots/)
make run           # http://localhost:8000
```

## Sheet schema

`User Phone Number`, `First Name`, `Job Title`, `Current Job Description`, `New Job Opportunity`,
`Date & Time`, `Call Made`. Rows with `Call Made` empty or `false` are pending. After a call the agent
writes `Call Made = true` and `Date & Time = <UTC ISO timestamp>`.

`SHEETS_PROVIDER=google` uses gspread with `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON string or file path),
`GOOGLE_SHEET_ID` and `GOOGLE_WORKSHEET_NAME`. Share the sheet with the service account email.

## Deploy (Railway)

Service `outbound-ai`, root directory `/outbound-ai`, multi-stage Dockerfile, volume at `/data`,
healthcheck `/health`. Keep `SERVICE_PROVIDER=mock` until a real demo; then set the Retell, Twilio and
`DEMO_KEY` variables and switch `SERVICE_PROVIDER=retell`.
