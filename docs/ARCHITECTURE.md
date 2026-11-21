# AgentOffice architecture

## Overview

```
Browser ── React pages ── officeModel (pure reduce/step) ── Phaser renderer
   │  GET /state (snapshot) + SSE /stream?after=seq; mutations carry X-AgentOffice-Client
   ▼
FastAPI (127.0.0.1) ── routes ── decisions (client interventions) ──┐
   │                                                                 │
   ▼                                                                 ▼
PostgreSQL: projects · runs · tasks · executions · approvals · artifacts · usage · agent_events
   ▲
   │ lease (SELECT … FOR UPDATE SKIP LOCKED), heartbeat
worker ── LangGraph run graph ── planner / runner / review gate ── tools ── Docker sandbox
                 │                          │
                 └─ AsyncPostgresSaver      └─ providers: Anthropic SDK · OpenAI SDK
```

There is **one authoritative state** (Postgres), **one orchestration engine** (the LangGraph run graph
plus the task table) and **one event system** (`agent_events`, streamed over SSE).

## Backend modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `models.py` | SQLAlchemy model: the 22 spec entities plus `ReferenceFile` and `TeamPreset` |
| `migrations/` | Alembic migrations (the schema is never created ad hoc) |
| `state_machine.py` | allowed project/run/task transitions; every status change goes through it |
| `events.py` | append-only activity log with secret redaction; the only writer of agent visual status |
| `providers/` | neutral conversation format; Anthropic and OpenAI adapters; scripted test provider |
| `security/credentials.py` | OS keychain / encrypted-file key storage |
| `orchestration/planner.py` | PM statement of work (validated with Pydantic), plan → tasks |
| `orchestration/runner.py` | one task's agent loop, suspend/resume, retries |
| `orchestration/flow.py` | parallel pool, conditional QA gate, bounded rework, finalize, pause/cancel, recovery |
| `orchestration/graph.py` | LangGraph `StateGraph` wiring of the above |
| `orchestration/llm.py` | the single model-call gateway: budget check → reserve → call → usage record |
| `orchestration/budget.py` | application-enforced spending controls |
| `orchestration/decisions.py` | approvals and client interventions |
| `orchestration/context.py` | task-scoped context: requirements, decisions, dependency outputs, agent memory |
| `requirements.py` | requirement items: brief splitting, stable refs (R-001…), supersession, impact proposal |
| `traceability.py` | task↔requirement links, artifact-version lineage, deterministic freshness, impact analysis, delivery gate |
| `tools/` | permission-checked tools, Docker sandbox, file ingestion |
| `worker.py` | durable worker: leases, heartbeats, restart recovery |
| `api/routes.py` | HTTP API |

### Run lifecycle

```
planning ─► awaiting_approval ─► running ─► completed
   ▲  │            │ revise         │  ▲ └─► blocked (waiting for client) ─► running
   │  └ blocked     └─► planning     │  └── pausing ─► paused ─► running
   └─ (budget)                       └─► cancelled / failed
```

1. **Plan.** The PM calls `submit_work_plan`. The plan is validated (unique keys, real assignees, no
   cycles, authorized tools). The SOW is saved as a versioned artifact and an approval is created.
2. **Approve.** The client may edit assignees and titles, remove tasks, choose tool authorizations,
   toggle QA and answer questions. The edited plan is validated again and then becomes tasks plus
   dependencies.
3. **Execute.** A concurrency-limited pool runs ready tasks. Each task runs in the runner loop:
   - Budget check happens before every call.
   - Tool calls are checked against agent permissions, the task's allowed tools and the run's
     approved tools.
   - The conversation is persisted after every step.
   - Suspensions (client question, tool authorization, delegation, budget, pause) store the pending
     tool call. Resumption pairs it with its result, so no tool call is ever orphaned.
   - Model changes take effect at that checkpoint.
4. **Review gate.** QA runs only if the plan asked for it and a QA Reviewer is hired. Open
   critical/major findings create targeted rework tasks for each deliverable's owner, followed by a
   re-review, up to `max_review_iterations`. Then the PM consolidates. A single-task run without QA
   gets a deterministic summary and no extra model call.
5. **Finalize.** The run completes and a deliverable-acceptance approval states: agent work completed,
   whether QA ran, unresolved findings, and that QA approval is not proof of correctness.

### Requirements and change requests

The brief is split into individual **requirement items** with stable references (R-001…): numbered or
bulleted lines and normative sentences become `requirement` items, and the rest becomes background
context. Every new item gets the next reference automatically (`before_flush` hook).

A client **change request**:
1. Is stored as its own item.
2. The PM proposes which active items it replaces (model call, budget-checked, with a keyword fallback).
3. The client confirms the proposal on the approval card.
4. Replaced items are marked `superseded` and linked through `superseded_by_id` (history kept).

Agents never see the raw brief. They get active items, plus an explicit "NO LONGER VALID" list naming
what replaced each retired item. Editing the brief never resurrects a retired rule. The same card selects
completed and in-flight tasks for targeted rework.

### Traceability and stale-artifact protection

- **Plan tasks cite the R-ids they implement** (validated). Every artifact version snapshots the
  requirements it implements and the exact input versions it derives from.
- **Impact of a change:** when a requirement is superseded, impact is computed from those links plus task
  dependencies and recorded consumption. It is never a blanket list.
- **Freshness is deterministic.** A version is stale if it implements a superseded requirement, derives
  from a stale input, or has no links and predates the change; a client may confirm a version as current.
- **Delivery gate:** a stage-aware gate blocks QA, consolidation and finalization while any deliverable is
  stale. See [CHANGE_MANAGEMENT_VALIDATION.md](CHANGE_MANAGEMENT_VALIDATION.md).

### Safeguards

- Max delegation depth, max model calls per run and per task, max review iterations, concurrency limit,
  task timeout, bounded retries (only for transient errors), duplicate-task prevention via per-run
  idempotency keys, and a scope limit on delegated tasks (planned × 1.5 + 4).
- A failed task never restarts the project. The client can retry, skip or cancel.
- Restart recovery: a worker that takes a run's lease resumes interrupted tasks from their
  persisted conversations. Tools are idempotent: artifacts dedupe by content hash, delegations by key.

### Security boundaries

- The browser never sees API keys; keys live in the OS keychain.
- The server binds to 127.0.0.1 only. Host-header allowlisting blocks DNS rebinding. Mutating
  requests need a custom header, which blocks cross-site form posts.
- Uploads are type- and size-checked, stored under random names, and shown to agents only inside an
  `<untrusted_document>` envelope (name sanitized, closing tags neutralized).
- Tool permissions are enforced server-side. Unknown or unauthorized tool calls fail safely and are
  logged.
- Code runs only in Docker with no network, a read-only root, a non-root user, dropped capabilities,
  no-new-privileges, CPU/memory/pid limits and a timeout, with no host environment passed in. If
  Docker is unavailable, execution tools report that they are disabled. There is no host fallback.
- An agent cannot overwrite a teammate's deliverable unless its task targets that deliverable.

## Frontend (`frontend/src`)

- `office/model.ts`: pure `reduce(state, snapshot|event)` and `step(state, dt)`. A character's zone and
  animation come only from recorded agent status (`visualFor`). Walking interpolates between recorded
  states. Snapshots reconcile on load and reconnect, and replayed events are de-duplicated by sequence.
- `office/OfficeScene.ts`: Phaser renderer with original procedural pixel art (`office/sprites.ts`).
- `hooks.ts`: `useProjectStream` fetches a snapshot, then subscribes to SSE from its sequence number.
- Every animated fact also appears in conventional UI: the team list, the live timeline, the
  Activity page and the task board. Reduced motion teleports characters and disables effects.

## Testing

| Suite | Location | What it covers |
|---|---|---|
| Unit | `backend/tests/unit` | state machines, redaction, pricing, file validation, credentials, schemas |
| Provider contract (mock HTTP) | `backend/tests/contract` | exact requests/parsing through the official SDKs |
| Integration (real Postgres, scripted/fake provider) | `backend/tests/integration` | full journey, delegation, parallelism, approvals, pause/resume, cancel, budgets, sandbox, recovery, QA bounds, API, migrations |
| Real provider | `backend/tests/real` | skipped unless an API key is configured; real results only |
| Frontend unit | `frontend/src/**/*.test.ts(x)` | event→animation mapping, approval UI |
| E2E (Playwright, scripted provider) | `frontend/e2e` | the full UI journey against an isolated server and test DB |

Mocked or scripted results are labelled as such in test names and docstrings.
