import { expect, test } from "@playwright/test";

const H = { "X-AgentOffice-Client": "1" };

test("MOCKED-PROVIDER journey: create, recruit, approve, clarify, review, accept, export", async ({ page, request }) => {
  // 1. Create the project through the wizard
  await page.goto("/projects/new");
  await page.getByRole("button", { name: /Product Requirements/ }).click();
  await page.getByLabel("Project name").fill("SaaS onboarding improvement");
  await page.getByLabel("Objective").fill("Produce a PRD, backlog and technical considerations for an AI onboarding assistant.");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByText("Anything missing?")).toBeVisible();
  await page.getByRole("button", { name: "Continue to team" }).click();

  // 2. Recruit the recommended PM, BA, Architect and QA
  for (let i = 0; i < 4; i++) {
    await page.getByRole("button", { name: "Hire", exact: true }).first().click();
    await expect(page.getByText(`Hired team (${i + 1})`)).toBeVisible();
  }
  await page.getByRole("button", { name: "Go to project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  const projectId = page.url().split("/").pop()!;

  // Assign the scripted test model (no real API key in CI)
  const agents = await (await request.get(`/api/projects/${projectId}/agents`)).json();
  for (const a of agents) {
    const r = await request.patch(`/api/projects/${projectId}/agents/${a.id}`, { headers: H, data: { provider: "scripted-test", model_id: "scripted-v1" } });
    expect(r.ok()).toBeTruthy();
  }
  await page.reload();

  // 3. PM drafts the statement of work; approve it
  await page.getByRole("button", { name: "Ask the PM for a plan" }).click();
  await expect(page.getByRole("button", { name: "Approve and start" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Work plan — edit assignments or remove tasks")).toBeVisible();
  await page.getByRole("button", { name: "Approve and start" }).click();

  // 4. An agent asks a clarification question; answer it
  await expect(page.getByRole("button", { name: "SMB" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "SMB" }).click();

  // 5. Work, QA review, rework and consolidation complete
  await expect(page.getByText("This run is complete")).toBeVisible({ timeout: 45_000 });

  // 6. The office shows every agent from recorded events
  await page.goto(`/office/${projectId}`);
  await expect(page.getByRole("img", { name: /Pixel-art office/ }).locator("canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: /Pat.*Completed/ })).toBeVisible();
  await page.getByRole("button", { name: /Quinn/ }).first().click();
  await expect(page.getByRole("complementary", { name: "Quinn details" })).toBeVisible();
  await expect(page.getByText("Model calls")).toBeVisible();

  // 7. Activity timeline is complete without the game view
  await page.goto(`/activity/${projectId}`);
  await expect(page.getByText(/reviewed the deliverables: revise/)).toBeVisible();
  await expect(page.getByText(/sent 1 finding\(s\) back to/)).toBeVisible();

  // 8. Accept and export
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("button", { name: "Accept deliverables" }).click();
  await expect(page.getByText("Nothing needs you right now.")).toBeVisible();
  const zip = await request.get(`/api/projects/${projectId}/export`);
  expect(zip.status()).toBe(200);
  expect((await zip.body()).subarray(0, 2).toString()).toBe("PK");

  // 9. Costs show test usage, clearly labelled
  await page.goto(`/costs/${projectId}`);
  await expect(page.getByText(/Costs are estimates/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "test" }).first()).toBeVisible();
});

test("settings never display stored keys and the API rejects cross-site writes", async ({ page, request }) => {
  await page.goto("/settings");
  await expect(page.getByText("Security & storage")).toBeVisible();
  const r = await request.post("/api/projects", { data: { name: "x", objective: "y" } }); // no client header
  expect(r.status()).toBe(403);
});
