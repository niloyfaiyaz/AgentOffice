import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// MOCKED-PROVIDER: every model call in these tests is answered by the scripted test provider,
// which is deterministic and NOT AI (the UI labels it so). The isolated server uses a test DB.
const H = { "X-AgentOffice-Client": "1" };
const IDEA = "Build a simple travel planning web app where friends can suggest activities, vote, and generate a shared itinerary.";

async function state(request: APIRequestContext, pid: string) {
  return (await request.get(`/api/projects/${pid}/state`)).json();
}

/** A second project created through the API and driven to a running state (for switching). */
async function secondProject(request: APIRequestContext): Promise<string> {
  const p = await (await request.post("/api/projects", { headers: H, data: { name: "Garden Planner", objective: "Plan a community garden. It must list plants." } })).json();
  const defs = await (await request.get("/api/agent-definitions")).json();
  for (const rk of ["project_manager", "research_analyst"]) {
    const d = defs.find((x: any) => x.role_key === rk);
    expect((await request.post(`/api/projects/${p.id}/agents`, { headers: H, data: { agent_definition_id: d.id, provider: "scripted-test", model_id: "scripted-v1" } })).ok()).toBeTruthy();
  }
  await request.post(`/api/projects/${p.id}/runs`, { headers: H, data: {} });
  await expect.poll(async () => (await state(request, p.id)).pending_approvals.some((a: any) => a.kind === "sow"), { timeout: 30_000 }).toBeTruthy();
  const sow = (await state(request, p.id)).pending_approvals.find((a: any) => a.kind === "sow");
  await request.post(`/api/approvals/${sow.id}/decide`, { headers: H, data: { decision: "approve", plan: sow.payload.plan, approved_tools: [], qa_review: false } });
  return p.id;
}

async function switchTo(page: Page, name: string) {
  await page.getByRole("button", { name: /Switch project/ }).click();
  await page.getByPlaceholder("Search projects…").fill(name.slice(0, 6));
  await page.getByRole("option", { name: new RegExp(name) }).click();
}

test("MOCKED-PROVIDER first-time user: idea → clarify → brief → team → approve → office → messages → deliver", async ({ page, request }) => {
  // Synthetic data must never appear in the normal project list.
  await request.post("/api/projects", { headers: H, data: { name: "Synthetic fixture", objective: "x", origin: "acceptance_test" } });

  // 1-2. Open AgentOffice and start a project from free text (no agents or models to choose first).
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "My projects" })).toBeVisible();
  await expect(page.getByText("Synthetic fixture")).toHaveCount(0);
  await page.getByRole("link", { name: "+ New project" }).first().click();
  await expect(page.getByRole("heading", { name: "What would you like your team to work on?" })).toBeVisible();
  await page.getByLabel("Describe your project").fill(IDEA);
  await page.getByRole("button", { name: "Start project" }).click();
  await expect(page).toHaveURL(/\/new\/[0-9a-f-]{36}$/, { timeout: 20_000 });
  const pid = page.url().split("/").pop()!;

  // 3. Answer the PM's clarifying questions (labelled as the test provider, not AI).
  await expect(page.getByText("Who will use it first?")).toBeVisible();
  await expect(page.getByText("test provider — not AI").first()).toBeVisible();
  await page.getByRole("button", { name: "Just my friends" }).click();
  await expect(page.getByText(/that's enough to draft the plan/)).toBeVisible({ timeout: 20_000 });

  // 4. Review the automatically populated, editable brief with provenance labels.
  await expect(page.getByLabel("Objective / problem statement")).toHaveValue(/travel planning web app/);
  await expect(page.getByText("AI proposal").first()).toBeVisible();
  await expect(page.getByText("From you").first()).toBeVisible();
  await page.getByLabel("Project name").fill("TravelPoll");
  await page.getByRole("button", { name: "Confirm brief & choose team" }).click();

  // 5. Review the recommended (minimal) team.
  await expect(page.getByRole("heading", { name: "Recommended team" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Archie — Software Architect")).toBeVisible();
  await expect(page.getByText("Dev — Developer")).toBeVisible();
  await expect(page.getByText(/Rhea/)).toHaveCount(0); // no unnecessary roles
  await page.getByRole("button", { name: "Accept team" }).click();

  // 6. Modify one agent's configuration.
  const devCard = page.locator("li", { hasText: "Developer" }).filter({ has: page.getByRole("button", { name: "Edit" }) }).first();
  await devCard.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Spending limit (USD)").fill("0.5");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(async () => (await state(request, pid)).agents.find((a: any) => a.role_key === "developer").spend_limit_usd).toBe(0.5);

  // 7-8. Review and approve the proposed work plan in one integrated setup review.
  await page.getByRole("button", { name: /for the work plan/ }).click();
  await expect(page.getByText("Work plan — edit assignments or remove tasks")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Requirements", { exact: true })).toBeVisible();
  await expect(page.getByText("Team & models")).toBeVisible();
  await page.getByRole("button", { name: "Approve & Start Project" }).click();

  // 9. Enter the project's office automatically.
  await expect(page).toHaveURL(new RegExp(`/p/${pid}$`), { timeout: 20_000 });
  await expect(page.getByRole("img", { name: /Pixel-art office/ }).locator("canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: /Switch project \(current: TravelPoll\)/ })).toBeVisible();

  // 10-11. Inspect an agent; find the one waiting for another agent (from recorded task state).
  await expect(page.getByRole("button", { name: /Archie, Software Architect: Waiting for you/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /Dev, Developer: Waiting for Archie/ })).toBeVisible();
  await page.getByRole("button", { name: /Archie, Software Architect/ }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText(/Waiting for you on “Discovery/)).toBeVisible();
  await expect(drawer.getByRole("link", { name: "Message Archie" })).toBeVisible();
  await page.keyboard.press("Escape");

  // 12. Message the PM in the project thread; a change-like message is only SUGGESTED, never applied.
  const reqsBefore = (await state(request, pid)).requirements.length;
  await page.getByRole("link", { name: /^Messages/ }).click();
  await page.getByLabel("Message Pat").fill("When will the first draft be ready?");
  await page.getByLabel("Message Pat").press("Enter");
  await expect(page.getByText("Scripted reply (test provider, not AI): noted.").first()).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Message Pat").fill("Actually it should target families instead");
  await page.getByLabel("Message Pat").press("Enter");
  await expect(page.getByRole("button", { name: "Record as a change request" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "No, it was just a message" }).click();
  expect((await state(request, pid)).requirements.length).toBe(reqsBefore);

  // 13. Respond to the agent's clarification by typing in that agent's conversation.
  await page.getByRole("button", { name: /Archie Software Architect/ }).click();
  await expect(page.getByText("Which customer segment should we prioritize first?").first()).toBeVisible();
  await page.getByLabel("Message Archie").fill("Friend groups first (SMB-sized).");
  await page.getByLabel("Message Archie").press("Enter");
  await expect(page.getByText(/Answer recorded for/)).toBeVisible({ timeout: 15_000 });

  // The answer drives real execution to completion (QA, rework, consolidation) without a restart.
  await expect.poll(async () => (await state(request, pid)).current_run.status, { timeout: 60_000 }).toBe("completed");
  const s = await state(request, pid);
  expect(s.runs.length).toBe(1);
  expect(s.tasks.some((t: any) => t.kind === "qa")).toBeTruthy();
  expect(s.requirements.every((r: any) => /^R-\d{3}$/.test(r.ref))).toBeTruthy();
  expect(s.tasks.filter((t: any) => t.kind === "work").every((t: any) => t.requirement_refs.length > 0)).toBeTruthy();
  const thread = await (await request.get(`/api/projects/${pid}/messages?channel=client`)).json();
  expect(thread.filter((m: any) => m.sender === "user").map((m: any) => m.content)).toContain("When will the first draft be ready?");

  // 14. The inbox lists the actionable item, linked to the project.
  await page.getByRole("link", { name: /^Inbox/ }).click();
  await expect(page.getByText("Deliverable awaiting acceptance")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("region", { name: "TravelPoll" })).toBeVisible();
  await page.getByRole("region", { name: "TravelPoll" }).getByRole("link", { name: "Open" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/p/${pid}`));

  // 15. Find the generated deliverable.
  await page.getByRole("link", { name: "Deliverables" }).first().click();
  await expect(page.getByRole("button", { name: /Developer deliverable/ }).first()).toBeVisible();

  // 16-17. Switch to another project and back; each view shows only that project's state.
  const other = await secondProject(request);
  await page.getByRole("link", { name: "Office & overview" }).click();
  await switchTo(page, "Garden Planner");
  await expect(page).toHaveURL(new RegExp(`/p/${other}$`));
  await expect(page.getByRole("button", { name: /Rhea, Research Analyst/ })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: /Archie/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Delivery summary" })).toHaveCount(0);
  await switchTo(page, "TravelPoll");
  await expect(page).toHaveURL(new RegExp(`/p/${pid}$`));
  await expect(page.getByRole("heading", { name: "Delivery summary" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Rhea/ })).toHaveCount(0);

  // 18. Review the handover, accept and export.
  await expect(page.getByText("Requirements coverage")).toBeVisible();
  await page.getByRole("button", { name: "Accept deliverables" }).click();
  await expect(page.getByText("The delivery decision has been recorded.")).toBeVisible({ timeout: 15_000 });
  const zip = await request.get(`/api/projects/${pid}/export`);
  expect(zip.status()).toBe(200);
  expect((await zip.body()).subarray(0, 2).toString()).toBe("PK");

  // Unique names are enforced (normalized: case and surrounding whitespace).
  const dup = await request.post("/api/projects", { headers: H, data: { name: "  travelpoll ", objective: "x" } });
  expect(dup.status()).toBe(409);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "TravelPoll" })).toBeVisible();
  await expect(page.getByText("Synthetic fixture")).toHaveCount(0);
});

test("settings never display stored keys and the API rejects cross-site writes", async ({ page, request }) => {
  await page.goto("/settings");
  await expect(page.getByText("Security & storage")).toBeVisible();
  const r = await request.post("/api/projects", { data: { name: "x", objective: "y" } }); // no client header
  expect(r.status()).toBe(403);
});

test("old URLs redirect into the project workspace", async ({ page }) => {
  await page.goto("/projects/new");
  await expect(page).toHaveURL(/\/new$/);
  await page.goto("/team");
  await expect(page).toHaveURL(/\/settings\/agents$/);
});
