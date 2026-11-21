import { expect, test } from "@playwright/test";

// A browser without the per-install token sees the lock screen; the launcher's sign-in link
// sets the session cookie and the app loads. Uses the isolated server's TEST-ONLY token.
test("local API token: locked without sign-in, unlocked by the launcher link", async ({ browser }) => {
  const ctx = await browser.newContext({ extraHTTPHeaders: {} });
  const page = await ctx.newPage();
  await page.goto("/");
  await expect(page.getByText("AgentOffice is locked")).toBeVisible();
  expect((await page.request.get("/api/projects")).status()).toBe(401);

  await page.goto("/api/auth/session?token=e2e-test-token");
  await expect(page).toHaveURL(/127\.0\.0\.1:8799\/$/);
  await expect(page.getByText("AgentOffice is locked")).toHaveCount(0);
  const cookies = await ctx.cookies();
  const c = cookies.find((x) => x.name === "agentoffice_session")!;
  expect(c.httpOnly).toBe(true);
  expect(c.sameSite).toBe("Strict");
  expect((await page.request.get("/api/projects")).status()).toBe(200);
  await ctx.close();
});
