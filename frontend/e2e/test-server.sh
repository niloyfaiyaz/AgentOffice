#!/usr/bin/env bash
# Starts an isolated AgentOffice (API + worker) for Playwright on port 8799, using the
# TEST database and the scripted (non-AI) test provider. Never touches real projects.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PW="$(grep '^AGENTOFFICE_DB_PASSWORD=' "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true)"
export AGENTOFFICE_DATABASE_URL="postgresql+psycopg://agentoffice:${PW:-agentoffice-local}@127.0.0.1:55432/agentoffice_test"
export AGENTOFFICE_API_TOKEN="e2e-test-token"
export AGENTOFFICE_ENABLE_TEST_PROVIDER=1
export AGENTOFFICE_DATA_DIR="$ROOT/data/e2e"
export AGENTOFFICE_PORT=8799
cd "$ROOT/backend"
"$ROOT/.venv/bin/alembic" upgrade head >/dev/null
"$ROOT/.venv/bin/python" -c "
from sqlalchemy import text
from app.db import engine
from app.models import Base
with engine.begin() as c:
    c.execute(text('TRUNCATE ' + ', '.join(t.name for t in Base.metadata.sorted_tables) + ' RESTART IDENTITY CASCADE'))
"
"$ROOT/.venv/bin/python" -m app.worker >"$ROOT/data/e2e-worker.log" 2>&1 &
WORKER=$!
trap 'kill $WORKER 2>/dev/null || true' EXIT
"$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8799
