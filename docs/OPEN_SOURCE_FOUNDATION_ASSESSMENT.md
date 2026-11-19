# AgentOffice: Open-Source Foundation Assessment

Date: 2026-11-18 · Assessor: Claude Code (build session) · Status: decisions applied (see §9)

## 1. Method

Each candidate was shallow-cloned into an isolated scratch directory with git hooks disabled
(`git -c core.hooksPath=/dev/null clone --depth 1`). **No candidate code, install script, or
package manager was executed**, and no AgentOffice credentials or files were exposed. Findings
come from reading source files, licenses, notices and dependency manifests as text, plus the
public GitHub REST API for maintenance signals. Star counts are recorded but were not used as a
quality signal.

Rollback point before any integration: git tag `checkpoint/pre-oss-assessment` (commit `6d457ed`).

## 2. Current implementation inventory (before this assessment)

| Area | State | Evidence |
|---|---|---|
| Data model (22 spec entities + ReferenceFile, TeamPreset), Alembic migration | Working | `backend/app/models.py`, `migrations/versions/0001_initial_schema.py`; round-trip test |
| Validated state machines (project / run / task / agent visual) | Working | `app/state_machine.py`, unit tests |
| Event log + secret redaction (sole source of office state) | Working | `app/events.py` |
| Anthropic + OpenAI adapters (official SDKs), neutral conversation, native replay, refusal handling, model discovery | Working (mock-HTTP contract tests); **not verified against live APIs** | `app/providers/`, `tests/contract/` |
| BYOK: OS keychain, encrypted-file fallback, keys never returned by the API | Working | `app/security/credentials.py`, tests |
| Tools with server-side permission checks; Docker sandbox (no network, read-only root, non-root, limits) | Working, sandbox verified with real Docker | `app/tools/`, `test_sandboxed_execution_is_isolated` |
| LangGraph run graph + Postgres checkpointer, durable leased worker, restart recovery | Working | `app/orchestration/graph.py`, `app/worker.py`, recovery test |
| SOW planning/approval, clarifications, delegation, pause/resume/cancel, budgets, QA rework loop, consolidation, exports | Working (scripted/fake provider) | `tests/integration/` |
| FastAPI API, loopback host check, CSRF header, SSE stream | Working | `app/main.py`, `app/api/routes.py` |
| Frontend (React/Vite/Tailwind/Phaser office) | **Missing** | — |
| Startup script, docs, Playwright e2e, real-provider journey | **Missing** | — |
| Known defects | 2 failing tests (mock header access in a contract test; a blank PDF page counted as text) | `PROGRESS.md` |

Expensive or risky areas still ahead: the pixel-art office (assets, animation, event mapping),
the client-facing UI for approvals and plan editing, and live-provider verification.

## 3. Candidate comparison matrix

| Repository @ commit | License | Stack | Maintenance signals (2026-11-18) | Tests | Relevant capability | Security concerns for us | Integration cost | Recommendation |
|---|---|---|---|---|---|---|---|---|
| [gonzalonicolasr/pixel-office](https://github.com/gonzalonicolasr/pixel-office) @ `d8e9f8dc` (2026-10-18) | MIT | TS, React 19, three.js, Node server | Created and last pushed the same day; 5★; no releases | 9 files (server + routing + SSE) | Code-drawn chibi sprites; lead routing (zero-assignment path); permission modal; SSE | Runs agent commands on the **host** via `/bin/sh -c`; API keys stored in **plaintext** `data/office.json` (0600); in-memory runs, no durability | High (different renderer and runtime) | **Patterns only** |
| [W17ant/Claude-Office](https://github.com/W17ant/Claude-Office) @ `ff2b52f5` (2026-11-18) | MIT, with NOTICE **excluding** the "Dunder Mifflin" skin (TV-show fan art: character sprites, props, quotes) | TS/React DOM+CSS renderer, Electron, Express, ws, better-sqlite3 | Active; releases v1.3.0 (2026-11-16); 390★; 3 open issues | 139 test files | Pure event→state reducer with separate frame step; snapshot reconciliation; walk/room transfers; reduced-motion CSS; ws auth | Built around Claude Code hook events; mascot ("Claude") sprites carry brand association; 1,207 sprite files, partly excluded from the MIT grant | High (Claude-Code-specific server; DOM renderer, while our spec requires Phaser) | **Patterns only**; do not take assets |
| [TensorOpsAI/agent-scrum](https://github.com/TensorOpsAI/agent-scrum) @ `e901b4cf` (2026-06-10) | MIT | Python FastAPI, SQLite, LangChain + Gemini, React 18 + zustand | Last push 2026-09-11; 26 open issues; no releases | 13 backend test files | Kanban boards, A2A messages, agent registry, ws broadcast | Its swarm module says it *replaced* the LangGraph StateGraph with a polling manager; adds a 3 s minimum "working time for visual feedback" and generates simulated data (shows activity that did not happen); Gemini-only model wiring | High; conflicts with "every visual state = recorded event" | **Reject** (kanban column idea only) |
| [JoelJohnsonThomas/ForgeFlow](https://github.com/JoelJohnsonThomas/ForgeFlow) @ `b1dd115f` (2026-07-01) | Apache-2.0 | Python LangGraph supervisor, FastAPI, Postgres checkpointer, Helm, Streamlit, MCP | Last push 2026-07-02; 7★; 0 issues | 48 test files | `interrupt_before` human approval; AsyncPostgresSaver; tool-output injection envelope; SSRF/PII guards | Heavy transitive deps (Slack, HubSpot/SAP connectors, pgvector, LangSmith, Tavily, Streamlit); approval suspends the **whole** graph | Medium–high; our checkpointer already matches theirs | **Pattern only** (output envelope hardening) |
| [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) @ `0d21f7ff` (2026-11-03) | MIT | Next.js, `@langchain/langgraph-sdk`, Radix | **Archived**; 93 open issues; 3.2k★ | 0 test files | Streaming threads, interrupt inbox, tool-call table, artifact panel | Requires the LangGraph Server API (threads/runs), which our FastAPI backend does not expose; archived = no security fixes | High (Next.js to Vite port plus a different backend protocol) | **Reject** (interaction ideas only) |
| [sagiyaacoby/Orchivra](https://github.com/sagiyaacoby/Orchivra) @ `3cc99ecb` (2026-11-10) | MIT (+ NOTICE) | Node.js single `server.js`, vanilla JS portal, PTY | Active; v3.2.3 (2026-11-10); 38★ | 1 test file | Task lifecycle with approval gates; blocker protocol; per-agent short/long memory; versioned task deliverables | Drives the Claude CLI through PTYs and injects decrypted secrets into terminals; Claude-CLI-only runtime | High (runtime incompatible with BYOK multi-provider) | **Patterns only** |

## 4. Subsystem decisions

| Subsystem | Decision | Rationale |
|---|---|---|
| Data model, migrations, state machines | **KEEP** | Complete and tested; no candidate uses Postgres + migrations at this granularity apart from ForgeFlow, whose schema targets a different domain. |
| Provider adapters / BYOK credentials | **KEEP** | Every candidate is weaker here (plaintext keys, env-only keys, or single-provider). |
| Orchestration engine (LangGraph + DB-authoritative tasks, leased worker) | **KEEP**, with adapted patterns | ForgeFlow's checkpointer approach equals ours; its graph-wide interrupt is coarser than our per-task suspension. Adapted: lead may complete work without delegating (pixel-office), conditional QA and consolidation (§9.1). |
| Context management / agent memory | **ADAPT** (pattern) | Orchivra's per-agent short memory, implemented as task-scoped "your earlier work on this project" derived from existing records (no schema change). Pixel-office's "teammates are doing X, don't duplicate". |
| Prompt-injection boundaries | **ADAPT** (pattern) | ForgeFlow's envelope rules: sanitized name attribute and neutralized closing tags. Their HIGH-risk redaction is not adopted: it would erase legitimate client material. |
| Artifact conflict prevention | **ADAPT** (pattern) | Orchivra-style ownership: an agent may not overwrite a teammate's deliverable unless its task is a rework or consolidation task targeting it. |
| Tool sandbox | **KEEP** | Candidates run on the host (pixel-office, Orchivra) or rely on external connectors. |
| Office visualization | **BUILD**, using the Claude Office architecture pattern | Spec mandates Phaser; Claude Office's code is DOM/CSS and hook-specific, and its art is partly excluded or brand-associated. We build a pure `reduce(state, event)` + `step(state, dt)` model with injected randomness, rendered by Phaser with procedurally drawn original sprites (pixel-office shows code-drawn sprites are viable). |
| Activity streaming | **KEEP** (SSE + `Last-Event-ID`) | Equivalent to the candidates' ws streams; snapshot-then-stream reconciliation as in Claude Office. |
| Chat / approvals UI | **BUILD**, adapting agent-chat-ui ideas | Interrupt-inbox and tool-call-table presentation ideas; no code (Next.js, LangGraph-SDK-bound, archived). |
| Task board | **BUILD**, adapting the agent-scrum idea | Kanban columns by task status in the Projects view. |

No subsystem is **REPLACE**d. No change requires your approval under §9 of the brief: no framework
replacement, database migration, removal of working functionality, or new security dependency.

## 5. Architectural recommendation

```
Browser (React + Vite + Tailwind)
 ├─ Pages: Dashboard · Office · Team · Projects (incl. kanban) · Deliverables · Activity · Costs · Settings
 ├─ officeModel.ts   pure reduce(event)/step(dt)   ← Claude Office pattern (original code)
 ├─ OfficeScene.ts   Phaser renderer, procedural original sprites  ← pixel-office idea
 └─ useProjectStream  snapshot (/state) + SSE (/stream?after=seq)
        │  HTTP (loopback, CSRF header)
FastAPI ── routes / decisions ── Postgres (single source of truth)
        └─ worker (lease) ── LangGraph run graph ── runner ── tools ── Docker sandbox
                                     └─ context.py: scoped context + agent memory + teammate awareness
```

There is still one execution state (Postgres), one orchestration engine (the LangGraph graph plus
the DB task table) and one event system (`agent_events` → SSE). Nothing external was added.

## 6. Estimated effort (qualitative)

- Pattern adaptations in the backend: **small**. Localized changes to the planner, review gate, context
  builder and tools, each covered by tests.
- Office built on the reducer/step pattern: **medium**. The pattern reduces rework risk because the
  animation logic is testable without a browser.
- Adopting any candidate wholesale: **large**, and each would reintroduce problems we already avoided
  (host execution, plaintext keys, simulated activity).
- Uncertainty: the visual quality of procedural sprites is a design risk, not a technical one. Live-API
  behavior remains unverified until a key is provided.

## 7. Provenance

No third-party source code or assets were copied into AgentOffice, so no license notices are
required. The design ideas adapted, credited for transparency:

| Idea | Source (URL @ commit, file) | License |
|---|---|---|
| Pure event→state reducer with separate frame step and injected randomness | W17ant/Claude-Office @ ff2b52f530ebaa30ca8a48445ec7384d1fbf43a6, `src/officeReducer.ts` | MIT (idea only) |
| Lead may answer alone; briefs name teammates' parallel work | gonzalonicolasr/pixel-office @ d8e9f8dcd8ad3a3b502570a77458a98ba1e402e0, `server/orchestrator.ts` | MIT (idea only) |
| Code-drawn pixel sprites | same repo, `src/office/sprites-chibi.ts` | MIT (idea only) |
| Untrusted-output envelope with sanitized name and neutral close tag | JoelJohnsonThomas/ForgeFlow @ b1dd115f2387c11fd5f84a8c11d6179b91b0147c, `forgeflow/security/tool_output_guard.py` | Apache-2.0 (idea only) |
| Per-agent short memory; blocker visibility for the orchestrator | sagiyaacoby/Orchivra @ 3cc99ecb6956b6929ec6f18da0086e8915e41abd, `server.js` | MIT (idea only) |
| Kanban task columns | TensorOpsAI/agent-scrum @ e901b4cfc923d016c8841a658606ce955df02ea1, `backend/app/db/models.py` | MIT (idea only) |
| Interrupt inbox / tool-call table presentation | langchain-ai/agent-chat-ui @ 0d21f7ff4c45287797e876dc6d8b150b6f277b1e, `src/components/thread/agent-inbox/` | MIT (idea only) |

## 8. Integration risks

- Ideas, unlike libraries, bring no upstream fixes; we own the implementations and their tests.
- Conditional QA means some projects finish with no QA review. Mitigation: the SOW states it, the
  client approves it, and the acceptance card says "no QA review was performed".
- The deterministic summary for single-task runs is less rich than a PM-written one, but costs no
  model call.
- The artifact ownership guard could block a legitimate edit. The tool error explains the alternatives
  (delegate to the owner, or use a new name).

## 9. Changes implemented from this assessment

1. **Selective orchestration**: the plan carries `qa_review` (PM's proposal; client can toggle). QA runs only
   when requested and a QA Reviewer is hired. A single-task run without QA gets a deterministic delivery summary
   instead of a consolidation model call. The PM may assign work to itself.
2. **Envelope hardening** in `tools/files.py` (attribute sanitizing, closing-tag neutralization) for all client
   reference-file content shown to agents.
3. **Teammate awareness** in task briefs (parallel tasks and their owners).
4. **Scoped agent memory**: an agent's own earlier handoff summaries in this project are included in its next brief.
5. **Artifact ownership guard** in `write_artifact`.
6. Each change is covered by new tests, and the full suite passes (see the engineering report).
