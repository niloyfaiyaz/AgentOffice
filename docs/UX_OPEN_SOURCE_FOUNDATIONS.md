# UX open-source foundations: assessment before the redesign

*Date: 2026-11-25. This is a research and architecture-selection document. **No redesign code has
been written yet.** The dependency decisions in §6 need the product owner's approval first.*

## 1. Method

- Each repository was shallow-cloned at the commit in §3 into an isolated scratch directory, with git
  hooks disabled and **no checkout, install, build or script execution**.
- Files were read with `git show` and `git ls-tree`: licences, `package.json` manifests, the relevant
  components and the docs.
- Maintenance signals come from the GitHub API on 2026-11-25.
- npm versions were checked against our rule that a version must be at least two weeks old.
- Our own frontend was inventoried first (§2), so every candidate is compared with what already works.
- Constraints throughout: keep the LangGraph orchestration, the PostgreSQL data model, the
  event-sourced office and the security controls. A UI library must fit them, not the other way round.

## 2. What AgentOffice already has (React 18.3, Vite 8, Tailwind 3.4, TanStack Query 5, React Router 7, Phaser 3.87)

| Redesign need | Existing component or capability | State |
|---|---|---|
| Decision and approval cards | `components/ApprovalCard.tsx` | **Strong.** It covers every decision kind: SOW editor, clarification answers, tool authorization, budget, task failure, requirement-change impact with rework cost (G1), stale-artifact gate, scope change, deliverable acceptance. Unit-tested. All of it is backed by one `ApprovalRequest` record |
| Live project state | `hooks.ts` `useProjectStream`: snapshot, then SSE from its sequence number, with React Query invalidation | **Strong.** Already the single source for every view |
| Office | `office/model.ts` (pure reducer, tested), `OfficeScene.ts` (Phaser), `sprites.ts` | **Strong.** Must stay as is |
| Agent inspection | `components/AgentPanel.tsx`, backed by `GET /agents/{id}/detail`: current task, blockers, deliverables, hand-offs, tool actions, recent events, usage; an advanced view with recorded conversation | **Good.** Needs better structure: "waiting on a teammate", dependencies, latest output, "message this agent" |
| Messaging | `ProjectDetail` › `Chat`; `POST /projects/{pid}/messages` with intents (question, requirement change, task feedback, scope change, cancel). The intent drives the structured change flow | **Basic.** One PM thread; no per-agent threads; intent is chosen manually |
| Team set-up | `components/TeamEditor.tsx`, `GET /recommendation`, `POST /recommendation/ai`, team presets, model pricing and cost tiers | **Good.** It is a configuration screen, not a recommendation review |
| Brief and intake | The `NewProject` wizard is a form-first, 3-step flow. `GET /intake-check` is a heuristic gap check. Requirements are split into R-ids | **Weakest area.** It is form-first and has no conversational discovery |
| Navigation and switching | A feature-oriented sidebar (8 sections), `ProjectPicker` and `ProjectSwitcher` (a plain `<select>`) | **Weak.** This is the main friction point the walkthrough reported |
| Primitives | `ui.tsx`: Button, Card, Badge, StatusBadge, Field, Tabs, Dialog, AvatarIcon, Empty, ErrorText | **Adequate.** The Dialog has initial focus and focus restore, but **no focus trap**. There is no popover, menu or combobox |
| Deliverables | `pages/Deliverables.tsx`: versions, lineage, QA findings, export | **Good** |

**Conclusion of the inventory:** the deep, domain-specific pieces (decisions, change management,
office, live state, deliverables) are already built and tested. The redesign mainly needs:
- **reorganisation:** project-centred routes and a workspace shell;
- **a conversational intake;**
- **a few accessible generic primitives** that we lack: popover/menu, command palette, focus-trapped
  dialog and drawer.

## 3. Comparison

| Repository @ commit (date) | Relevant capability | Licence | Compatibility with our stack | Existing AgentOffice equivalent | Integration effort | Dependencies and risks | Recommendation |
|---|---|---|---|---|---|---|---|
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) @ `4e4dd62e` (2026-11-25) | Chat primitives (Thread, Composer, Message, BranchPicker). `useExternalStoreRuntime` lets an app keep its own message store | MIT | `@assistant-ui/react` 0.15 supports React 18 and its primitives are unstyled. The styled "thread" components assume **Tailwind v4** and shadcn tokens (every workspace package pins `tailwindcss ^4.3`) | `Chat` in ProjectDetail, plus ApprovalCard for decisions | Medium. The primitives are drop-in, but our messages, approvals and intents would have to be mapped into its thread and message model. Decision cards would become "tool UI" adapters | `@assistant-ui/react` pulls in `@assistant-ui/core`, `store`, `tap`, `assistant-stream`, **`assistant-cloud`**, `zustand`, `zod`, `radix-ui`. That is a second client-side state system next to React Query, built for **token streaming**. Our discovery and messages are server-owned request/response records. The project is very active, with API churn (0.x) | **ADAPT** (patterns only): composer behaviour, message grouping, stick-to-bottom scrolling. Revisit if we add token streaming |
| [CopilotKit/CopilotKit](https://github.com/CopilotKit/CopilotKit) @ `7eaa344d` (2026-11-25) | In-app copilot chat, generative UI, agent state sharing over the AG-UI protocol | MIT | It needs a **Copilot Runtime** endpoint (`@copilotkit/runtime`, Node, GraphQL/Hono) or its Python SDK, speaking AG-UI to the agent | Our FastAPI API, SSE stream and LangGraph worker already fill this role | **High.** It would add a second agent runtime and protocol in front of LangGraph, and duplicate our event and state system | `react-core` alone pulls in `@ag-ui/*`, `rxjs`, `lit`, `katex`, `recharts`, `@scarf/scarf` (install analytics) and a websandbox. The runtime adds `@segment/analytics-node`, a licence verifier and AI SDKs. That is a telemetry and supply-chain surface we don't want in a local-first BYOK app. 492 open issues | **REJECT** |
| [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) @ `0d21f7ff` (2026-11-03) | Thread UI, an "agent inbox" for human-in-the-loop interrupts (approve, edit, reject), a tool-call table, an artifact panel | MIT | Next.js 16, React 19, Tailwind 4. Requires the **LangGraph Server API** (`@langchain/langgraph-sdk` threads and runs), which our FastAPI backend doesn't expose | ApprovalCard, which already covers approve, edit, reject and respond against our own records | High. A port across Next.js and React 19, plus a different backend protocol | **Archived** (no security fixes), 93 open issues | **REJECT** as code. Keep its interrupt-inbox and tool-call-table ideas (already noted in our 2026-11-18 assessment) |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui) @ `0e5b2e62` (2026-11-25) | A copy-in component registry on Radix (or Base UI) and Tailwind: Dialog, Sheet, Popover, Command, Sidebar, Tabs, DropdownMenu… | MIT | New projects default to Tailwind 4 and React 19. Its docs state existing Tailwind 3 / React 18 apps keep working, but current registry sources use Tailwind 4 tokens and a `cn` helper. **We would copy individual files, restyle them to our CSS variables, and not run the CLI** (it overwrites files) | `ui.tsx` primitives | Low per component. Each file is a thin styled wrapper over a Radix primitive | The wrappers bring in `radix-ui`, `cmdk` and `lucide-react`. Copy-in avoids a runtime dependency on shadcn itself. The MIT notice must be kept in copied files | **ADAPT.** Use the composition patterns (Sheet for the agent drawer, Command for the switcher) over the underlying Radix and cmdk packages, styled with our tokens. No CLI, no Tailwind 4 migration |
| [makeplane/plane](https://github.com/makeplane/plane) @ `723bb178` (2026-11-24) | A project-centred information architecture: workspace › project sidebar; "Intake" triage; workspace notifications inbox with filters and applied-filter chips; a "Power K" command palette | **AGPL-3.0-only** | React Router, MobX. A full product | Our project list, inbox counts and switcher | n/a (reference only) | AGPL: copying code would put AgentOffice's network-served code under AGPL obligations. Its MobX state model is a mismatch for us | **REJECT** as code. **ADAPT** as interaction-design reference only: project-scoped navigation, a global inbox separate from project activity, filter chips, ⌘K project switching. Nothing is copied |
| [chatwoot/chatwoot](https://github.com/chatwoot/chatwoot) @ `a9c76fa5` (2026-11-25) | A three-pane conversation inbox (list › thread › contact context), assignment, unread state | MIT ("Expat") **except `enterprise/`**, which has its own licence | Rails backend with a **Vue 3** frontend (Tailwind 3.4). No React components | Messages and Inbox | n/a (a different framework) | Mixed licence (enterprise directory); the wrong framework | **REJECT** as code. **ADAPT** the layout idea: a conversation list with an unread or needs-action marker, the thread, and a linked-record side pane |
| [chatscope/chat-ui-kit-react](https://github.com/chatscope/chat-ui-kit-react) @ `8c690cd3` (2025-05-15) | Ready-made chat widgets: MainContainer, ConversationList, MessageList, MessageInput, TypingIndicator, Avatar | MIT | Supports React 16–19. It ships **its own SCSS theme** (`@chatscope/chat-ui-kit-styles`), not Tailwind, so it would clash with our light/dark tokens | `Chat` in ProjectDetail | Low to wire up, medium to restyle | Pulls in **Font Awesome** (`@fortawesome/*`, about 4 packages) and `classnames`. Last release v2.1.1 in May 2025, roughly 18 months without a release. Its contenteditable input needs an accessibility review | **REJECT** as a dependency. Its component breakdown (ConversationList / MessageList / MessageInput / Separator) is a useful naming reference |

## 4. Small primitive libraries considered (direct reuse)

| Package | Version (≥ 2 weeks old) | Licence | Why | Cost |
|---|---|---|---|---|
| `@radix-ui/react-dialog` | 1.3.1 (2026-10-12) | MIT | A focus-trapped, accessible modal **and** side drawer (Sheet) for the agent panel and setup review edits. It replaces the internals of our hand-rolled `Dialog` | about 15 small `@radix-ui/*` packages plus `aria-hidden` and `react-remove-scroll`; no install scripts are needed (we install with `--ignore-scripts`) |
| `@radix-ui/react-popover` | 1.3.1 (2026-10-12) | MIT | Anchored, accessible popover for the project switcher and the inbox bell | Shares most of the Dialog's dependencies |
| `cmdk` | 1.1.1 (2025-03-14) | MIT | An accessible, filterable command list for **project switching** (search by name, status and action-count badges) and later ⌘K | Depends on `@radix-ui/react-dialog`, so it adds almost nothing on top of the above. Slow release cadence, but small and stable |

Not needed: the `radix-ui` umbrella package (we take only the 2 primitives), `lucide-react` (we
have few icons; Unicode or inline SVG is enough), `zustand`/`zod` on the client (React Query is the
state layer), `react-markdown` (not required by the redesign), and any chat framework.

## 5. Recommended smallest combination

**Keep (unchanged in substance):**
- ApprovalCard
- the office model, Phaser scene and sprites
- `useProjectStream` with React Query
- Deliverables
- TeamEditor
- the backend decision, message and event records
- Tailwind 3 tokens and light/dark themes

**Improve in place (our code, using external patterns):**
1. **Conversation surface,** for discovery chat, project messages and per-agent threads. About 200
   lines on our primitives, with assistant-ui-style composer behaviour: Enter to send, Shift+Enter
   for a new line, auto-grow, stick-to-bottom. Decision cards are rendered inline by embedding the
   existing ApprovalCard. One message and decision record, no copies.
2. **Project workspace shell:**
   - global navigation: Home/My Projects, Inbox, Settings;
   - project tabs: Office & Overview, Messages, Work Plan, Deliverables, Team & Costs.

   This follows Plane's project-centred IA as a design reference only.
3. **Global Inbox page:** actionable items (from `ApprovalRequest`, blocked or failed tasks and
   deliverables awaiting acceptance) separated from informational notices. This follows the Plane
   and Chatwoot inbox layout pattern.
4. **AgentPanel restructure:**
   - a Sheet drawer with identity, now-doing, waiting-on (teammate or client), dependencies, latest
     output, deliverables and cost;
   - a "Message this agent" action;
   - the advanced view kept.

**Add (direct reuse, 3 small MIT packages):** `@radix-ui/react-dialog`, `@radix-ui/react-popover`
and `cmdk`, styled with our tokens. They give a focus-trapped dialog and drawer, an accessible
popover, and a searchable project switcher. If you'd rather add **no** dependencies, the fallback is
to extend `ui.tsx` by hand: a focus trap, a listbox and a popover. That's feasible, but it's
accessibility code we would own and need to test ourselves.

**Not adopted:**
- CopilotKit: a second runtime, telemetry dependencies, duplicates LangGraph and SSE.
- assistant-ui as a dependency: a second state system built for token streaming.
- agent-chat-ui: archived; Next.js, React 19, LangGraph Server.
- Plane code: AGPL.
- Chatwoot code: Vue, plus a mixed-licence enterprise directory.
- chatscope: stale; its own SCSS and Font Awesome.
- Tailwind 4 and React 19 migrations: out of scope, with no redesign benefit.

**Licence hygiene.** If any shadcn wrapper is copied, it keeps a header comment with shadcn's MIT
notice, and `THIRD_PARTY_NOTICES.md` lists radix-ui, cmdk and any copied shadcn files. No code or
assets from Plane, Chatwoot, agent-chat-ui, CopilotKit or chatscope will be copied.

**What this does *not* change:**
- LangGraph orchestration, the worker, the PostgreSQL schema for runs, tasks and decisions,
  traceability, the budget, the Phaser office, security.

The redesign will need **backend extensions** that are independent of any UI library. They come
from the redesign brief and will be detailed for review when implementation starts:
- a discovery-conversation endpoint that uses the real configured PM model, with labelled
  assumptions;
- structured brief fields with "confirmed" versus "AI-proposed" provenance;
- a database-level unique index on normalized active project names;
- an inbox aggregation endpoint;
- marking test projects as synthetic, plus a guarded cleanup command.

## 6. Decisions for approval

1. **Add three small MIT UI primitives** (`@radix-ui/react-dialog` 1.3.1, `@radix-ui/react-popover`
   1.3.1, `cmdk` 1.1.1), styled with our existing tokens. *Recommended.* The alternative is no new
   dependencies, with hand-built accessible primitives.
2. **Don't adopt a chat or copilot framework** (assistant-ui, CopilotKit). Build the conversation
   surface on our own records. *Recommended.*
3. **Stay on Tailwind 3.4 and React 18.3** for the redesign. Copy shadcn patterns by hand rather
   than via its CLI. *Recommended.*
4. **Plane and Chatwoot are design references only,** with no code copied. *Recommended,* given
   AGPL and mixed licensing.

Once these are approved, the full UX redesign specification remains the implementation target.

## 7. Provenance

| Repository | Commit examined | Licence file read | Signals (2026-11-25) |
|---|---|---|---|
| assistant-ui/assistant-ui | `4e4dd62edf6d199486c3456b282b7c5a57adc0a1` | `LICENSE` (MIT) | 13.4k★, 40 open issues, active |
| CopilotKit/CopilotKit | `7eaa344d41963c1d61d0070c85ffa0927dda0aba` | `LICENSE` (MIT) | 39.0k★, 492 open issues, v1.90.2 (2026-11-23) |
| langchain-ai/agent-chat-ui | `0d21f7ff4c45287797e876dc6d8b150b6f277b1e` | `LICENSE` (MIT) | **archived**, 93 open issues |
| shadcn-ui/ui | `0e5b2e621a9ee4cf6a604bbe6c5c0d5b70561eb4` | `LICENSE.md` (MIT) | 129k★, shadcn@4.23.1 (2026-11-25) |
| makeplane/plane | `723bb178f97b87e80a23df9eed134eb1388d7465` | `LICENSE.txt` and `COPYRIGHT.txt` (AGPL-3.0-only) | 63.2k★, v1.5.1 (2026-11-25) |
| chatwoot/chatwoot | `a9c76fa50ff75c811d87c0a62fa1e0cfc2258b2f` | `LICENSE` (MIT except `enterprise/`) | 40.6k★, v4.20.1 (2026-11-20) |
| chatscope/chat-ui-kit-react | `8c690cd3ced687551cf9f8eb9000e0a60f302af4` | `LICENSE` (MIT) | 1.8k★, v2.1.1 (2025-05-15) |
