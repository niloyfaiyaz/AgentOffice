# AgentOffice: engineering report

Date: 2026-11-18 · Branch: `build/agentoffice` · Rollback tag before open-source integration:
`checkpoint/pre-oss-assessment`

## 1. Implemented capabilities

- **Projects**: create, edit, rename, archive/unarchive, delete (with uploads and exports); intake gap
  check; reference files (TXT, MD, PDF, DOCX, CSV, JSON, source code) with validation and safe
  extraction; requirements on record; multiple runs per project (revisions); validated state machines.
- **Team**: built-in library of 8 roles plus custom roles; per-project copies with name, model,
  effort, job description, permissions, spending limit and call cap; saved and re-applied teams;
  recommendation by template, keyword heuristic (labelled as such) or by asking the hired PM.
- **Models and BYOK**: Anthropic and OpenAI adapters on the official SDKs; keys in the OS keychain
  (encrypted-file fallback); connection test with model discovery; independent model per agent;
  model replacement at safe checkpoints; seeded Anthropic and OpenAI prices with source and check date
  labelled (OpenAI's taken from developers.openai.com/api/docs/pricing on 2026-11-19); other discovered
  models stay unpriced until the user enters prices.
- **Orchestration**: PM statement of work (validated) with client approve/edit/revise/reject;
  dependency-aware parallel execution with a concurrency limit; structured delegation with handoffs;
  client questions; tool authorization; budget and call limits; pause/resume/cancel; bounded
  targeted retries; restart recovery; conditional QA with bounded targeted rework; PM consolidation;
  final acceptance or revision run; requirement-change, task-feedback and scope-change interventions.
- **Tools**: reference-file and deliverable reading, versioned deliverable writing (with an ownership
  guard), table analysis, delegation, client questions, sandboxed code and test execution, and
  Anthropic web search (only when permitted and approved).
- **Deliverables**: versions, owners, sources, QA findings, acceptance status, stale marking, and
  exports (MD, JSON, CSV, TXT, DOCX, ZIP with manifest), each validated before success is reported.
- **Costs**: per-call usage records (tokens, cache, web-search counts, price snapshot); breakdowns by
  agent, task and model; editable prices; estimates are labelled as estimates throughout.
- **Virtual office**: Phaser scene with original procedural pixel art; reception, workstations, meeting
  table, QA area, live status board; agent inspection with an advanced view (persisted conversation,
  structured events); handoff animation; reduced motion; keyboard-accessible team list; a full
  non-animated timeline.
- **UI sections**: Dashboard, Virtual Office, Team, Projects (with kanban), Deliverables, Activity,
  Costs, Settings; light/dark themes; layouts verified at 375 px and 1024 px with no horizontal overflow.

## 2. Architecture summary

See [ARCHITECTURE.md](ARCHITECTURE.md). There is one authoritative state (Postgres), one orchestration
engine (a LangGraph graph over a DB task table, run by a leased durable worker) and one event stream
(`agent_events` → SSE). The open-source review and the patterns adopted are in
[OPEN_SOURCE_FOUNDATION_ASSESSMENT.md](OPEN_SOURCE_FOUNDATION_ASSESSMENT.md). No third-party code
or assets were copied.

## 3. Dependency and provider requirements

Docker Desktop, Python ≥ 3.11 (developed on 3.14.6), Node ≥ 18 (developed on 26.8.2). Python and npm
packages are pinned in `backend/requirements.txt` and `frontend/package.json`/`package-lock.json`.
Real execution needs an Anthropic and/or OpenAI **API** key. Anthropic web search must be enabled for
the key's organization.

## 4. Automated test results (2026-11-18, this machine)

| Suite | Result | Provider |
|---|---|---|
| Backend unit + contract + integration (`pytest`, real PostgreSQL 16, real Docker sandbox) | **57 passed** | scripted / fake, mock HTTP for adapters |
| Real-provider journey (`tests/real`), 2026-11-19 | **1 passed** (106 s) | **real: OpenAI gpt-5.4** |
| Frontend unit (`vitest`) | **12 passed** | n/a |
| End-to-end UI (`playwright`, isolated server + test DB) | **2 passed** | scripted (not AI) |
| Migration up/down round-trip | passed (part of the backend suite) | n/a |

Commands: `./agentoffice test`, and for e2e `cd frontend && npx playwright test` (set
`PLAYWRIGHT_CHROMIUM_PATH` to reuse an installed Chromium if `npx playwright install` is unavailable).

## 5. End-to-end execution results

- **Manual browser walk-through** (built-in browser, scripted provider): wizard → recruit 4 agents →
  switch models in the edit dialog → PM plan → approve → Bea asks a question (the office shows her at the
  client desk with ✋) → answer → 6/6 tasks including QA, rework, re-review and consolidation → office
  shows every agent completed → deliverables with versions and the QA finding → export.
  Bugs found this way and fixed: duplicate desk assignment, office canvas overflow and readability,
  horizontal overflow at narrow widths, avatars announced redundantly to screen readers, test-provider
  tier label.
- **Real-provider journey: PASSED with OpenAI gpt-5.4** (key added by the user in Settings, stored in the
  macOS Keychain). Each step and its result:

  | Step | Result |
  |---|---|
  | Create SaaS onboarding project ($3 budget) | pass |
  | Hire PM, BA, Technical Architect, QA; assign gpt-5.4 | pass |
  | Provider connection | pass: 50 models visible |
  | PM statement of work | pass: 2 tasks, QA requested, **2 real clarification questions** (success metric; stack constraints) |
  | Approve SOW, answer the questions | pass: answers recorded as requirements |
  | Execution | pass: backlog (BA) and technical considerations (Architect) ran in parallel |
  | QA review of actual artifacts | pass: 8 findings, all `info` severity, so correctly no rework |
  | PM consolidation | pass: final delivery summary |
  | Export | pass: 11,173-byte ZIP with manifest |
  | Usage records | pass: 11 real calls, 30,409 input / 5,805 output tokens, **est. $0.1681** |

  Not exercised by the real run: a *mid-run* agent question (the agents did not need one; the path is
  covered by scripted tests), QA-triggered rework against a real model, and delegation by a real model.
  Two defects were found and fixed during this run: provider clients reused across event loops
  (now cached per loop), and informational QA notes counted as "unresolved findings" at acceptance
  (now reported separately).

## 6. Security verification

| Control | How verified |
|---|---|
| Keys never returned by the API or stored in the DB | `test_credentials_never_returned`; DB stores only a hint |
| Encrypted fallback cannot be read without the passphrase | `test_encrypted_credential_store` |
| Loopback-only host, CSRF header | `test_security_middleware`, Playwright security test |
| Tool permissions enforced server-side | `test_unauthorized_tool_fails_safely` |
| Consequential tools need client authorization | `test_consequential_tool_requires_approval` |
| Sandbox isolation | `test_sandboxed_execution_is_isolated` ran real code in Docker: network blocked, root read-only, uid 10001, no host secrets in env |
| Untrusted-document envelope cannot be closed early | `test_untrusted_envelope_cannot_be_escaped` |
| Secret redaction in events | `test_redaction` |
| Deliverable ownership guard | `test_artifact_ownership_guard_and_agent_memory` |

## 7. Known defects and limitations

- On narrow screens the office canvas scales down; names stay legible but small below ~900 px.
- The encrypted-file credential fallback needs `AGENTOFFICE_CREDENTIAL_PASSPHRASE` in the environment of
  both server and worker; it cannot be unlocked from the UI.
- Web research is Anthropic-only (provider-hosted search); there is no OpenAI search integration.
- PDF extraction is text-only: scanned PDFs are reported as empty, not OCR'd.
- Usage costs are estimates from configured prices; provider invoices are authoritative.
- Playwright 1.49's own Chromium download stalled on this machine; tests ran against an existing
  Chromium build via `PLAYWRIGHT_CHROMIUM_PATH`.

## 8. Unverified functionality (needs a real provider)

OpenAI (gpt-5.4) is verified end to end with real calls (§5). Still verified only with scripted/fake
providers and mock-HTTP contract tests:
- **all live Anthropic calls** (no Anthropic key was provided);
- mid-run clarification asked by a real agent (QA-triggered rework, requirement-change rework and delegation
  are now verified with real OpenAI models; see [AGENTOFFICE_E2E_ACCEPTANCE_REPORT.md](AGENTOFFICE_E2E_ACCEPTANCE_REPORT.md));
- the server-side refusal-fallback beta and effort parameter against the live API (graceful
  degradation on rejection is tested with mocks);
- Anthropic web search; "ask the PM to propose a team"; PM chat answers.

## 9. Run it locally

```bash
./agentoffice start      # opens http://127.0.0.1:8765
./agentoffice test       # backend + frontend unit tests
./agentoffice stop
```
