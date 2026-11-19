# AgentOffice — build progress (paused 2026-11-18)

Work in progress. This file records where the build stopped so it can resume cleanly.
The source spec is the AgentOffice PRD the user pasted into the build session.

## Environment
- Python venv: `.venv/` at repo root (Python 3.14). Install: `.venv/bin/pip install -r backend/requirements.txt`
- Postgres: `docker compose up -d postgres` (loopback 127.0.0.1:55432; DBs `agentoffice` and `agentoffice_test`)
- Sandbox image: `docker compose --profile build-only build sandbox-image` (built: `agentoffice-sandbox:1`)
- Migrations: `cd backend && ../.venv/bin/alembic upgrade head`
- Tests: `cd backend && ../.venv/bin/python -m pytest tests/ -q </dev/null`
- No provider API keys are configured. The real-provider journey test is NOT done yet.

## Done (backend)
- Data model, all 22 spec entities plus ReferenceFile and TeamPreset (`backend/app/models.py`), Alembic migration `0001`
- Validated state machines (`app/state_machine.py`)
- Event log with secret redaction (`app/events.py`); office status is derived only from events
- Providers: Anthropic + OpenAI adapters on the official SDKs, neutral conversation format, native replay of
  thinking blocks, refusal handling, optional server-side fallbacks with graceful degrade (`app/providers/`)
- Scripted test provider, gated by `AGENTOFFICE_ENABLE_TEST_PROVIDER=1` and flagged as test usage
- BYOK: macOS Keychain via keyring; scrypt+Fernet encrypted-file fallback (`app/security/credentials.py`)
- Tools with server-side permission checks, Docker sandbox (no network, read-only, non-root, limits),
  file ingestion (txt/md/pdf/docx/csv/json/code) (`app/tools/`)
- Orchestration: PM planner + SOW validation, task runner with suspend/resume (approvals, delegation, pause,
  budget), parallel pool, QA gate with bounded rework, consolidation, finalize, pause/cancel, restart recovery,
  LangGraph graph + Postgres checkpointer, durable worker with leases (`app/orchestration/`, `app/worker.py`)
- Budget enforcement before every call, including calls outside runs (`app/orchestration/budget.py`, `llm.py`)
- Client decisions for every approval kind, and PM chat intents (`app/orchestration/decisions.py`)
- FastAPI API with loopback host check and a CSRF client header (`app/main.py`, `app/api/routes.py`)
- Exports (md/json/csv/txt/docx/zip), validated before reporting success (`app/exports.py`)

## Test status at pause: 49 passed, 2 failed
- `tests/contract/test_provider_adapters.py::test_anthropic_request_and_parse`: KeyError `x-api-key` when
  reading request headers in the mock transport. Probably a header-casing/dict conversion issue in the test.
  Check `req.headers.get("x-api-key")`.
- `tests/unit/test_units.py::test_docx_and_pdf_extraction`: a blank PDF page yields "[page 1]" text, so the
  status is "ok", not "empty". Fix `files.extract` to judge emptiness on the page text only, without the markers.

## Remaining work
1. Fix the 2 failing tests above
2. Frontend: React + TS + Vite + Tailwind + Phaser virtual office (procedural original pixel art), pages:
   Dashboard, Office, Team, Projects, Deliverables, Activity, Costs, Settings; SSE stream hook; agent
   inspection panel; approvals UI; reduced motion and a non-animated timeline; the event→visual-state mapping
   as a pure, unit-tested function
3. Frontend tests (Vitest + RTL) and Playwright e2e (scripted provider, labelled mocked)
4. Startup script (`./agentoffice start|stop`): compose up, migrate, build frontend, run uvicorn on 127.0.0.1:8765
   plus `python -m app.worker`
5. Launch the app and run the journey in the browser
6. Real-provider journey: needs the user to add an API key in Settings. Never claim it passed without one
7. README, docs/ARCHITECTURE.md, final engineering report
8. Push to https://github.com/niloyfaiyaz/AgentOffice.git (the user asked for this once the build is done)
