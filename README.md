# AgentOffice

Build your own AI consulting team. Recruit agents, give each one its own AI model, approve the
plan, watch the work happen in a pixel-art office, step in when the team needs you, and receive
reviewed, versioned, exportable deliverables.

AgentOffice is a **local-first** browser app. Projects, files and history stay on your machine.
When agents run, their prompts and the project context they need are sent to the AI provider whose
API key **you** configure (Anthropic and/or OpenAI). There is no telemetry.

## Requirements

- macOS or Linux, with **Docker Desktop** (runs PostgreSQL and the code sandbox)
- **Python 3.11+** and **Node.js 18+** (used once, to set up and build)
- An API key from the Anthropic Console and/or the OpenAI platform, to run real agents. A Claude Pro or
  ChatGPT subscription does not include API credits.

## Run it

```bash
./agentoffice start
```

The first start creates a Python environment, starts PostgreSQL in Docker (bound to `127.0.0.1:55432`),
builds the sandbox image and the interface, applies database migrations, and then opens
<http://127.0.0.1:8765>. Later starts take a few seconds.

```bash
./agentoffice stop          # stop the app (add --all to also stop PostgreSQL)
./agentoffice status        # is the server/worker running?
./agentoffice logs          # recent server and worker logs
./agentoffice test          # backend + frontend automated tests
```

Then, in the app:

1. **Settings**: paste an Anthropic or OpenAI API key. It is stored in your OS keychain and tested.
2. **Start new project**: pick a template (PRD, competitive analysis, software prototype, business
   process, or custom), describe the outcome, and optionally upload reference files.
3. **Recruit the team**: hire the recommended roles, choose a model for each, and adjust job
   descriptions, permissions and spending limits.
4. **Ask the PM for a plan**: review the statement of work, edit assignments, authorize tools,
   answer questions, then approve.
5. **Watch the office**, answer questions and approvals as they come in, and pause or cancel at any time.
6. **Review deliverables**: read versions and QA findings, accept or request a revision, and export.

## What runs where

| Component | Where | Notes |
|---|---|---|
| Web UI (React, Vite, Tailwind, Phaser) | your browser | talks only to the local API |
| API server (FastAPI) | host, `127.0.0.1:8765` | loopback only; host-header and CSRF checks |
| Execution worker (LangGraph) | host process | runs independently of the browser; resumes after restarts |
| PostgreSQL 16 | Docker, `127.0.0.1:55432` | the single source of truth |
| Code sandbox | throwaway Docker containers | no network, read-only root, non-root user, CPU/memory/time limits |
| API keys | OS keychain (encrypted-file fallback) | never stored in the database, logs or browser |

The API server and worker run on the host, not in Docker, so they can use the OS keychain and
start sandbox containers.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AGENTOFFICE_PORT` | `8765` | UI/API port (always bound to 127.0.0.1) |
| `AGENTOFFICE_DATABASE_URL` | local Docker Postgres | database connection |
| `AGENTOFFICE_DATA_DIR` | `./data` | uploads, exports, sandbox scratch |
| `AGENTOFFICE_CREDENTIAL_BACKEND` | `auto` | `keyring`, or `encrypted_file` |
| `AGENTOFFICE_CREDENTIAL_PASSPHRASE` | — | unlock secret for the encrypted-file fallback (supply it to both server and worker) |
| `AGENTOFFICE_ENABLE_TEST_PROVIDER` | off | enables the **scripted, non-AI** provider used by automated tests |

## Data, privacy and deletion

- Deleting a project removes its history, deliverables, uploads and exports from this machine.
- Removing an API key in Settings deletes it from the keychain.
- `docker compose down -v` removes the database volume entirely.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how it works
- [docs/OPEN_SOURCE_FOUNDATION_ASSESSMENT.md](docs/OPEN_SOURCE_FOUNDATION_ASSESSMENT.md): reuse decisions
- [docs/ENGINEERING_REPORT.md](docs/ENGINEERING_REPORT.md): what is verified, what is not, known defects
