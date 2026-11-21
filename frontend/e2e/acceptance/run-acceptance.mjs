// AgentOffice autonomous acceptance journey (CSV Import Assistant + CR-001).
//
// Drives the REAL user interface with Playwright for every client action. The backend API is
// read only to collect evidence and to know *when* to act (e.g. "the BA finished its draft").
// Usage:
//   BASE_URL=http://127.0.0.1:8765 PROVIDER=openai MODEL=gpt-5.4-mini PM_MODEL=gpt-5.4 \
//   OUT=../docs/acceptance node e2e/acceptance/run-acceptance.mjs
// PROVIDER=scripted-test runs a free dry run against the isolated test server.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8765";
const PROVIDER = process.env.PROVIDER ?? "openai";
const MODEL = process.env.MODEL ?? "gpt-5.4-mini";
const PM_MODEL = process.env.PM_MODEL ?? MODEL;
const BUDGET = process.env.BUDGET ?? "2";
const MAX_CALLS = process.env.MAX_CALLS ?? "60";
const OUT = path.resolve(process.env.OUT ?? "../docs/acceptance");
const DEADLINE_MS = Number(process.env.DEADLINE_MS ?? 25 * 60_000);
const TEAM = process.env.TEAM ?? "multi"; // multi | single
const EMAIL_RULE = process.env.EMAIL_RULE ?? "Every contact must have a valid email address. Rows with missing or invalid email addresses must be rejected.";
const RESUME_PID = process.env.RESUME_PID ?? "";   // continue an existing project instead of creating one
const REVISION_TEXT = process.env.REVISION_TEXT ?? ""; // request a revision run on the acceptance card
const SHOTS = path.join(OUT, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const log = [];
const t0 = Date.now();
const note = (step, ok, detail = "") => {
  const e = { t: ((Date.now() - t0) / 1000).toFixed(1), step, ok, detail };
  log.push(e);
  console.log(`[${e.t}s] ${ok === true ? "PASS" : ok === false ? "FAIL" : "INFO"} ${step}${detail ? " — " + detail : ""}`);
};
// The local API token (data/api-token) is read from disk and never printed or saved.
const TOKEN = process.env.AGENTOFFICE_API_TOKEN
  ?? fs.readFileSync(new URL("../../../data/api-token", import.meta.url), "utf8").trim();
const api = async (p) => {
  const r = await fetch(`${BASE}/api${p}`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  if (!r.ok) throw new Error(`${p}: ${r.status} ${await r.text()}`);
  return r.json();
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let shotN = 0;
const shot = async (page, name) => {
  const f = path.join(SHOTS, `${String(++shotN).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: f, fullPage: false });
  return path.relative(OUT, f);
};

// Simulated client answers (synthetic, consistent with the brief).
function clientAnswer(q) {
  const s = q.toLowerCase();
  if (s.includes("duplicate")) return "Treat rows as duplicates when the email matches case-insensitively; if a row has no email, match on the normalized phone number. Keep the first occurrence and flag the others.";
  if (/(size|limit|how many|rows|large|volume)/.test(s)) return "Assume files up to 5 MB or 10,000 rows.";
  if (/(column|field|header|required)/.test(s)) return "Columns: first_name, last_name, email, phone, company. first_name and last_name are required; company is optional.";
  if (/(phone|format)/.test(s)) return "Accept phone numbers in E.164 or common national formats; normalize to E.164.";
  if (/(partial|invalid rows|skip)/.test(s)) return "Administrators can import the valid rows and skip invalid ones; invalid rows are listed in the summary.";
  if (/(metric|success|measure)/.test(s)) return "Success = fewer invalid contacts imported and fewer support tickets about failed imports.";
  return "Use sensible defaults for a small B2B SaaS product and state them as assumptions.";
}

const OBJECTIVE = `A small B2B SaaS platform lets administrators upload CSV files containing customer contacts. They need a preview-and-validation workflow before importing contacts, to prevent invalid records from entering the customer database and to explain validation errors clearly.

The CSV import feature must:
1. Allow administrators to upload a CSV file.
2. Display a preview of the imported records.
3. Validate required fields.
4. Identify duplicate contacts within the uploaded file.
5. Display row-specific validation errors.
6. Allow administrators to confirm valid records before import.
7. Provide an import summary.

${EMAIL_RULE}`;
const DELIVERABLES = ["Concise Product Requirements Document", "Prioritized user stories", "Testable acceptance criteria",
  "Technical feasibility and risk assessment", "QA review report", "Final consolidated project deliverable"].join("\n");
const CONSTRAINTS = "Out of scope: production database integration, real customer information, authentication, external SaaS integrations, deployment, a complete CRM. Keep each document concise (under ~900 words).";
const SUCCESS = "An engineering team could build and test the CSV import workflow from these documents without further clarification.";
const CR = process.env.CR_TEXT ?? "Update the CSV validation requirements. A customer contact may now be imported without an email address if a valid phone number is provided. Reject a row only if both contact methods are absent or invalid. Update the affected requirements, user stories, acceptance criteria, and QA tests.";

const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1366, height: 900 }, acceptDownloads: true });
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
const evidence = { config: { BASE, PROVIDER, MODEL, PM_MODEL, BUDGET, MAX_CALLS, TEAM, EMAIL_RULE, CR }, log, qa: [], cr: {}, refresh: [],
  timing: {}, interventions: [], screens: {} };
let pid = null;

try {
  // 1-2. Launch + health
  const h = await api("/health");
  await page.goto(`${BASE}/api/auth/session?token=${encodeURIComponent(TOKEN)}`);
  await page.getByRole("heading", { name: "Your consulting office" }).waitFor();
  note("1-2 app launched; frontend and backend healthy", h.ok === true, `${BASE}`);
  const boot = await api("/bootstrap");
  const prov = boot.providers.find((p) => p.provider === PROVIDER);
  note("provider connection available", prov?.status === "valid", `${PROVIDER}: ${prov?.status} (${prov?.storage_backend ?? "n/a"})`);
  if (prov?.status !== "valid") throw new Error("provider not valid");
  if (PROVIDER !== "scripted-test") {
    const models = await api("/models");
    for (const m of new Set([MODEL, PM_MODEL])) {
      const mc = models.find((x) => x.provider === PROVIDER && x.model_id === m);
      const priced = mc && mc.input_price_per_mtok !== null && mc.output_price_per_mtok !== null;
      note(`budget enforcement possible for ${m}`, !!priced, priced ? `$${mc.input_price_per_mtok}/$${mc.output_price_per_mtok} per Mtok (${mc.pricing_source})` : "unpriced");
      if (!priced) throw new Error(`model ${m} unpriced: budget cannot be enforced`);
    }
  }

  let team, bea;
  if (RESUME_PID) {
    pid = RESUME_PID;
    evidence.project_id = pid;
    team = await api(`/projects/${pid}/agents`);
    evidence.team = team.map((a) => ({ name: a.display_name, role: a.role, model: `${a.provider}/${a.model_id}` }));
    evidence.timing.start = Date.now();
    note("resuming existing project", true, pid);
  } else {
  // 3-4. Create project via wizard
  await page.goto(`${BASE}/projects/new`);
  await page.getByRole("button", { name: /Product Requirements/ }).click();
  await page.getByLabel("Project name").fill("CSV Import Assistant");
  await page.getByLabel(/^Objective/).fill(OBJECTIVE);
  await page.getByLabel(/^Desired deliverables/).fill(DELIVERABLES);
  await page.getByLabel(/^Success criteria/).fill(SUCCESS);
  await page.getByLabel(/^Constraints/).fill(CONSTRAINTS);
  await page.getByLabel(/^Budget in USD/).fill(BUDGET);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByText("Reference material").first().waitFor();
  await page.getByRole("button", { name: "Continue to team" }).click();
  note("3-4 project created with requirements, exclusions and $" + BUDGET + " budget", true);

  // 5. Assemble team from recommendations
  for (let i = 0; i < (TEAM === "single" ? 1 : 4); i++) {
    await page.getByRole("button", { name: "Hire", exact: true }).first().click();
    await page.getByText(`Hired team (${i + 1})`).waitFor();
  }
  await page.getByRole("button", { name: "Go to project" }).click();
  await page.waitForURL(/\/projects\/[0-9a-f-]{36}$/);
  pid = page.url().split("/").pop();
  evidence.project_id = pid;

  // 6. Configure roles and models through the team editor dialog
  await page.getByRole("tab", { name: "Team" }).click();
  const configure = async (name, model, role) => {
    await page.locator("li", { hasText: name }).getByRole("button", { name: "Edit" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.locator("select").first().selectOption(`${PROVIDER}::${model}`);
    if (role) await dlg.getByLabel("Role").fill(role);
    await dlg.getByLabel(/^Effort/).selectOption("low");
    await dlg.getByRole("button", { name: "Save" }).click();
    await dlg.waitFor({ state: "detached" });
  };
  await configure("Pat", PM_MODEL);
  if (TEAM !== "single") {
    await configure("Bea", MODEL, "Business Analyst");
    await configure("Archie", MODEL, "Technical Reviewer");
    await configure("Quinn", MODEL);
  }
  team = await api(`/projects/${pid}/agents`);
  evidence.team = team.map((a) => ({ name: a.display_name, role: a.role, model: `${a.provider}/${a.model_id}`, orchestrator: a.is_orchestrator, tools: a.tools }));
  const okTeam = TEAM === "single" ? team.length === 1 && team[0].provider === PROVIDER
    : team.length === 4 && team.every((a) => a.provider === PROVIDER) && team.some((a) => a.role === "Technical Reviewer");
  note(`5-6 team assembled (${TEAM})`, okTeam,
    evidence.team.map((a) => `${a.name}=${a.role} [${a.model}]`).join("; "));
  evidence.screens.team = await shot(page, "team");

  // Budget controls through the UI (call cap enforced before every model call)
  await page.getByRole("tab", { name: "Budget & limits" }).click();
  await page.getByLabel(/^Project budget/).fill(BUDGET);
  await page.getByLabel(/^Max model calls per run/).fill(MAX_CALLS);
  await page.getByRole("button", { name: "Save limits" }).click();
  await page.getByText("Saved").waitFor();
  const b = await api(`/projects/${pid}/budget`);
  note("budget controls set before any model call", b.budget_usd === Number(BUDGET) && b.max_model_calls_per_run === Number(MAX_CALLS),
    `budget $${b.budget_usd}, max ${b.max_model_calls_per_run} calls/run`);

  // 7. Generate statement of work
  await page.getByRole("tab", { name: /Overview/ }).click();
  evidence.timing.start = Date.now();
  await page.getByRole("button", { name: "Ask the PM for a plan" }).click();
  await page.getByRole("button", { name: "Approve and start" }).waitFor({ timeout: 300_000 });
  const st0 = await api(`/projects/${pid}/state`);
  const sowAp = st0.pending_approvals.find((a) => a.kind === "sow");
  evidence.sow = sowAp.payload.plan;
  note("7 statement of work generated by the PM", true,
    `${evidence.sow.tasks.length} tasks; qa_review=${evidence.sow.qa_review}; questions=${(evidence.sow.clarification_questions || []).length}`);
  evidence.screens.sow = await shot(page, "sow-approval");

  // 8. Review + approve through the approval card (answer PM questions, keep QA on)
  for (const q of evidence.sow.clarification_questions || []) {
    const a = clientAnswer(q);
    await page.getByLabel(q, { exact: true }).fill(a);
    evidence.qa.push({ stage: "plan", q, a });
  }
  const qaBox = page.getByRole("checkbox", { name: /Independent QA review/ });
  if (await qaBox.isEnabled() && !(await qaBox.isChecked())) await qaBox.check();
  evidence.interventions.push("approve statement of work");
  evidence.timing.plan_ready = Date.now();
  await page.getByRole("button", { name: "Approve and start" }).click();
  await page.getByText("Nothing needs you right now.").or(page.getByText("The team is working.")).first().waitFor({ timeout: 60_000 });
  note("8 SOW approved through the approval interface (QA review on)", true);
  }

  // 9-12. Execute; act as the client when needed; introduce CR-001 after the BA's first draft
  bea = team.find((a) => a.display_name === "Bea");
  let crSent = !!RESUME_PID;
  let revisionDone = !REVISION_TEXT;
  const startRun = (await api(`/projects/${pid}/state`)).current_run?.run_number ?? 0;
  let crDecided = false;
  let officeShot = false;
  let refreshChecked = false;
  const deadline = Date.now() + DEADLINE_MS;
  while (Date.now() < deadline) {
    const st = await api(`/projects/${pid}/state`);
    const run = st.current_run;
    if (!officeShot && st.tasks.some((t) => t.status === "running")) {
      await page.goto(`${BASE}/office/${pid}`);
      await page.getByRole("img", { name: /Pixel-art office/ }).locator("canvas").waitFor();
      await sleep(1500);
      evidence.screens.office_running = await shot(page, "office-running");
      // Office vs authoritative state, then the same check after a hard refresh.
      for (const phase of ["before-refresh", "after-refresh"]) {
        if (phase === "after-refresh") { await page.reload(); await page.getByRole("img", { name: /Pixel-art office/ }).locator("canvas").waitFor(); await sleep(1500); }
        const api2 = await api(`/projects/${pid}/agents`);
        const shown = {};
        for (const a of api2) {
          const btn = page.getByRole("button", { name: new RegExp(`^${a.display_name}\\b`) }).first();
          shown[a.display_name] = { ui: (await btn.innerText()).replace(/\s+/g, " ").trim(), api: a.status };
        }
        evidence.refresh.push({ phase, shown });
      }
      officeShot = true;
      await page.goto(`${BASE}/projects/${pid}`);
    }
    // CR-001: once the BA's first work task (requirements draft) has completed
    const beaDone = st.tasks.filter((t) => (TEAM === "single" || t.assigned_agent_id === bea?.id) && t.kind === "work" && t.status === "completed");
    if (!crSent && beaDone.length) {
      evidence.timing.cr = Date.now();
      evidence.interventions.push("submit CR");
      evidence.cr.before = {
        usage: (await api(`/projects/${pid}/costs`)).records.length,
        spend: st.estimated_spend_usd,
        tasks: st.tasks.map((t) => ({ id: t.id, title: t.title, kind: t.kind, status: t.status, agent: t.assigned_agent_id })),
        artifacts: (await api(`/projects/${pid}/artifacts`)).map((a) => ({ id: a.id, name: a.name, v: a.current_version })),
      };
      await page.goto(`${BASE}/projects/${pid}`);
      await page.getByRole("tab", { name: "Talk to the PM" }).click();
      await page.getByLabel("Message type").selectOption("requirement_change");
      await page.getByLabel("Message", { exact: true }).fill(CR);
      await page.getByRole("button", { name: "Send" }).click();
      await page.locator("li", { hasText: CR.slice(0, 40) }).first().waitFor();
      await sleep(800);
      evidence.screens.cr_sent = await shot(page, "cr-001-sent");
      const msgs = await api(`/projects/${pid}/messages`);
      evidence.cr.reply = msgs.filter((m) => m.sender !== "user").pop()?.content;
      evidence.cr.sent_at_task_states = evidence.cr.before.tasks.map((t) => `${t.title} [${t.status}]`);
      note("CR-001 submitted through the PM conversation (requirement change)", true, evidence.cr.reply);
      crSent = true;
      await page.getByRole("tab", { name: /Overview/ }).click();
      continue;
    }
    // Client decisions
    for (const ap of st.pending_approvals) {
      await page.goto(`${BASE}/projects/${pid}`);
      const card = page.getByRole("article", { name: new RegExp(ap.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").slice(0, 60)) }).first();
      await card.waitFor({ timeout: 20_000 });
      if (ap.kind === "requirement_change" && !crDecided) {
        evidence.screens.cr_approval = await shot(page, "cr-001-impact-approval");
        // Impacted = every completed task listed: the BA's requirements and anything derived from them.
        const listed = ap.payload.tasks ?? [];
        evidence.cr.impact = { tasks: listed, preserved: ap.payload.preserved_tasks, at_risk: ap.payload.artifacts_at_risk,
          impact_by_candidate: ap.payload.impact_by_candidate };
        evidence.interventions.push("confirm CR impact (accepted defaults)");
        // Superseded requirements: accept the PM's pre-selected proposal as shown on the card.
        const cands = ap.payload.candidates ?? [];
        await card.getByRole("button", { name: "Apply" }).click();
        await sleep(800);
        const reqsAfter = (await api(`/projects/${pid}/state`)).requirements;
        evidence.cr.approval = { listed: listed.map((t) => `${t.title} [${t.impact}/${t.action}] ${t.reason}`),
          selected: listed.filter((t) => ["rework", "rework_after"].includes(t.action)).map((t) => t.title),
          supersession_method: ap.payload.proposal_method, supersession_rationale: ap.payload.proposal_rationale,
          proposed: cands.filter((c) => c.proposed).map((c) => `${c.ref}: ${c.text}`),
          not_proposed: cands.filter((c) => !c.proposed).map((c) => `${c.ref}: ${c.text}`),
          superseded_after: reqsAfter.filter((r) => r.superseded_by).map((r) => `${r.ref} -> ${r.superseded_by}: ${r.text}`) };
        note("CR-001 supersession confirmed", evidence.cr.approval.superseded_after.length > 0,
          `${ap.payload.proposal_method}: ${evidence.cr.approval.superseded_after.join(" | ")}`);
        note("CR impact decided in the UI (evidence-based defaults)", true,
          listed.map((t) => `${t.title}: ${t.impact}/${t.action}`).join(" | ") + ` || kept: ${(ap.payload.preserved_tasks || []).join(", ") || "-"}`);
        crDecided = true;
      } else if (ap.kind === "stale_artifacts") {
        evidence.gate = (evidence.gate || []).concat([ap.payload.artifacts]);
        evidence.screens.gate = await shot(page, "delivery-blocked");
        note("delivery gate blocked stale deliverables", null, ap.payload.artifacts.map((a) => `${a.name}: ${a.reason}`).join(" | "));
        await card.getByRole("button", { name: "Rework them" }).click();
        evidence.interventions.push("delivery gate: rework stale deliverables");
      } else if (ap.kind === "clarification") {
        const a = clientAnswer(ap.title);
        await card.getByLabel("Your answer").fill(a);
        await card.getByRole("button", { name: "Answer" }).click();
        evidence.qa.push({ stage: "execution", q: ap.title, a });
        evidence.interventions.push("answer clarification");
        note("client answered a mid-run question", true, ap.title.slice(0, 120));
      } else if (ap.kind === "tool_authorization") {
        await card.getByRole("button", { name: "Deny" }).click();
        note("tool authorization denied (not needed for this project)", null, ap.title);
      } else if (ap.kind === "budget") {
        evidence.budget_block = ap;
        note("BUDGET LIMIT reached - stopping paid execution", false, ap.explanation);
        await card.getByRole("button", { name: "Stop spending" }).click();
        throw new Error("budget limit reached");
      } else if (ap.kind === "task_failure") {
        evidence.task_failure = ap;
        const retry = process.env.RETRY_FAILED === "1";
        note(`task failure reported to client (${retry ? "retry" : "skip"})`, null, ap.explanation.slice(0, 200));
        await card.getByRole("button", { name: retry ? "Retry task" : "Skip task" }).click();
        evidence.interventions.push(retry ? "retry failed task" : "skip failed task");
      } else if (ap.kind === "sow" && RESUME_PID) {
        const plan = ap.payload.plan;
        for (const q of plan.clarification_questions || []) {
          const a = clientAnswer(q);
          await page.getByLabel(q, { exact: true }).fill(a);
          evidence.qa.push({ stage: "revision plan", q, a });
        }
        evidence.revision_plan = plan;
        await card.getByRole("button", { name: "Approve and start" }).click();
        evidence.interventions.push("approve revision plan");
        note("revision plan approved", true, `${plan.tasks.length} task(s): ${plan.tasks.map((t) => `${t.title} [${(t.requirement_refs || []).join(",")}]`).join(" | ")}`);
      } else if (ap.kind === "deliverable_acceptance" && REVISION_TEXT && !revisionDone) {
        await card.getByLabel("Revision request").fill(REVISION_TEXT);
        await card.getByRole("button", { name: "Request revision" }).click();
        evidence.interventions.push("request revision with the change");
        evidence.timing.revision_requested = Date.now();
        note("revision requested on the acceptance card", true, REVISION_TEXT);
        revisionDone = true;
      } else if (ap.kind === "deliverable_acceptance") {
        // handled after the loop
      }
      await sleep(500);
    }
    if (run && ["completed", "failed", "cancelled"].includes(run.status)) {
      if (!revisionDone) { await sleep(1500); continue; }
      if (REVISION_TEXT && run.run_number <= startRun) { await sleep(1500); continue; }
      break;
    }
    if (!refreshChecked && run?.status === "blocked") refreshChecked = true;
    await sleep(2500);
  }
  evidence.timing.end = Date.now();
  const final = await api(`/projects/${pid}/state`);
  note("9-12 execution finished", final.current_run?.status === "completed", `run status ${final.current_run?.status}`);

  // Office after completion + refresh consistency
  await page.goto(`${BASE}/office/${pid}`);
  await page.getByRole("img", { name: /Pixel-art office/ }).locator("canvas").waitFor();
  await sleep(4000);
  evidence.screens.office_done = await shot(page, "office-completed");
  await page.goto(`${BASE}/activity/${pid}`);
  await page.getByRole("heading", { name: "Activity" }).waitFor();
  evidence.screens.activity = await shot(page, "activity");

  // 13. Export through the Deliverables page
  await page.goto(`${BASE}/deliverables/${pid}`);
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Export all (.zip)" }).click()]);
  const zipPath = path.join(OUT, "export.zip");
  await dl.saveAs(zipPath);
  note("13 deliverables exported via the UI", fs.statSync(zipPath).size > 0, `${fs.statSync(zipPath).size} bytes`);
  evidence.screens.deliverables = await shot(page, "deliverables");
  await page.goto(`${BASE}/costs/${pid}`);
  await page.getByRole("heading", { name: "Costs" }).waitFor();
  evidence.screens.costs = await shot(page, "costs");
} catch (e) {
  note("journey aborted", false, String(e?.message ?? e).slice(0, 500));
  try { await shot(page, "failure"); } catch { /* ignore */ }
} finally {
  if (pid) {
    for (const [k, p] of Object.entries({ state: `/projects/${pid}/state`, events: `/projects/${pid}/events?limit=1000`,
      handoffs: `/projects/${pid}/handoffs`, costs: `/projects/${pid}/costs`, findings: `/projects/${pid}/findings`,
      messages: `/projects/${pid}/messages`, artifacts: `/projects/${pid}/artifacts`, approvals: `/projects/${pid}/approvals` })) {
      try { evidence[k] = await api(p); } catch (e) { evidence[k] = String(e); }
    }
    const docs = path.join(OUT, "artifacts");
    fs.mkdirSync(docs, { recursive: true });
    evidence.artifact_versions = [];
    for (const a of Array.isArray(evidence.artifacts) ? evidence.artifacts : []) {
      const full = await api(`/artifacts/${a.id}`);
      for (const v of full.versions) {
        const c = await api(`/artifacts/${a.id}?version=${v.version}`);
        const fname = `${a.name.replace(/[^A-Za-z0-9._-]+/g, "_")}.v${v.version}.${a.artifact_type === "json" ? "json" : "md"}`;
        fs.writeFileSync(path.join(docs, fname), c.content);
        evidence.artifact_versions.push({ id: a.id, name: a.name, version: v.version, category: a.category, file: `artifacts/${fname}`,
          owner: a.owner_agent_id, created_at: v.created_at, by_task: full.versions.find((x) => x.version === v.version)?.created_by_task_id });
      }
    }
  }
  evidence.console_errors = consoleErrors;
  evidence.duration_s = (Date.now() - t0) / 1000;
  fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(evidence, null, 2));
  await browser.close();
  console.log(`evidence written to ${OUT}`);
}
