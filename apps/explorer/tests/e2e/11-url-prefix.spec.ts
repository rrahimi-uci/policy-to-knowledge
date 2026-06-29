/**
 * Flow 11 — URL Prefix Routing
 *
 * Verifies the /app URL prefix middleware works correctly:
 *   1. The app is served under /app/ and loads the full UI.
 *   2. Static assets (CSS, JS, favicon) load through the prefix.
 *   3. API calls (health, tasks, graph) are routed through the prefix.
 *   4. The root (/) redirects to /app/.
 *   5. The frontend fetch override correctly prefixes API calls.
 */

import { test, expect, type Page } from "@playwright/test";
import { CHAT, GRAPH } from "./helpers/selectors";

test.describe("Flow 11 — URL Prefix Routing", () => {

  /* ── Test 1: App loads under /app/ with full UI ─────────── */
  test("app loads under /app/ and renders the chat panel", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Chat input should be visible — proves index.html loaded
    await expect(page.locator(CHAT.input)).toBeVisible({ timeout: 15_000 });

    // Header title should be present (the chat/assistant panel header)
    const h1 = page.locator("header h1");
    await expect(h1).toBeVisible();
    await expect(h1).toHaveText("Assistant");

    // URL must include /app
    expect(page.url()).toContain("/app");
  });

  /* ── Test 2: Static assets load through the prefix ─────────── */
  test("static assets (CSS, JS, favicon) load through /app/", async ({ page }) => {
    // Collect network responses for key assets
    const assetResponses: { url: string; status: number }[] = [];
    page.on("response", (res) => {
      const url = res.url();
      if (
        url.includes("/js/state.js") ||
        url.includes("/css/variables.css") ||
        url.includes("logo.svg")
      ) {
        assetResponses.push({ url, status: res.status() });
      }
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // We should have captured at least state.js and variables.css
    const stateJs = assetResponses.find((r) => r.url.includes("state.js"));
    const variablesCss = assetResponses.find((r) => r.url.includes("variables.css"));

    expect(stateJs).toBeDefined();
    expect(stateJs!.status).toBe(200);
    expect(stateJs!.url).toContain("/app/");

    expect(variablesCss).toBeDefined();
    expect(variablesCss!.status).toBe(200);
    expect(variablesCss!.url).toContain("/app/");
  });

  /* ── Test 3: API health endpoint works through the prefix ──── */
  test("API health and tasks endpoints respond through /app/", async ({ request }) => {
    // Playwright's request.get with absolute paths bypasses baseURL path,
    // so we use /app/api/ explicitly to hit the prefix middleware.
    const healthResp = await request.get("/app/api/");
    expect(healthResp.status()).toBe(200);
    const healthBody = await healthResp.json();
    expect(healthBody.status).toBe("ok");

    // Tasks API should also work
    const tasksResp = await request.get("/app/api/tasks");
    expect(tasksResp.status()).toBe(200);
    const tasksBody = await tasksResp.json();
    expect(tasksBody).toHaveProperty("tasks");
    expect(Array.isArray(tasksBody.tasks)).toBe(true);
  });

  /* ── Test 4: Root (/) redirects to /app/ ────────────────── */
  test("navigating to root (/) redirects to /app/", async ({ page, baseURL }) => {
    // Derive the server origin from baseURL (e.g., "http://localhost:5001")
    const origin = new URL(baseURL ?? "http://localhost:5001").origin;

    await page.goto(origin + "/", {
      waitUntil: "networkidle",
    });

    // Should have followed the 302 redirect to /app/
    expect(page.url()).toContain("/app");

    // The page should still load correctly
    await expect(page.locator(CHAT.input)).toBeVisible({ timeout: 15_000 });
  });

  /* ── Test 5: Frontend fetch override prefixes API calls ─────── */
  test("frontend fetch override correctly routes API calls through prefix", async ({ page }) => {
    // Intercept outgoing /app/api/ calls to prove the fetch override works
    const apiCalls: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      if (url.includes("/api/")) {
        apiCalls.push(url);
      }
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Wait a moment for the health-check ping to fire
    await page.waitForTimeout(3_000);

    // The health-check ping should have gone through /app/api/
    const healthPing = apiCalls.find((u) => u.includes("/api/"));
    expect(healthPing).toBeDefined();
    expect(healthPing!).toContain("/app/api/");

    // None of the API calls should go to root /api/ without the prefix
    for (const url of apiCalls) {
      const path = new URL(url).pathname;
      expect(path.startsWith("/app/")).toBe(true);
    }
  });
});
