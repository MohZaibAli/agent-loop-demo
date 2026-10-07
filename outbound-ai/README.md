# Voice Flow Agent (outbound-ai)

Outbound voice calling and pre-call SMS workflow: Google Sheets → Twilio SMS → wait → Retell AI call →
sheet update. Standalone Python (FastAPI + static HTML/CSS/JS), no n8n.

```
FETCH_SHEETS → FILTER_LEADS → SEND_SMS → WAIT → RETELL_CALL → UPDATE_SHEET
```

## Safety rules

- Everything defaults to `SERVICE_PROVIDER=mock`. Tests, CI, Docker and the UI never send a real SMS or
  place a real call.
- A real run needs `SERVICE_PROVIDER=retell` **and** header `X-Demo-Key: <DEMO_KEY>`. Anything else falls
  back to mock and the UI shows `MOCK`.
- Spend is tracked in `SPEND_FILE` (`/data/spend.json` on Railway, `./data/spend.json` locally); never
  committed.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Sheets schema, fixture sheet, Google Sheets client, filter, write-back, tests | done |
| 2 | Twilio + Retell httpx clients with mock fallback | next |
| 3 | Workflow engine, SSE events, budget guard | |
| 4 | `POST /runs`, `GET /runs/{id}/events`, `GET /budget` | |
| 5 | Editorial execution-trace UI | |
| 6 | Playwright E2E, deployment polish | |

## Run

```bash
uv sync --group dev
cp .env.example .env
make test          # 29 tests, all mock
make run           # http://localhost:8000
```

Endpoints today: `GET /health`, `GET /mode`, `GET /leads?pending=true`, `GET /config`, `/` (UI).

## Sheet schema

`User Phone Number`, `First Name`, `Job Title`, `Current Job Description`, `New Job Opportunity`,
`Date & Time`, `Call Made`. Rows with `Call Made` empty or `false` are pending. After a call the agent
writes `Call Made = true` and `Date & Time = <UTC ISO timestamp>`.

`SHEETS_PROVIDER=fixture` (default) uses `fixtures/leads.json` in memory. `SHEETS_PROVIDER=google` uses
gspread with `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON string or file path), `GOOGLE_SHEET_ID` and
`GOOGLE_WORKSHEET_NAME`. Share the sheet with the service account email.

## Deploy (Railway)

Service root directory `/outbound-ai`, Dockerfile build, volume mounted at `/data`. Set the variables
from `.env.example`; keep `SERVICE_PROVIDER=mock` until a real demo.
