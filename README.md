<div align="center">

<img src="frontend/public/favicon.svg" width="72" alt="AgentOffice logo" />

# AgentOffice

**Hire an AI consulting team. Approve the plan. Watch them work. Get reviewed, versioned deliverables.**

A local-first, no-code workspace where a Project Manager agent plans, specialist agents do the work,
a QA agent reviews it, and *you* stay the client: approving scope, answering questions, changing
requirements mid-project, and controlling spend. All of it is visualized live in a pixel-art office.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-orchestration-1C3C3C)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Phaser](https://img.shields.io/badge/Phaser-3-8A2BE2)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![BYOK](https://img.shields.io/badge/BYOK-Anthropic%20%7C%20OpenAI-black)
![Tests](https://img.shields.io/badge/tests-75%20backend%20·%2015%20UI%20·%202%20e2e-brightgreen)

<img src="docs/images/office-working.png" width="860" alt="The pixel-art office: Bea is working, Archie has just been assigned a task, and the status board shows the run state and spend" />

</div>

---

## Why AgentOffice?

Most multi-agent tools are developer frameworks: node graphs, YAML and Python. AgentOffice is for the
people who actually manage projects, such as **product managers, business analysts, founders and
consultants**. It translates agent engineering into management language:

| Engineering concept | In AgentOffice |
|---|---|
| Orchestrator | Your **Project Manager**, who plans and delegates |
| Agent config / system prompt | An **employee profile** and job description |
| Model selection | Each consultant's **model and cost tier** |
| Task graph | A **statement of work** you approve or edit |
| Human-in-the-loop | **Client decisions**: questions, approvals, budget calls |
| Token usage | **Billable usage**, per agent, task and model |
| Artifacts | **Versioned deliverables** with QA findings |

And it's honest by design. Nothing in the office animates unless a real backend event happened, costs
are labelled as estimates, and a QA "pass" is described as an opinion rather than proof.

## What it does

**🧑‍💼 Build a team.** Hire from 8 built-in roles (PM, Business Analyst, Research Analyst, Architect,
Developer, QA, Technical Writer, Data Analyst) or create your own. Give **each agent its own model**:
Claude for planning, a cheaper model for drafting, whatever fits the budget. Start from templates for
PRDs, competitive analysis, prototypes or process analysis, or describe any goal.

**📋 Approve the plan.** The PM turns your brief into a statement of work: tasks, dependencies,
assignees, acceptance criteria, risks and tool needs. Every task cites the requirement IDs (R-001…) it
implements. Edit assignments, drop tasks or answer the PM's questions, then approve. Nothing runs before you do.

<img src="docs/images/plan-approval.png" width="760" alt="Statement of work approval: scope, deliverables, acceptance criteria and assumptions" />

**🏢 Watch real work.** Tasks run in parallel where dependencies allow. Agents delegate, hand off, ask
you questions (you'll see them waiting at the client desk ✋) and review each other's output. Click any
agent to see its current task, tokens, spend, hand-offs, and the raw conversation in an advanced view.

**🔁 Change your mind mid-project.** This is the part most systems get wrong.
1. Submit a change.
2. The PM proposes which requirements it **replaces**.
3. AgentOffice computes, from task-to-requirement links and artifact lineage, **exactly which work is
   affected**: completed work, work in progress (reworked after it finishes) and downstream tasks.
   Everything else is kept.
4. You confirm.
5. A deterministic gate then **blocks delivery of any document still based on a retired requirement**.

<img src="docs/images/change-impact.png" width="760" alt="Change impact card: the PM pre-selects R-009 as replaced by the new email-or-phone rule" />

**✅ Get reviewed deliverables.** QA checks every deliverable against the acceptance criteria and sends
targeted rework, in bounded cycles. Deliverables are versioned, with lineage showing which requirements
each version implements and which inputs it came from. Export Markdown, DOCX, JSON, CSV or a ZIP with
a manifest.

**💸 Stay in control of spend.**
- **Budgets per project, agent and task**, checked *before* every call.
- **No early stops:** when the budget is tight, a call's output allowance is reduced to what you can
  afford instead of stopping the run.
- **Full breakdowns** of tokens and estimated cost per agent, task and model.

<p>
<img src="docs/images/deliverables.png" width="49%" alt="Deliverables with versions, export formats and QA findings" />
<img src="docs/images/costs.png" width="49%" alt="Costs by agent, model and task" />
</p>

## Does it actually work?

AgentOffice was tested end-to-end by an autonomous QA run that drove the real UI with Playwright and
**real OpenAI models**, including a requirement change mid-project. All evidence (every artifact
version, event log, usage record and screenshot) is committed in [`docs/`](docs):

- **[Acceptance report](docs/AGENTOFFICE_E2E_ACCEPTANCE_REPORT.md):** a full client journey, five defects
  found and fixed, re-verified live.
- **[Change management and multi-agent vs single-agent study](docs/CHANGE_MANAGEMENT_VALIDATION.md):**
  identical brief, identical change, same model, blind AI-evaluated.

| Same brief + mid-project change, gpt-5.4 | Single agent | Multi-agent team |
|---|---|---|
| Blind rubric score (AI evaluator, blinded) | 19 / 35 | **29 / 35** |
| Deterministic deliverable checks | 14 / 16 | **16 / 16** |
| Real defects found and fixed by its own QA | 0 (no QA) | **3** |
| Estimated cost | **$0.14** | $0.51 |
| Execution time | **69 s** | 187 s |

These are honest numbers: on this task, the team produced clearly better, more testable documents,
for about 3.6× the cost. AgentOffice lets you pick that trade-off per project.

## Quick start

**You need:** macOS or Linux, [Docker Desktop](https://www.docker.com/products/docker-desktop/),
Python 3.11+, Node 18+, and an **API key** from the
[Anthropic Console](https://console.anthropic.com/) and/or the [OpenAI platform](https://platform.openai.com/).
A Claude Pro or ChatGPT Plus subscription does not include API credits.

```bash
git clone https://github.com/niloyfaiyaz/AgentOffice.git
cd AgentOffice
./agentoffice start
```

The first start installs everything, starts PostgreSQL in Docker, builds the code sandbox and the UI,
then opens **http://127.0.0.1:8765**. Then:

1. **Settings:** paste your API key. It's stored in your OS keychain, never in the database or the browser.
2. **Start new project:** pick a template and describe the outcome you want.
3. **Hire the recommended team** and pick a model for each agent.
4. **Ask the PM for a plan**, review it, and approve.
5. **Open the Virtual Office** and watch, answering questions as they come.

```bash
./agentoffice stop --all   # stop everything
./agentoffice logs         # server and worker logs
./agentoffice test         # backend and UI test suites
```

## Privacy and security

- **Local-first.** Projects, files and history live on your machine (PostgreSQL in Docker, files under `data/`).
- **BYOK.** Your keys go to your OS keychain (encrypted-file fallback). Prompts go only to the providers
  *you* configure. No telemetry.
- **Loopback only.** The app binds to `127.0.0.1`, with host-header checks against DNS rebinding and a
  required header on writes against cross-site requests.
- **Sandboxed code.** Agent-written code runs in throwaway Docker containers: no network, read-only
  root, non-root user, CPU, memory and time limits. Each run needs your authorization.
- **Untrusted inputs.** Uploaded documents are treated as data, wrapped so agents can't be steered by
  instructions inside them.
- **Server-side permissions.** Tool permissions are enforced on the server, so an agent can't grant
  itself new powers.

## How it works

```mermaid
flowchart LR
  UI["Browser<br/>React · Phaser office"] -- "REST + SSE (loopback)" --> API[FastAPI]
  API --> DB[(PostgreSQL<br/>single source of truth)]
  W["Durable worker<br/>LangGraph run graph"] --> DB
  W --> P["Provider adapters<br/>Anthropic · OpenAI"]
  W --> T["Permission-checked tools"]
  T --> S["Docker sandbox"]
```

- **One state, one engine, one event stream.** The LangGraph run graph and the task table in Postgres
  drive execution. Every state change is an event; the office and the timeline render those events.
- **Durable.** A leased worker survives restarts. Every agent conversation is checkpointed, so tasks
  pause, wait for you and resume without losing tool calls.
- **Traceable.** Requirements are versioned items. Tasks link to the requirements they implement,
  and each artifact version records its requirements and exact inputs, which powers change impact
  and the stale-delivery gate.

More detail: [Architecture](docs/ARCHITECTURE.md) ·
[Engineering report](docs/ENGINEERING_REPORT.md) ·
[Open-source assessment](docs/OPEN_SOURCE_FOUNDATION_ASSESSMENT.md).

## Tech stack

**Backend:** Python, FastAPI, Pydantic, LangGraph (+ Postgres checkpointer), SQLAlchemy and Alembic,
the official `anthropic` and `openai` SDKs, keyring and cryptography.
**Frontend:** React, TypeScript, Vite, Tailwind, Phaser 3 (original procedural pixel art), TanStack Query.
**Testing:** pytest (against real Postgres and Docker), Vitest with React Testing Library, Playwright.

## Status and roadmap

AgentOffice is a working v1, verified end-to-end with OpenAI. Known gaps and next steps:

- [ ] Live verification with Anthropic models (the adapter is contract-tested only)
- [ ] Tighter requirement linking by the PM (broad links limit how much work a change can preserve)
- [ ] Section-level lineage (today a change reworks a whole document)
- [ ] A built-in self-review step for single-agent teams
- [ ] Web research beyond Anthropic's built-in search

Issues and pull requests are welcome. Please run `./agentoffice test` before submitting.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AGENTOFFICE_PORT` | `8765` | UI and API port (always bound to 127.0.0.1) |
| `AGENTOFFICE_DATABASE_URL` | local Docker Postgres | Database connection |
| `AGENTOFFICE_DATA_DIR` | `./data` | Uploads, exports, sandbox scratch |
| `AGENTOFFICE_CREDENTIAL_BACKEND` | `auto` | `keyring` or `encrypted_file` |
| `AGENTOFFICE_CREDENTIAL_PASSPHRASE` | — | Unlock secret for the encrypted-file fallback |
| `AGENTOFFICE_ENABLE_TEST_PROVIDER` | off | Scripted, **non-AI** provider used by automated tests |

---

<div align="center">
<img src="docs/images/office-done.png" width="640" alt="The office after delivery: every agent shows a completed check mark" />
<br/>
<sub>Built with Claude Code. Every pixel is original procedural art, with no third-party sprites.</sub>
</div>
