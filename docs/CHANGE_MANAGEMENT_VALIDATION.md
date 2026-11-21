# AgentOffice: change-management improvements and multi-agent efficiency validation

Date: 2026-11-21 · Scope: task-to-requirement traceability, stale-artifact enforcement, real-provider
re-validation of a mid-project requirement change, and a single-agent vs multi-agent comparison.
Provider: OpenAI **gpt-5.4** for every agent in both configurations (same model and effort, for fairness).
Real spend for this assignment: **$0.6532 estimated** (authorized: $1.00).

## Executive summary

**Can AgentOffice now identify affected tasks automatically when requirements change?**
**Yes.** It uses evidence, not a blanket list. Each task records the requirement IDs it implements, and
each artifact version records its requirements and the exact input versions it was derived from. When
a requirement is superseded, impact is computed from:
- direct links;
- task dependencies;
- recorded artifact consumption.

Each affected task gets an action: rework, rework after it finishes (in flight), relink (not started),
wait for upstream rework, or preserve. Tasks with no recorded links are flagged as uncertain for client
confirmation, never silently omitted.

In the real run, the PM proposed superseding exactly R-009 (the email rule). The analysis identified the
completed PRD task (direct) and the in-flight technical assessment (rework after it finished), and the
lineage confirms the in-flight output (v1, implements R-009) was superseded by a rework version (v2,
implements R-020). Preservation of unrelated work is proven by automated tests. It was not visible in the
real run, because the PM linked both of its tasks to the changed rule (see risk 1).

**Can it guarantee that stale artifacts are blocked from final delivery?**
**Yes, for staleness caused by superseded requirements, deterministically and without any model.**
- **Before QA and consolidation, and again before finalizing,** a lineage-based gate blocks delivery
  while any deliverable implements a superseded requirement, derives from a stale input, or has no
  links and predates the change.
- **It explains each blocker** and offers targeted rework, explicit client confirmation, or cancellation.
- **Stale versions are kept** for audit.

The guarantee is bounded:
- a change that only **adds** a rule supersedes nothing, so lineage cannot prove staleness; affected work
  is surfaced to the client as uncertain instead;
- the guarantee is only as precise as the PM's task-requirement links.

**Does the multi-agent configuration outperform a single agent on this task?**
**On quality, yes, in this one-sample comparison. On cost and speed, no.**
- **Blind rubric review (AI evaluator, blinded):** multi 29/35 vs single 19/35, high confidence.
- **Deterministic checks:** 16/16 vs 14/16.
- **QA value:** the multi-agent QA reviewer found 3 real major defects, all resolved. One was a
  cross-document phone-rule contradiction (10–15 vs 7–15 digits) that the multi-agent split itself
  introduced.
- **Single-agent weaknesses:** its package leaves email and phone formats undefined, and contains a
  statement contradicting the email-OR-phone rule.
- **Cost of quality:** multi-agent cost **3.6×** as much ($0.51 vs $0.14), used **4.1×** the calls and
  **2.7×** the execution time.

**Is any additional architectural modification necessary before broader testing?**
**No blocking modification.** Two non-blocking changes are recommended:
1. A smarter budget-reservation policy. Worst-case reservations stopped the multi-agent run twice, well
   below real spend.
2. Tighter PM requirement linking. Broad links limit how much work can be preserved.

## 1. Architecture changes implemented

| Component | Change |
|---|---|
| `app/traceability.py` (new) | Task-requirement links, lineage snapshots, deterministic `Freshness` evaluator, evidence-based `impact()`, `artifacts_at_risk()`, `delivery_blockers()` |
| Planner | Plan tasks **must** carry `requirement_refs`; refs are validated (unknown → error, superseded → error, so the PM corrects them); links are created on approval; the SOW table shows "Implements" |
| Runner / tools | The execution records the input versions its context was built from; `read_artifact` records the exact version read; `write_artifact` snapshots lineage; subtasks inherit links |
| Change flow | The proposal is computed per candidate requirement; the decision relinks not-started tasks, creates targeted reworks (in-flight ones after they finish), and orders downstream tasks and reworks after upstream reworks |
| Run flow / graph | Stage-aware **delivery gate** at the review gate (pre) and at finalize; new `stale_artifacts` decision (rework / confirm / cancel); graph routes "blocked" to settle |
| Context | Agents see `⚠ STALE: <reason>` on any stale input; active requirements only (from D4) |
| UI | Evidence-based change card (reasons, pre-selection that follows supersession choices, uncertain flags, kept tasks, artifacts at risk); "Delivery blocked" card; requirement refs on plan, tasks and versions; lineage ("Implements … · derived from …") in the deliverable viewer |

There is still one orchestration engine (LangGraph + DB task table), one database and one event stream.
No new agents or services were added.

## 2. Database changes (migration `0003`, backward compatible)

- **New `task_requirements`** (task_id, requirement_id, source, active, created_at, deactivated_at).
  Links are **deactivated, never deleted**.
- **`artifact_versions.requirement_ids`, `artifact_versions.input_version_ids`:** an immutable lineage
  snapshot per version.
- **`task_executions.input_version_ids`:** what the execution actually consumed.
- **`artifacts.stale_reason`** (`[lineage] …` computed, or `[note] …` from client actions) and
  **`artifacts.confirmed_version`** (explicit client confirmation).

Existing projects need no backfill. Legacy versions have empty lineage, so they only become "uncertain"
if a requirement is later superseded in that project.

## 3. Traceability, as implemented

1. **Superseded IDs:** the client confirms them on the change card (PM proposal, keyword fallback).
2. **Linked tasks:** active `task_requirements` rows matching the superseded IDs.
3. **Dependent tasks and artifacts:** a transitive closure over `task_dependencies` plus recorded
   consumption (which tasks' executions read which task's artifact versions). Artifacts at risk come
   from a "what-if" freshness evaluation.
4. **Targeted proposal**, per task:

   | Task state | Directly linked | Downstream of an affected task |
   |---|---|---|
   | Completed | rework | rework |
   | In flight | rework after it finishes | rework after it finishes |
   | Not started | relink | wait for the upstream rework |
   | Not started, both | relink and wait | relink and wait |

   Untraced tasks are marked *uncertain/confirm*; unrelated tasks are *preserve*.
5. **Explanation:** each task's reason (e.g. "implements R-009", "uses output of “…”"), the artifacts
   that would become stale, and the kept tasks.
6. **Approval** is required before the plan changes.
7. **Unaffected completed work** is left untouched, with no new versions.

## 4. Stale-artifact enforcement

Freshness is a pure function of the lineage plus the requirement records:
- **stale:** the version implements a superseded requirement;
- **stale:** the version derives from a stale input version. Documents a task was *asked to revise* are
  revision sources, not derivation;
- **uncertain:** the version has no requirement links and predates the latest supersession;
- **current:** the client explicitly confirmed this version.

**At the delivery gate:**
- **Pre-stage** (before QA/consolidation): all deliverables except consolidation outputs, which are
  about to be regenerated.
- **Final:** everything. An earlier run's consolidated deliverable is historical once this run has
  produced its own.

Blocked delivery creates a client decision that lists every blocker and its reason.

**Rework and history:**
- A rework writes a **new version** with current lineage. Old versions are never deleted.
- Identical content re-written by a newer task gets a new version, so lineage reflects the current baseline.

## 5. Automated test results (2026-11-21)

| Suite | Result |
|---|---|
| Backend (`pytest`, real PostgreSQL 16, real Docker sandbox, scripted/fake providers) | **71 passed** (+7 traceability/staleness/budget tests this round) |
| Frontend unit (`vitest`) | **15 passed** (+2: evidence-based card follows supersession choice; delivery-blocked card) |
| Playwright UI e2e (scripted provider, isolated server) | **2 passed** |
| Free dry runs of the paid journey (scripted, both configurations) | passed |

New regression tests:
- `test_plan_tasks_must_cite_valid_requirements`
- `test_impact_is_evidence_based_and_preserves_unrelated_work`
- `test_stale_deliverable_blocks_delivery_until_confirmed`
- `test_untraced_work_is_flagged_uncertain_and_client_can_confirm`
- `test_relinked_task_keeps_link_history`
- `test_D6_budget_block_separates_actual_spend_from_reservations`
- updated D4 tests

## 6. Real-provider evidence

Evidence is under [docs/change-validation/](change-validation/): `evidence.json`, `artifacts/` (every
version), `export.zip`, `screens/` and `checklist.json` per segment.
- **Initial requirement:** "Every imported customer contact must have a valid email address."
- **Change:** "Contacts may be imported if they have either a valid email address or a valid phone number."

| Check | Multi-agent | Single-agent |
|---|---|---|
| Original requirement superseded | ✓ R-009 → R-020 (PM proposal, 1 call, $0.0033) | ✓ R-009 → R-019 (PM proposal, 1 call, $0.0028) |
| Affected tasks identified automatically | ✓ the PRD task (completed, *direct*) and the technical assessment (in flight, *rework after*) | n/a: the run had already finished; documents were marked stale and a revision run reworked them |
| In-progress task handled safely | ✓ tech doc v1 implements R-009 (pre-change); rework v2 implements R-020 and derives from PRD v2 | n/a |
| Unrelated work preserved | not exercised: the PM linked both tasks to R-009 | n/a (single task) |
| Only necessary tasks reworked | ✓ 2 change reworks (both genuinely affected); 3 further reworks came from QA findings, not the change | 1 revision task |
| Stale artifacts excluded from delivery | ✓ final stale deliverables: none; nothing stale reached the gate | ✓ final: none (run-1 docs superseded by revision v2) |
| Consistent final documentation | ✓ 16/16 deterministic checks | 14/16 (no open questions; no QA report, since there is no QA role) |
| Calls and spend recorded | ✓ 33 calls, $0.5118 | ✓ 8 calls, $0.1414 |

**Interruptions in the multi-agent run** (all handled through the UI):
1. **First stop, at $0.24 actual spend:** worst-case reservations for two concurrent QA reworks
   (16,000-token output allowance × $15/Mtok ≈ $0.24 per call) blocked further calls (defect D6). My
   script then chose "Stop spending", which failed one task by design. I lowered every agent's output
   allowance to 6,000 tokens in **both** projects, a per-agent setting, and retried.
2. **Second stop, at $0.45 actual spend** (genuine). I raised that project's budget to $0.75. The hard
   caps then bounded total spend at $0.75 + $0.14 = $0.89, keeping it within the $1 authorization.

## 7. Single-agent vs multi-agent comparison

**Setup:** an identical brief and change, the same reference material (none), the same tools, and the
same model (gpt-5.4, low effort, 6,000-token output allowance after adjustment). Both ran through
AgentOffice's UI.
- **Single-agent:** one agent (the PM role) plans, writes and consolidates; with no QA role, there is no
  QA gate.
- **Multi-agent:** PM, Business Analyst, Technical Reviewer and QA Reviewer.

| Metric | Single agent | Multi-agent | Source |
|---|---|---|---|
| Deliverable completeness (deterministic) | 14/16 checks | **16/16** | `check_deliverables.py` |
| Requirements consistency (deterministic: no email-mandatory claim) | pass | pass | checklist |
| Requirements consistency (blind review, criterion 3) | 2/5: contradicts the rule in AC-4 / column list | **4/5** | blind evaluator, verified in the file (line 119) |
| Acceptance-criteria quality (blind, criterion 4) | 2/5: formats undefined, not testable | **4/5**: concrete phone rule with boundary examples | blind evaluator |
| Defects found | 4 major + 7 minor by the blind reviewer; 0 found internally (no QA) | 9 minor by the blind reviewer; **3 major found and fixed by its own QA** | evaluator / QA findings |
| Blind rubric total | 19/35 | **29/35** (high confidence) | blind evaluator |
| Model calls | **8** | 33 | usage records |
| Input / output tokens | **16,797 / 6,582** | 84,627 / 18,824 | usage records |
| Estimated API cost | **$0.1414** | $0.5118 | usage records |
| Execution time (excluding time waiting on client decisions) | **69 s** | 187 s | event log |
| Human interventions | 5: approve plan, submit change, confirm impact, request revision, approve revision plan | 5: approve plan, submit change, confirm impact, 2× retry after budget stops | evidence |
| Cost of handling the change | **≈ $0.083**: 1 impact call + revision run (plan + 1 task, whole document rewritten) | ≈ $0.110: 1 impact call + 2 targeted reworks (5 calls); the QA cycles that followed ($0.24) also re-verified the change | per-task usage |

**Interpretation.** The independent QA loop is where the multi-agent value came from. It turned an
ambiguous phone rule into a testable one and caught a cross-document contradiction. But splitting the
work across agents also *created* that contradiction, and multi-agent paid 3.6× for the improvement.

For a small, single-document task, a single agent was cheaper and faster, and good enough to build
from. Its output still needed clarification on formats, and it contained one rule contradiction that
nothing in its configuration checked.

**Caveats:**
- **n = 1 per configuration.** Model variance is real; treat these results as indicative, not conclusive.
- **The change arrived at different points.** The single agent finished in about 30 s, so its change
  arrived after completion and was handled by a revision run. The multi-agent change arrived mid-run.
- **A true single-agent "self-review" is not a distinct AgentOffice step.** The QA gate requires a QA
  Reviewer role. I reported this limitation rather than changing the product for the benchmark.
- **The blind evaluator was an AI (Claude) sub-agent** given only the two scrubbed packages, the brief
  and a fixed rubric, and the mapping was sealed. Package size (one document vs three) may have hinted
  at the configuration. QA reports and system-generated summaries were excluded from both packages,
  because they reveal the configuration.

## 8. Costs, tokens and time

| Segment | Calls | Tokens in / out | Est. cost |
|---|---|---|---|
| Multi-agent, all segments | 33 | 84,627 / 18,824 | $0.5118 |
| Single-agent, all segments | 8 | 16,797 / 6,582 | $0.1414 |
| **Total paid (this assignment)** | **41** | **101,424 / 25,406** | **$0.6532** |
| Dry runs (scripted provider) | — | — | $0 |

These are estimates from the configured OpenAI standard prices (gpt-5.4 $2.50 / $15.00 per Mtok).
Provider billing is authoritative.

## 9. Defects discovered and fixed

**From real-provider execution:**
- **D6 (Medium): budget reservations far above real spend.**
  - **Problem:** reservations use each call's worst case (the full output allowance), so with
    expensive models and concurrency the budget blocks at a fraction of real spend.
  - **Fixed:** the explanation now separates spend, in-flight reservations and the next call's worst
    case (`test_D6_…`).
  - **Not changed:** the reservation policy itself, which guarantees the cap (risk 4).

**Found by the new regression tests during development** (fixed before any paid run):

| ID | Defect |
|---|---|
| D7 | The additive-change reply wrongly said tasks "have no requirement links" |
| D8 | The impact list was computed across *all* candidate requirements, so unrelated tasks were proposed for rework |
| D9 | In revision runs, documents given to a task to revise were treated as derivation inputs, marking unrelated work stale |
| D10 | A rework's own revision source made its output "derived from stale input", so a rework could never be fresh |
| D11 | A not-started task that was both directly linked and downstream was relinked but not held back, so it consumed a stale input |
| D12 | Blanket "predates the change" notes kept blocking unrelated deliverables after the client decided the change |
| D13 | A previous run's consolidated deliverable blocked a revision run and could not be reworked (fixed with a stage-aware gate) |
| D14 | Identical content re-written by a newer task kept the old version's stale lineage |

## 10. Remaining architectural risks

1. **Link precision depends on the PM.** In the real run, gpt-5.4 linked each task to 12 requirement
   items, so a one-rule change invalidated everything. Linking is validated, not minimized. Possible
   next steps: a planner instruction plus a warning when a task links most of the baseline, or
   per-deliverable-section granularity.
2. **Artifact-level granularity.** Lineage is per document, not per section; a change to one rule
   reworks the whole document.
3. **Additive changes** cannot be proven stale (nothing is superseded). They are surfaced to the client
   as uncertain, which is correct but needs human judgement.
4. **Budget reservations are conservative.** The worst-case policy guarantees caps but blocks early with
   expensive models and parallel agents. Options: size the per-agent output allowance by role, or
   estimate from observed output with an explicit "may exceed by ≤ one call" setting.
5. **Deterministic checks are keyword-based.** They missed the single-agent package's contradictory
   acceptance criterion, which the blind review caught. They are necessary, not sufficient.
6. **No single-agent self-review step.** A configuration without a QA Reviewer gets no independent review.
