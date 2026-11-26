# AgentOffice product strategy

*Updated 2026-11-21. This is a product-strategy document, not a feature announcement. Every capability
below is labelled **Implemented**, **Partial**, **Planned** or **Under evaluation**. "Implemented"
means it is in the code on `main` and covered by tests or by the recorded acceptance runs in
[`docs/`](.).*

## 1. Product vision

**AgentOffice: your own AI project team, without the overhead of managing one.**

> Build your AI team, delegate complex work, manage changing requirements, and turn ideas into
> deliverables through an intuitive visual workspace.

AgentOffice is a **visual AI project-team management platform**. It is for people with ambitious
projects who need a team, not necessarily people whose job title involves managing one.

The consulting-team metaphor and the pixel-art office make multi-agent work understandable at a
glance. The value itself comes from **coordination, accountability, quality control and efficient
execution**: turning a complex, changing objective into coordinated, reviewed deliverables.

What AgentOffice is **not**:
- An app only for PMs and BAs.
- A novelty visualization of agents.
- An IDE replacement.
- A generic workflow-automation builder.

## 2. Primary customer segments

AgentOffice serves **independent project builders**. Their projects are complex enough to benefit
from a team, but they lack the resources, technical background or time to assemble one.

| Segment | Typical projects | What they need most |
|---|---|---|
| **Solo founders and entrepreneurs** | MVP specs, market and competitor research, idea validation, launch preparation, prototypes | Breadth of expertise on a small budget, with a cost they can see |
| **University students** | Capstones, product-management assignments, research projects, software projects | Structure, critique against a rubric, and AI use that stays within course rules and is recorded |
| **Product Managers and Business Analysts** | Requirements, user stories, process analysis, stakeholder changes, deliverable review | Traceability, controlled change, and QA they can defend to stakeholders |

The original PM/BA audience stays a first-class segment. The change is that the product no longer
assumes a management job title.

## 3. The shared problem

All three segments already use AI. Their problem is **coordination**, not access:

- Work is spread across separate chats, and each one loses the project's context.
- Nobody owns a task, so it's unclear who did what or what is still open.
- Outputs are not reviewed against what was actually asked.
- When a requirement changes, they must work out by hand which earlier outputs are now wrong,
  and they usually redo too much or too little.
- Spend is invisible until the bill arrives.

AgentOffice addresses this with one project state, one plan the user approves, named agents
responsible for tasks, reviewed and versioned deliverables, and change handling that knows what
depends on what.

## 4. Competitive differentiation hypothesis

The space is crowded. Relevance AI, Perplexity Computer, Taskade, CrewAI and Pixel Office are
examples. **We do not assume that visual agents, multi-model orchestration or "hiring" agents are
unique.** Other products offer some or all of them.

**Hypothesis:** AgentOffice helps people manage complex, *evolving* projects across specialized AI
agents, with transparent responsibility, costs, deliverables and changes.

The hypothesis rests on four capability groups, in priority order. The animation is not one of them.

| | Capability group | Why it matters |
|---|---|---|
| A | **Visual team management** | You can see who is working on what, what's blocked, what's delivered, and what needs your decision |
| B | **Flexible team composition** | Specialists, per-agent models and permissions, with the costs visible |
| C | **Change-aware orchestration** | A changed requirement reworks only the affected work, and outdated documents can't be delivered |
| D | **Deliverable accountability** | Versioned artifacts, requirement traceability, QA findings, approval history and exports |

C and D are the hardest to copy, and they are where the evidence is strongest (see §8).
This is a hypothesis: we have not run a structured comparison against these competitors.

## 5. Core value proposition

| For | AgentOffice gives you | Instead of |
|---|---|---|
| Anyone with a team-sized project | A planned, staffed and reviewed project from one objective | Juggling many chats and pasting context between them |
| When things change | Targeted rework of exactly what's affected, with retired requirements blocked from delivery | Starting over, or quietly shipping outdated documents |
| When money matters | Budgets enforced before every call, and spend broken down by agent, task and model | Discovering the cost afterwards |
| When quality matters | QA against acceptance criteria, evidence-based findings and bounded rework | Trusting a single model's first draft |

## 6. Product experience principles

1. **One engine, two styles.** Autopilot and Manager mode are two views of the same projects,
   agents, plans and runs. They are not separate products or execution paths.
   - **Autopilot:** the user describes an objective. AgentOffice recommends the team, the
     responsibilities and the plan. The user only approves important decisions and reviews
     deliverables.
   - **Manager mode:** the user configures agents, models, budgets and permissions, inspects
     hand-offs and intervenes during execution.
2. **Honest by design.** Nothing animates unless a real backend event happened. Costs are labelled
   as estimates. A QA "pass" is called an opinion, not proof.
3. **The client stays in charge.** Nothing runs before the plan is approved. Questions, tool
   authorizations and budget decisions come to the user.
4. **Visual first, never visual only.** Everything shown in the office also appears in conventional
   UI: the team list, task board, timeline and activity log.
5. **Templates configure; they don't fork.** A template only sets the project, team and deliverable
   defaults. It never adds its own execution logic.

## 7. Template strategy

Templates are starting points on the shared architecture. Each one only presets an objective
example, a recommended team and expected deliverables. The table maps each requested starting
point to what exists today.

| Segment | Starting point | Status today |
|---|---|---|
| Founders | Validate a startup idea | **Planned.** Use *Competitive Analysis* or *Custom* today |
| | Competitive analysis | **Implemented** (*Competitive Analysis*) |
| | MVP specification | **Partial.** *Product Requirements* covers it, but there is no MVP-specific preset |
| | Software prototype | **Implemented** (*Software Prototype*, with code run in the Docker sandbox) |
| Students | Plan a capstone project | **Planned.** Use *Custom* today |
| | Structured research | **Partial.** *Competitive Analysis* or *Custom*, with web research only through Anthropic's built-in search |
| | Review a product proposal | **Partial.** Upload the proposal; a QA Reviewer critiques it against acceptance criteria |
| | Software project | **Implemented** (*Software Prototype*) |
| | Evaluate against an assignment rubric | **Partial.** The rubric can be uploaded and turned into acceptance criteria by hand; it isn't parsed automatically |
| PMs and BAs | Product requirements | **Implemented** (*Product Requirements*) |
| | User stories and acceptance criteria | **Implemented**, as part of *Product Requirements* |
| | Business process analysis | **Implemented** (*Business Process Analysis*) |
| | Stakeholder requirement changes | **Implemented.** Change requests work on any project, not just one template |
| | Review product deliverables | **Implemented.** The QA Reviewer, findings and bounded rework apply everywhere |

**Academic AI-use controls** are **Planned**. Today a student can write course restrictions into the
project constraints and agents will see them, but nothing enforces them and there is no AI-use
record designed for submission. See gap G3.

## 8. Existing functionality supporting the positioning

### A. Visual team management (Implemented)
- **Pixel-art office** driven only by recorded events:
  - working, reviewing, communicating, blocked and done states;
  - agents walk to the client desk when they are waiting for you.
- **Agent panel:** current task, tokens, spend, hand-offs and the raw conversation.
- **Conventional views:** task board (including blocked tasks), live timeline, Activity page and
  Approvals inbox with every pending decision.

### B. Flexible team composition (Implemented, cost preview partial)
- **Roles:** 8 built-in roles, plus custom roles and reusable employee profiles.
- **Team presets** you can save and reuse.
- **Per-agent settings:** provider, model, effort, output limit, call limit and spend limit. The model
  can be changed mid-run and takes effect at the next checkpoint.
- **Server-enforced tool permissions** per agent, task and run, with client authorization for
  sensitive tools such as code execution.
- **Team recommendations,** from one of three sources:
  1. the template;
  2. a keyword heuristic, labelled as a heuristic;
  3. an AI proposal from the hired Project Manager.
- **Costs:** per-model cost tier and price source, and a breakdown by agent, task and model. There is
  **no forward-looking estimate** of what a plan will cost (gap G2).

### C. Change-aware orchestration (Implemented)
- **Versioned requirements** with stable IDs (R-001…), explicit supersession and history.
- **Impact proposal:** the PM proposes which requirements a change replaces, and the client confirms
  it on an approval card.
- **Impact analysis** comes from task-to-requirement links, task dependencies and recorded artifact
  consumption. Unaffected work is kept.
- **Delivery gate:** a deterministic, stage-aware gate blocks QA, consolidation and delivery of any
  artifact based on a retired requirement.
- **Targeted rework** for completed, in-flight and downstream tasks.
- **Every change needs approval.** There is no "significant change" threshold, so even small changes
  ask for approval.
- **Estimated rework cost** on the change card (G1, implemented 2026-11-21):
  - Each affected task's recorded token usage is re-priced at its agent's current model. No model
    call is made.
  - The card totals the tasks the client selects and compares the total with the remaining budget.
  - In-flight tasks and tasks without cost data make the total a lower bound, and the card says so.
    Unpriced models are reported as unknown, not guessed.
  - Actual rework cost is still recorded per task afterwards.

Evidence (real OpenAI models):
- In the [acceptance report](AGENTOFFICE_E2E_ACCEPTANCE_REPORT.md), a mid-project change cost about
  14–20% of the run, versus 100% for a restart.
- In the [change-management validation](CHANGE_MANAGEMENT_VALIDATION.md), the multi-agent team
  scored 29/35 on a blind rubric versus 19/35 for a single agent, at about 3.6× the cost.

### D. Deliverable accountability (Implemented)
- **Versions and lineage:** versioned artifacts, each recording the requirements it implements and
  its exact inputs.
- **QA findings** with severity, evidence and a recommendation, plus bounded rework cycles.
- **Approval history:** plan, tool authorizations, budget decisions, changes and deliverable
  acceptance.
- **Exports:** Markdown, DOCX, JSON, CSV and a ZIP with a manifest.

### Experience modes
| Mode | Status | What exists | What's missing |
|---|---|---|---|
| **Manager** | **Implemented** in substance, though not labelled as a mode | Team editor, per-agent models and budgets, plan editing, tool authorization, pause, resume, cancel, retry, skip, the agent conversation view and model changes mid-run | — |
| **Autopilot** | **Partial** | Templates, recommended teams, the PM drafting the whole plan, and approvals only at decision points | One-click "hire the recommended team with sensible default models"; a single guided path that hides Manager controls until needed |

### Platform qualities to preserve
- **Local-first:** PostgreSQL in Docker, with files kept on the user's machine.
- **BYOK** for Anthropic and OpenAI, with keys in the OS keychain.
- **Real multi-agent execution** on a durable worker built on LangGraph.
- **Security:** a locked local API and sandboxed code.

## 9. Gaps requiring future work

These are recommendations, not commitments. None of them is implemented in this update.

| ID | Gap | Segment(s) | Size | Priority |
|---|---|---|---|---|
| G1 | ~~Rework cost estimate on the change-impact card~~ **Done 2026-11-21:** recorded usage re-priced at the current model, totalled against the remaining budget | All | Small | Done |
| G2 | **Plan cost estimate before approval.** Base it on task count, assigned models and historical usage, with a clear "estimate" label | All, especially founders and students | Medium | **High** |
| G3 | **Academic assistance levels and an AI-use record.** The levels are brainstorming, critique, guided learning and permitted implementation. They would be a project-level setting that restricts tools and instructions server-side, plus an exportable log of what the AI did | Students | Medium | **High** for the student segment |
| G4 | ~~Autopilot path~~ **Done 2026-11-25** in the UX redesign: describe → clarify → accept the recommended team in one click → integrated approval | Founders, students | Small to medium | Done |
| G5 | **Significant-change threshold.** Auto-approve trivial changes and require approval above an impact or cost threshold. Depends on G1 | PM/BA | Small | Low |
| G6 | **More templates:** Validate a startup idea, MVP specification, Capstone plan, Rubric review. Catalog entries only | Founders, students | Small | Medium |
| G7 | **Research beyond Anthropic's built-in search,** for OpenAI-only users | Founders, students | Medium | Under evaluation |
| G8 | **Live verification with Anthropic models.** So far only OpenAI has been verified end-to-end | All | Small (needs a key) | Medium |

Already on the README roadmap and still valid:
- tighter requirement linking by the PM;
- section-level lineage;
- a self-review step for single-agent teams.

## 10. Validation hypotheses

Validation uses the existing tests and recorded evidence first. **No new model calls were made for
this strategy update.**

| Scenario | Hypothesis | Existing evidence | Verdict |
|---|---|---|---|
| **Founder:** MVP spec for a small SaaS product | The same template, team and change engine produces a usable spec with no customization | The acceptance run built a full requirements package for a small product (a CSV import assistant) with real models, including QA rework | **Supported.** *Product Requirements* fits it. A dedicated MVP template (G6) and a plan cost estimate (G2) would make it smoother |
| **Student:** a multi-deliverable assignment with explicit AI-use limits | The same engine can run it, with limits enforced and recorded | Multi-deliverable plans and QA against criteria are proven. AI-use limits can only be stated in the project constraints | **Partially supported.** Running the work fits the architecture. Enforced limits and a record need G3, which is a project setting on the same engine, not a new architecture |
| **PM/BA:** a stakeholder change in an existing project | Impact is targeted, unaffected work is kept, and stale outputs are blocked | [Change-management validation](CHANGE_MANAGEMENT_VALIDATION.md): real-model runs, deterministic deliverable checks, and blind rubric scoring | **Supported**, the strongest evidence. The rework cost preview (G1) is now implemented |

**Conclusion:** all three scenarios run on one architecture. None of them needs a separate execution
path. The gaps are configuration and surfacing work (G2–G6), not a rebuild.

**Validation still to do:**
- **Usability:** an unassisted first-run test with one person from each segment, measuring time
  to an approved plan and whether they understood the office.
- **Willingness to pay:** whether BYOK cost visibility changes founders' and students' decisions to
  use a team over a single agent.
- **Differentiation:** whether users notice and value change-aware orchestration (C) compared with
  competitors, rather than the visualization.
