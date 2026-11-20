# AgentOffice: autonomous end-to-end acceptance report

Date: 2026-11-20 · Tester: Claude Code acting as independent QA engineer and simulated PM client ·
Scenario: **CSV Import Assistant** with change request **CR-001** · Provider: **OpenAI, real calls**
through AgentOffice's stored credential (macOS Keychain; the key was never read into the test,
printed or committed).

## A. Executive summary

| Question | Answer |
|---|---|
| **Overall outcome** | **PARTIAL.** The full journey and the deliverables **pass** on the verified run. Change management **works but is not structurally guaranteed** (open defect D4). |
| Real OpenAI calls occurred? | **Yes.** 49 real calls across two runs, 119,570 input / 22,549 output tokens, est. **$0.32** total (cap $2). |
| Full client journey completed? | **Yes**, through the real UI (Playwright) in both runs. |
| Requirement change succeeded? | **Yes.** CR-001 was recorded, impacted work was identified, approved and reworked; no restart. |
| Final artifacts consistent? | **Run 1:** content consistent, but the "QA review report" was not written by QA (defect D1). **Run 2 (after fixes): yes**, 15/15 deterministic checks. No deliverable says email is always mandatory. |

Two real runs were made:
- **Run 1** found five defects: D1, D2, D3 and D4 in that run, and D5 in a free scripted dry run beforehand.
- D1, D2, D3 and D5 were fixed with regression tests.
- **Run 2** re-executed the identical scenario against the fixed build and confirmed every fix in real
  execution.
- D4 needs a structural change and is proposed, not executed (§H).

Evidence is under [docs/acceptance/](acceptance/) (run 1) and [docs/acceptance/rerun/](acceptance/rerun/) (run 2):
`evidence.json` (events, tasks, handoffs, usage records, findings, approvals, messages), `artifacts/` (every
version of every generated document), `export.zip` (the UI export), `screens/` (screenshots) and
`checklist.json` (deterministic review). Raw run logs: `data/acceptance-run.log`, `data/acceptance-rerun.log`.
The journey script is [frontend/e2e/acceptance/run-acceptance.mjs](../frontend/e2e/acceptance/run-acceptance.mjs)
and the checklist is [check_deliverables.py](../frontend/e2e/acceptance/check_deliverables.py).

**Method.** Every client action went through the user interface with Playwright: project wizard, hiring,
the agent edit dialog, budget form, plan approval card, answering questions, the "Talk to the PM"
requirement-change form, the impact-approval card and the export link. The backend API was read only
to collect evidence and to decide *when* to act (for example, "the BA's draft is complete"). No document
was written outside AgentOffice. A free dry run on the scripted provider debugged the script before any
paid call.

## B. Journey results

| # | Step | Run 1 | Run 2 (verified) | Evidence |
|---|---|---|---|---|
| 1-2 | Launch app; frontend and backend health | PASS | PASS | log lines 1-2 |
| — | OpenAI credential valid; models priced so the budget can be enforced | PASS | PASS | gpt-5.4 $2.50/$15, gpt-5.4-mini $0.75/$4.50 per Mtok |
| 3-4 | Create "CSV Import Assistant" with the 7 requirements, email rule, exclusions, $ budget | PASS | PASS | wizard |
| 5-6 | Team: PM, Business Analyst, **Technical Reviewer** (renamed in UI), QA; models assigned in the edit dialog | PASS | PASS | `screens/01-team.png` |
| — | Budget ($2 / $1.50) and 60-call cap set through the UI **before** the first call | PASS | PASS | `budget controls set` |
| 7 | PM generates statement of work | PASS (2 tasks, 3 questions) | PASS (2 tasks, 1 question) | `screens/02-sow-approval.png`, `evidence.sow` |
| 8 | Client answers questions and approves through the approval card (QA on) | PASS | PASS | `evidence.qa` |
| 9 | Real multi-agent execution | PASS | PASS | events |
| 10 | Assignment and handoff events observed | PASS (1 delegation) | PASS (1 QA→BA rework handoff) | `evidence.handoffs` |
| — | **CR-001** submitted via "Talk to the PM" after the BA's first draft | PASS | PASS | `screens/04-cr-001-sent.png` |
| — | Impact approval shown and decided in the UI | PASS (completed tasks only) | PASS (completed **and in-flight**) | `screens/05-cr-001-impact-approval.png` |
| 11 | Artifacts produced and versioned | PASS | PASS | `artifacts/` |
| 12 | QA review and final consolidation | **FAIL** (QA report authored by the BA; QA recorded 0 findings) | PASS (QA authored its report; F-001 major → rework → resolved) | §C, §G-D1 |
| 13 | Export via the UI | PASS (12,272 bytes) | PASS (12,680 bytes) | `export.zip` |
| — | Office matches state before and after a hard refresh | PASS | PASS | `evidence.refresh` |
| — | Browser console errors | none | none | `evidence.console_errors` |

## C. Agent execution

| Agent | Role | Model | Run 2 tasks | Calls | Tokens in/out | Est. cost |
|---|---|---|---|---|---|---|
| Pat | Project Manager (orchestrator) | gpt-5.4 | plan; consolidation | 4 | 17,638 / 2,949 | $0.0940 |
| Bea | Business Analyst | gpt-5.4-mini | requirements; CR rework; QA rework | 9 | 14,945 / 4,560 | $0.0331 |
| Archie | Technical Reviewer | gpt-5.4-mini | feasibility & risk; CR rework | 4 | 8,481 / 2,942 | $0.0200 |
| Quinn | QA Reviewer | gpt-5.4-mini | QA review; re-review | 7 | 20,752 / 633 | $0.0215 |

Run 2 task sequence: BA requirements ✓ → Technical Reviewer (depends on BA) **running** when CR-001
arrived → CR approved → BA rework ✓ and Technical Reviewer rework ✓ (the rework waited for the
in-flight task) → QA review (F-001 *major*: phone-format rule left as an open question; F-002 minor) → rework handoff
Quinn→Bea ✓ → QA re-review resolved both ✓ → PM consolidation ✓. Every task completed, with 0 retries and 0 failures.

Run 1 sequence differed: the BA **delegated** the technical assessment to Archie although Archie already had
that task planned (D2), and the BA wrote a "QA review report" and a "final consolidated deliverable"
herself (D1).

## D. Artifacts

Run 2 (final, verified). The latest versions are the delivered ones:

| Artifact | Versions | Author | Path |
|---|---|---|---|
| Requirements (PRD, prioritized user stories, acceptance criteria) | v1 → v2 (CR-001) → v3 (QA F-001) | Bea | `docs/acceptance/rerun/artifacts/csv_import_assistant_requirements.md.v{1,2,3}.md` |
| Technical feasibility & risk assessment | v1 → v2 (CR-001) | Archie | `…/csv_import_assistant_technical_feasibility_risk_assessment.md.v{1,2}.md` |
| QA Review Report (traceable F-ids) | v1 (round 1) → v2 (re-review) | Quinn | `…/QA_Review_Report_run_1_.v{1,2}.md` |
| Final consolidated project deliverable | v1 | Pat | `…/final_consolidated_project_deliverable.md.v1.md` |
| Statement of work | v1 | Pat | `…/Statement_of_Work_run_1_.v1.md` |
| UI export (ZIP with manifest + QA findings) | — | — | `docs/acceptance/rerun/export.zip` |

The final deliverable cites its sources by version, for example *"A row is valid if at least one contact
method is valid: email or phone. (`csv_import_assistant_requirements.md` v3)"*.

**Deterministic checklist** (`check_deliverables.py`, independent of the QA agent; checks the latest version of every final document):

| Check | Run 1 | Run 2 |
|---|---|---|
| CSV upload, preview, duplicates, row-specific errors, confirmation, summary | PASS | PASS |
| Email-or-phone rule; reject only when both are absent or invalid | PASS | PASS |
| User stories, acceptance criteria, valid and invalid coverage | PASS | PASS |
| Technical assumptions, open questions | PASS | PASS |
| Traceable QA findings (F-xxx) in the delivered documents | **FAIL** | PASS |
| **No deliverable claims email is always mandatory** | PASS | PASS |
| **Total** | 14/15 | **15/15** |

Manual note: run 2's final document lists `email` among the "required CSV **columns**" (header presence)
next to the rule that either email or phone suffices per row. This is consistent, but the wording could be
misread; worth a client review comment.

## E. Requirement change evaluation (CR-001)

| # | Criterion | Run 1 | Run 2 | Notes |
|---|---|---|---|---|
| 1 | Records the new requirement | ✓ | ✓ | stored as a `change` requirement with source `client_message`; visible on the project page |
| 2 | Preserves the original requirement and history | ✓ (kept) | ✓ (kept) | the original stays; artifact versions preserve history (v1 = pre-change) |
| 3 | Identifies impacted work | partial | ✓ | run 1 offered completed tasks only, missing a task already running (D3, fixed) |
| 4 | Updates the affected tasks | ✓ | ✓ | targeted rework tasks; in-flight rework waits for the original to finish |
| 5 | Preserves unaffected completed work | n/a | n/a | at CR time every completed task was requirement-derived; unstarted tasks were not rerun but picked up the change |
| 6 | Prevents stale requirements in later outputs | ✓ observed | ✓ observed | **not structurally enforced**: the original "every contact must have an email" stays *active* next to the change, and agents reconcile via a "latest wins" label (D4) |
| 7 | Requests approval where required | ✓ | ✓ | impact approval card; client chooses tasks |
| 8 | Resumes execution appropriately | ✓ | ✓ | no pause or restart needed; independent work continued |
| 9 | Consistent final artifacts | ✓ (content) | ✓ | stale checks pass in both runs |
| 10 | Records the additional cost | ✓ | ✓ | per-task usage records (§F) |

The application did **not** restart the project, and no stale artifact reached final delivery in either run.
In run 1 that was partly luck: the in-flight task's pre-change output (v2) was overwritten by a later
rework (v3). Run 2's fix makes this deterministic for in-flight work.

## F. Cost and efficiency

| Metric | Run 1 | Run 2 |
|---|---|---|
| Total real calls / tokens in / tokens out | 25 / 57,754 / 11,465 | 24 / 61,816 / 11,084 |
| Est. total cost | $0.1513 | $0.1687 |
| Calls before CR-001 | 10 ($0.0444) | 3 ($0.0246) |
| Tasks invalidated by CR-001 | 2 (both completed) | 2 (1 completed, 1 in flight) |
| Tasks rerun for CR-001 | 2 rework tasks | 2 rework tasks |
| CR-001 rework calls / tokens / cost | 8 / 14,007 in, 4,011 out / **$0.0309** | 5 / 10,125 in, 3,244 out / **$0.0229** |
| Unaffected completed tasks preserved | 0 (none were unaffected) | 0 (none were unaffected) |
| Full restart | No | No |
| Stale artifacts in final delivery | No | No |
| Duplicate work | Yes: technical assessment written 3× (D2) | No |

**Targeted rework is supported.** CR-001 cost about 14-20% of the run, versus 100% for a restart. Most of
run 2's remaining cost is the PM's consolidation on gpt-5.4 ($0.077), by design (the stronger model for
synthesis).

Cumulative acceptance spend: **$0.32 estimated**, well under the $2 limit. These are estimates from
configured prices, not provider invoices.

**Architecture (static inspection, distinguished from observed behavior):**

| Property | Status | Basis |
|---|---|---|
| Versioned project requirements | **Partial.** Rows with kind, source and active/superseded status, but a change does not supersede the specific rule, and the objective is one text block | code (`ProjectRequirement`) + observed |
| Task-to-requirement dependencies | **Absent.** Impact is by task status, chosen by the client | code |
| Artifact lineage | **Present.** Versions with author task/agent, hash and sources; the final document cited `v3` | observed |
| Persistent execution checkpoints | **Present.** Per-step conversation persistence + LangGraph Postgres checkpointer; restart recovery covered by an automated test | code + tests (not exercised in these runs) |
| Safe state updates | **Present.** Validated state machines, leases, idempotency keys | code + tests |
| Configurable agent definitions | **Present.** Roles renamed and models switched in the UI | observed |
| Model replacement without hard-coding | **Present.** Per-agent provider/model; gpt-5.4 and mini mixed | observed |
| Orchestration separated from visualization | **Present.** Worker process vs. SSE-fed UI; office state identical after refresh | observed |

## G. Defects

| ID | Severity | Component | Reproduction | Expected | Actual (run 1) | Root cause | Fix | Regression | Re-verified |
|---|---|---|---|---|---|---|---|---|---|
| **D1** | High | tools / planner | Run the scenario with "QA review report" as a deliverable | the QA report comes from the QA review, with traceable findings | the BA wrote `qa-review-report.md` *before QA ran*; QA passed with 0 findings in 1 call; the final docs had no F-ids | the QA role had no way to produce a report document; the planner assigned all deliverables to the BA; no role boundary | the QA review generates an owner-attributed **QA Review Report** from recorded findings; non-QA roles cannot write QA reports; only consolidation writes the final consolidated deliverable; planner instruction | `test_D1_…` | ✓ run 2: report by Quinn, F-001/F-002, real rework loop |
| **D2** | Medium | delegation tool | BA task with a dependent planned task for the Technical Reviewer | no duplicate work | BA delegated the same assessment; it was written 3× | no check for teammates' planned downstream tasks | delegation refused when the target already has a pending/ready task that depends on the current one | `test_D2_…` | ✓ run 2: no duplicate delegation |
| **D3** | Medium | change management | CR-001 while the dependent task is running | in-flight work included in impact | only completed tasks offered; the running task produced pre-change output | impact list filtered on `completed` | in-flight tasks listed (labelled), their rework depends on them and runs after | `test_D3_…` | ✓ run 2: in-flight task listed, rework ran after it |
| **D4** | Medium | requirements model | inspect requirements after CR-001 | the original email rule marked superseded | original stays active next to the change | requirements are not granular; the objective is one blob; no supersession link | **not fixed: structural** (§H-1) | — | — |
| **D5** | Low | PM conversation | requirement change after a run completes (dry run) | delivered docs flagged, revision offered | "All upcoming work will follow it"; docs silently stale | no terminal-run branch | deliverables marked stale; reply explains how to revise | `test_D5_…` | automated only (no paid rerun needed) |

Test results after fixes: backend **61 passed** (+4 regression tests), frontend unit **12 passed**,
Playwright UI e2e **2 passed**, real-provider journey **passed** (run 2).

Observations, not counted as defects:
- In run 1, QA passed after one call with 0 findings while D1's misattributed report existed. The QA agent
  must not be the sole source of truth, which is why the deterministic checklist exists.
- The office keeps showing an agent's last task title after completion ("Completed — Consolidate final
  delivery"). That is accurate, but could be read as current work.

## H. Architectural recommendations (ranked)

1. **Granular, versioned requirements with explicit supersession** (fixes D4; most important). Split
   the brief into individual requirement items at intake. A change request references the items it
   replaces (proposed by the PM, confirmed by the client), marking them `superseded_by`. Agents then see
   only current rules instead of reconciling contradictions. This is a schema and UI change, so I have not
   done it without your approval.
2. **Task ↔ requirement traceability.** The planner tags each task with the requirement IDs it implements.
   Impact analysis can then *propose* exactly the affected tasks, instead of listing all completed and
   in-flight work for the client to choose from. This is what makes targeted rework scale beyond small projects.
3. **Stale-input enforcement.** When a requirement changes, mark derived artifacts stale until a new
   version exists, and have consolidation refuse stale inputs. That turns "no stale artifact reached
   delivery" from observed into guaranteed.
4. **Deterministic acceptance checks inside QA.** Generate a checklist from the approved acceptance
   criteria and run it alongside the QA agent's opinion, as this report did externally.

Items 1-3 build on existing tables (`project_requirements`, `tasks`, `artifacts`) and need one migration;
no framework change.

## I. Final recommendation

**Yes, AgentOffice is ready for you to test personally**, with these caveats:
- **Change requests work.** Expect the impact card to list every completed or in-progress task. Until
  recommendation 1 is built, the original requirement text remains visible next to the change.
- **Only OpenAI is verified.** Anthropic models have not been exercised against the live API.
- **Gate releases on the deterministic checks.** QA is a review opinion. The checklist script in
  `frontend/e2e/acceptance/` can be rerun on any project's evidence.

Nothing blocks personal testing. The decision that needs you is whether to implement recommendation 1
(requirement versioning), because it changes the data model.
