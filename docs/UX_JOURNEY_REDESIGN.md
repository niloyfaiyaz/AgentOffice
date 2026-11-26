# UX and project-delivery redesign

*Implemented 2026-11-25 (commit `1465726`). Open-source groundwork and approved dependency decisions:
[UX_OPEN_SOURCE_FOUNDATIONS.md](UX_OPEN_SOURCE_FOUNDATIONS.md).*

## 1. Previous journey and the friction it caused

An informal walkthrough by someone experienced in agentic AI found the features worked, but the
journey felt like a collection of tools rather than a project-delivery environment. In the code,
that showed up as five problems.

| Before | Friction |
|---|---|
| A **feature-first sidebar**: Dashboard, Virtual Office, Team, Projects, Deliverables, Activity, Costs, Settings | The user had to know which feature held the thing they wanted. Five of the eight sections needed a project picked first, each with its own dropdown |
| A **form-first wizard**: template → name / objective / deliverables / constraints / success criteria / budget → files → hire agents one by one → "Go to project" → "Ask the PM for a plan" | Users configured before they were understood. There was no clarification, and agents and models were chosen before any plan existed |
| A **heuristic "Anything missing?" list** | It flagged gaps but asked nothing and filled nothing |
| The **plan approval** sat on a project-page tab, apart from the team and budget | Approval was disconnected from the rest of the setup |
| **One "Talk to the PM" form** where the user had to pick the message type | There were no agent threads. Agent questions lived only on approval cards |
| **Office in its own section**, with the agent panel beside it | There was no sense of "entering" the project. "Waiting for a teammate" was not visible |
| A **plain `<select>`** for switching projects | Each page had its own switcher, and state could only be resumed by reading history |

## 2. New information architecture

```
Global:  My projects (Home)  ·  + New project  ·  Inbox (badge)  ·  Settings (→ Agent library)

Setup:   /new  →  /new/:id   Describe & clarify → Project brief → Team → Review & approve

Project workspace  /p/:id   [project switcher ▾] [status] [decisions badge]
         phase: Discover · Define/Requirements · Plan · Execute/Build & test · Review & deliver
         ├── Office & overview   where things stand · next step · decisions · delivery summary · office
         ├── Messages            team thread (PM) · one thread per agent · discovery history
         ├── Work plan           run controls · task board · requirements · change request
         ├── Deliverables        versions · lineage · QA findings · export · acceptance
         └── Team & costs        agents · models · permissions · costs · limits · activity log
```

- **Old URLs redirect:**
  - `/projects/:id` and `/office/:id` go to the workspace;
  - `/deliverables/:id` and `/costs/:id` go to the matching tab;
  - `/team` goes to `/settings/agents`.
- **Every workspace view is keyed by the project id.** Switching projects remounts the office,
  messages, deliverables and costs, so nothing from the previous project can leak into the next.
  This is covered by the Playwright journey.

## 3. The journey and its key screens

1. **Describe the project.** The screen asks "What would you like your team to work on?". It has a
   large free-text box, optional file attachments, optional template chips and a "Start project"
   button. No agents or models are chosen at this point.
   - `POST /api/discovery` creates a draft project with a provisional unique name, hires the
     Project Manager with a default model, and stores the description as the first discovery
     message.
2. **Clarify.** The PM runs on the **real configured provider**, budget-checked through the single
   model gateway (`orchestration/llm.call_model`, purpose `discovery`).
   - **What it does:** proposes a structured brief and asks at most 3 questions per turn. It may
     only ask about scope, users, deliverables, constraints, feasibility, permissions or
     acceptance. Reasonable defaults are recorded as **labelled assumptions** instead.
   - **How the user answers:** each question shows option buttons, an "I don't know" button and a
     free-text composer.
   - **Limits:** after 3 turns the brief is presented as ready.
   - **Record:** the conversation is kept as the project's discovery history, and is also listed
     under Messages.
3. **Project brief.** The brief is generated and fully editable. It covers:
   - name, objective, audience;
   - in scope and out of scope;
   - deliverables, requirements, constraints;
   - assumptions, open questions, success criteria.

   **Provenance labels.** Every item shows **From you** (taken from the client's words), **AI
   proposal**, or **Edited by you**. Later PM turns never overwrite client edits and never
   re-propose items the client deleted.

   **Confirming.** "Confirm brief" mirrors the brief into **versioned requirement items (R-001…)**
   through the existing `requirements.sync_core`. Supersession, traceability, impact analysis and
   the stale-delivery gate therefore apply unchanged. Editing a confirmed brief retires the
   changed items (history kept) rather than deleting them.

   **Brief history.** Every change, whether by the PM or the client, is listed.
4. **Recommended team.** The PM's recommendation is part of the same discovery call, so it costs
   no extra model call. It aims for the smallest team. Each card shows:
   - character, role, responsibility and why the agent is needed;
   - the default model and its cost tier;
   - typical task cost from this installation's history, or "no cost history yet";
   - the tools the agent can use.

   "Accept team" hires the ticked roles. The existing team editor then allows changes to models,
   instructions, tools, limits and roles, and adding or removing agents.
5. **Integrated review and approval.** The review shows:
   - the requirements, with refs;
   - team and models, flagging any provider that is not connected;
   - the budget, editable;
   - the plan estimate;
   - the **existing statement-of-work editor**: plan, deliverables, dependencies, assumptions,
     risks, tool authorizations, QA toggle, revise or reject.

   **"Approve & Start Project"** is the SOW approval, unchanged server-side. It is disabled, with
   the reason shown, until every agent's provider is connected and any budget change is saved.
   Tool authorizations remain explicit checkboxes, and nothing is silently authorized.
6. **Project workspace.** After approval, the app opens `/p/:id`. The overview shows:
   - **where things stand:** the last meaningful update, what each busy agent is doing, and the next
     recommended action;
   - **pending decisions,** as inline cards;
   - **the office;**
   - once the run completes, **the delivery summary**.

**Messages.**
- **Threads:** a project thread where the PM is the default contact, plus one direct thread per
  agent.
- **Answering questions:** if an agent has an open question, typing in its thread answers it, using
  the same approval record. The acknowledgement comes from AgentOffice, not the agent.
- **Classification:** other messages are classified first by a deterministic rule and then by the
  answering model.
  - Requirement changes, scope changes, cancellations and approvals are **only suggested**, as a
    card that sends them through the existing structured flow when the client confirms.
  - Instructions to a specialist with open work are recorded on that task.
- **Decision history:** listed per thread.

**Inbox.**
- **Needs your action:** pending approvals, discovery questions and failed runs. Each item is the
  one underlying record, linked to where it is handled.
- **Updates:** informational events (run completed, brief confirmed, requirement superseded…),
  kept separate, with per-browser read state.
- **Not included:** routine agent events.

**Agent inspection** is a slide-out drawer showing:
- identity and role;
- "Now", as a plain sentence, and what the agent is waiting on (teammate or client);
- dependencies and latest output (linked to the deliverable);
- recorded actions and hand-offs;
- model and estimated usage cost;
- "Message ⟨agent⟩".

The technical view shows the recorded conversation only. Private model reasoning is neither
recorded nor shown.

**Visual status.**
- Office characters carry a plain-text tag, for example "needs you", "waiting: Archie", "working"
  or "done", next to the existing icons, so state never depends on colour or animation alone.
- "Waiting for another agent" is derived only from recorded task state: an open dependency or
  delegated sub-task.

**Handover.** The delivery summary shows:
- the objective;
- deliverables, linked;
- requirements coverage, with the caveat that a link is not proof the requirement is met;
- QA results, unresolved findings and accepted assumptions;
- total estimated cost and recommended next actions;
- export, accept and request-revision actions, using the existing acceptance record.

**Returning to a project.** The overview always opens with status, last update, what agents are
doing, pending decisions and the next step, so nobody has to reconstruct context from the
activity log.

**Empty and error states, all explained in the UI:**
- **No API key:** a banner on Home and New project, and a non-AI prefill during discovery.
- **No cost history:** the estimate says so.
- **Provider not connected:** approval is gated with the reason shown.
- **No recommended agents:** the team editor and the agent library.
- **Insufficient budget:** discovery says the call was not sent; runs keep their existing budget
  decision card.
- **Awaiting approval:** the workspace returns to the setup review for the first plan.
- **Agent failure:** the failure card and an inbox item.
- **No deliverables or messages yet:** explanatory empty states.
- **Paused, completed or cancelled:** the next-step text.

## 4. Project-delivery principles

- **The lifecycle is visible but never rigid.**
  - Discover, Define, Plan, Execute and Review & deliver are shown as an informational phase strip.
  - The labels adapt to the project type: "Requirements · Build & test" for software, "Define
    questions · Research & write" for research.
  - Feedback and changes are accepted at any point.
- **The discipline is kept:**
  - discovery and clarification;
  - a client-confirmed scope;
  - a plan approval before any work;
  - named owners for every task;
  - independent QA;
  - change impact with confirmation;
  - deliverable acceptance.
- **AI removes the paperwork, not the checks:**
  - the PM drafts the brief, team and plan;
  - the client confirms the brief, the team and the plan;
  - chat never authorizes a consequential action.
- **One orchestrator for every project type.** A template or project type only changes defaults
  and labels.

## 5. Existing components reused (not rebuilt)

| Reused | Where |
|---|---|
| LangGraph run graph, worker, planner, runner, review gate, consolidation | Unchanged |
| `requirements.sync_core`, supersession, `traceability.*`, stale-delivery gate | The confirmed brief feeds `sync_core` (new `assumption` kind) |
| `ApprovalCard` and the SOW editor | Inline in Messages, Overview, Work plan and the setup review. `SowEditor` is exported with an approval gate |
| `TeamEditor`, `FilesPanel`, Deliverables, Costs, Activity | Inside workspace tabs |
| `useProjectStream` (snapshot + SSE), the office reducer, Phaser scene and sprites | Office view; the scene gained text tags |
| Budget gateway (`plan_call`) | Applies to discovery and chat calls |
| Project delete logic | Moved to `services.purge_project`, shared with the cleanup command |

New UI primitives, as approved: `@radix-ui/react-dialog` 1.3.1 (modals and the agent drawer,
replacing the hand-rolled dialog, which had no focus trap), `@radix-ui/react-popover` 1.3.1 and
`cmdk` 1.1.1 (the project switcher). See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## 6. Backend changes

| Change | Files |
|---|---|
| **Migration `0004`** adds three columns: `projects.name_key` (normalized name; partial **unique index** over active user projects), `projects.origin` (`user` / `acceptance_test` / `scripted_test`) and `projects.brief` (JSON). Existing duplicate names get " (2)", " (3)"…, with a `project_renamed` event; nothing is deleted | `migrations/versions/0004_…`, `models.py`, `naming.py` |
| **Discovery and brief:** `POST /discovery`, `GET /projects/{id}/discovery`, `POST …/discovery/turn`, `PUT …/brief`, `POST …/brief/confirm` | `discovery.py`, `api/workspace.py` |
| **Team, estimate, inbox:** `GET …/team/recommended`, `POST …/team/hire`, `GET …/estimate` (median recorded cost per completed task on each model; unavailable below 3 samples), `GET /inbox` | `api/workspace.py` |
| **Messages:** `intent: "auto"` (the default), direct agent threads (`agent_id`), `GET …/threads`, answer-by-message, model and heuristic intent classification returned as a suggestion | `api/routes.py` |
| **Names:** 409 with a friendly message on create, rename and unarchive into a conflict. **Archived projects free their name**; restoring one into a conflict asks for a rename. Test projects sit outside the user's namespace. In a multi-user deployment the unique index would add the owner id | `services.ensure_name_available`, `routes.py` |
| **Agent detail** adds the focus task, waiting-on, dependencies and latest output. **Project state** adds the last meaningful update and the brief | `routes.py` |
| **Synthetic data:** `./agentoffice cleanup-test-data`. A dry run classifies projects on *evidence* only: project ids in committed acceptance evidence under `docs/`, or all-scripted-provider projects with no real calls. `--mark` hides them (reversible); `--delete --yes` permanently deletes flagged projects | `cleanup.py`, `agentoffice` |
| **Scripted provider:** deterministic discovery and chat replies, labelled "not AI" | `providers/scripted.py` |
| Older projects without a structured brief get one prefilled from their form fields, marked "from you" | `discovery.from_legacy` |

No change was made to the orchestration engine, the run, task or decision tables, budget
enforcement, security controls or the Phaser office's event model.

## 7. Test results (2026-11-25)

| Suite | Result | Provider |
|---|---|---|
| Backend: pytest on real PostgreSQL 16 and the Docker sandbox | **88 passed**, 11 of them new, in `tests/integration/test_journey.py` | Scripted / fake (not AI) |
| Frontend unit: Vitest | **22 passed** (6 new: agent situation, next step, phase, composer) | n/a |
| Playwright: isolated server and test DB | **4 passed**, including the 18-step first-time-user journey | Scripted (not AI) |
| **Real-provider smoke test** (`frontend/e2e/acceptance/ux_smoke.py`) | **all 8 steps passed, est. $0.0625** against a $0.40 cap (authorized $0.50) | **Real OpenAI**: gpt-5.4 (PM), gpt-5.4-mini (specialists) |

**What the Playwright journey verifies.** It acts as a first-time user:
1. Opens AgentOffice and starts from free text.
2. Answers the PM's question.
3. Checks the prefilled brief and its provenance labels, then renames the project.
4. Reviews the minimal team, without unneeded roles.
5. Changes the Developer's spending limit, verified in the database.
6. Approves in the integrated review and lands in the office.
7. Inspects Archie, who is "waiting for you", and finds Dev "waiting for Archie".
8. Messages the PM, and checks that a change-like message is only suggested, with the requirement
   count unchanged.
9. Answers Archie by typing in Archie's thread. The run completes through QA and consolidation
   with **one run** (no restart).
10. Checks that requirement refs and task links are intact and that the message is recorded in the
    team thread.
11. Finds the item in the Inbox and opens it.
12. Finds the deliverable.
13. Switches to a second project (only its agents appear) and back (the delivery summary
    persists).
14. Accepts and exports a valid ZIP.
15. Confirms a normalized duplicate name is rejected (409) and a synthetic project never appears in
    the list.

**Real-provider observations.** Evidence is in [docs/ux-smoke/evidence.json](ux-smoke/evidence.json).

- **Turn 1:** the PM asked 3 relevant questions (access model, how itineraries are generated, and
  which fields suggestions need), recorded labelled assumptions (browser app, MVP, no payments),
  and recommended PM, BA, Developer and QA.
- **Turn 2:** after the answers (including an "I don't know"), it asked 2 more questions. The
  client could confirm anyway: open items stay as open questions and assumptions.
- **Requirements:** confirming produced R-001…R-029.
- **Chat:** the model classified "Actually, it should target families… instead" as a
  `requirement_change` and only suggested it. An ordinary question was answered.
- **Plan:** the PM drafted one. The test stopped at the approval card (rejected), so no execution
  money was spent.

**Data hygiene on this installation:**
- Migration 0004 renamed four of the five acceptance-test projects named "CSV Import Assistant",
  giving them suffixes (2)–(5).
- `cleanup-test-data --mark` flagged those five, matched by id against committed evidence, as
  acceptance test data, plus the smoke-test project created with that origin. They are hidden from
  the project list.
- "Create a FAQ agent" is classified as a user project and is untouched.
- **Nothing has been deleted.** Deletion awaits the owner's approval.

**Automated tests show the flows work; they do not show the UX is intuitive.** That still needs
observation of real first-time users (see §8).

## 8. Limitations and unresolved decisions

1. **Usability is unvalidated.** Recommended next: observe 3–5 nontechnical founders and students
   doing the travel-app scenario unassisted, and measure time to approved plan and errors.
2. **Real PMs may ask follow-ups for up to 3 rounds** (5 questions in the smoke test). The cap and
   the "confirm anyway" path prevent loops. Whether 3 rounds is right needs user observation.
3. **The requirement links the PM creates are too broad.** In the smoke test, the first plan task
   cited about 22 requirements, which limits targeted rework. This is the risk already recorded in
   CHANGE_MANAGEMENT_VALIDATION.md.
4. **The plan estimate needs at least 3 completed tasks per model in this installation's history.**
   A fresh install shows "no reliable estimate yet". The budget is enforced regardless.
5. **Discovery and chat replies are not streamed.** A turn takes about 5–12 s with a "thinking…"
   indicator. Each direct message to an agent is one budget-checked model call.
6. **The acceptance script still drives the old wizard.** `frontend/e2e/acceptance/run-acceptance.mjs`
   was written for the pre-redesign UI. It remains as the tool behind the committed evidence and
   needs porting to the new journey before it is reused. The new `ux_smoke.py` covers the
   redesigned path through the API.
7. **README screenshots predate the redesign**, except the office, which is unchanged in substance.
8. **Inbox read state is per browser** (a convenience, in local storage). Action items come from
   the server and are always accurate.
9. **Decision for the owner:** whether to permanently delete the 6 flagged test projects with
   `./agentoffice cleanup-test-data --delete --yes`. The committed evidence under `docs/` is never
   touched.
10. **Not built,** because it is out of scope or would duplicate existing work:
    - token streaming;
    - per-section requirement lineage;
    - academic AI-use modes (G3 in PRODUCT_STRATEGY.md);
    - multi-user ownership.
