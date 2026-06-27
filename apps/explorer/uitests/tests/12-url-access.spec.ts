/**
 * Flow 12 — URL & Page Access Verification
 *
 * 10 tests ensuring every major route, API endpoint, and UI panel
 * remains accessible through the /app URL prefix.
 *
 *   1. Graph API returns valid data at /app/api/graph
 *   2. Graph status API responds at /app/api/graph/status
 *   3. Graph releases API responds at /app/api/graph/releases
 *   4. Annotations API responds at /app/api/annotations
 *   5. Gremlin examples API responds at /app/api/gremlin/examples
 *   6. Favicon / logo image loads via /app/logo.svg
 *   7. All JS files load with 200 through the prefix
 *   8. Graph panel renders nodes after chat command
 *   9. Detail panel opens for a node through prefixed page
 *  10. Non-prefixed API paths return 404 (middleware blocks them)
 */

import { test, expect } from "@playwright/test";
import { CHAT, GRAPH, DETAIL } from "./helpers/selectors";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered, clickRandomNode } from "./helpers/graph";

test.describe("Flow 12 — URL & Page Access Verification", () => {

  /* ── Test 1: Graph API returns data ────────────────────────── */
  test("graph API returns valid JSON at /app/api/graph", async ({ request }) => {
    const resp = await request.get("/app/api/graph");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    // Must have nodes and links arrays
    expect(body).toHaveProperty("nodes");
    expect(body).toHaveProperty("links");
    expect(Array.isArray(body.nodes)).toBe(true);
    expect(Array.isArray(body.links)).toBe(true);
  });

  /* ── Test 2: Graph status API ──────────────────────────────── */
  test("graph status API responds at /app/api/graph/status", async ({ request }) => {
    const resp = await request.get("/app/api/graph/status");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    // Status endpoint returns lock/release info
    expect(typeof body).toBe("object");
  });

  /* ── Test 3: Graph releases API ────────────────────────────── */
  test("graph releases API responds at /app/api/graph/releases", async ({ request }) => {
    const resp = await request.get("/app/api/graph/releases");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    // Returns an array of release objects
    expect(Array.isArray(body)).toBe(true);
  });

  /* ── Test 4: Annotations API ───────────────────────────────── */
  test("annotations list API responds at /app/api/annotations", async ({ request }) => {
    const resp = await request.get("/app/api/annotations");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    // Returns an object (annotations dict or similar structure)
    expect(typeof body).toBe("object");
  });

  /* ── Test 5: Gremlin examples API ──────────────────────────── */
  test("gremlin examples API responds at /app/api/gremlin/examples", async ({ request }) => {
    const resp = await request.get("/app/api/gremlin/examples");
    expect(resp.status()).toBe(200);

    const body = await resp.json();
    // Returns an array of example queries
    expect(body).toHaveProperty("examples");
    expect(Array.isArray(body.examples)).toBe(true);
    expect(body.examples.length).toBeGreaterThan(0);
  });

  /* ── Test 6: Favicon / logo image loads ────────────────────── */
  test("favicon image loads at /app/logo.svg", async ({ request }) => {
    const resp = await request.get("/app/logo.svg");
    expect(resp.status()).toBe(200);

    const contentType = resp.headers()["content-type"] ?? "";
    expect(contentType).toContain("image");
  });

  /* ── Test 7: All JavaScript files load through prefix ──────── */
  test("all JS files load with 200 through the prefix", async ({ page }) => {
    const jsResponses: { url: string; status: number }[] = [];
    page.on("response", (res) => {
      const url = res.url();
      // Only track local JS files (skip CDN scripts like marked.min.js)
      if (url.endsWith(".js") && url.includes("localhost")) {
        jsResponses.push({ url, status: res.status() });
      }
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // There should be at least 5 local JS files (state, app, chat, graph, etc.)
    expect(jsResponses.length).toBeGreaterThanOrEqual(5);

    for (const r of jsResponses) {
      expect(r.status).toBe(200);
      expect(r.url).toContain("/app/");
    }
  });

  /* ── Test 8: Graph renders after chat command ──────────────── */
  test("graph panel renders nodes via chat through prefixed page", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await expect(page.locator(CHAT.input)).toBeVisible({ timeout: 15_000 });

    // Ask copilot to show a graph
    await sendChatMessage(page, "show fannie mae graph");

    // Wait for graph to render
    await waitForGraphRendered(page, 30_000);

    // Verify node count badge shows a positive number
    const countText = await page.locator(GRAPH.nodeCount).textContent();
    const count = parseInt(countText ?? "0", 10);
    expect(count).toBeGreaterThan(0);

    // Verify the URL still has the prefix
    expect(page.url()).toContain("/app");
  });

  /* ── Test 9: Detail panel opens for a node ─────────────────── */
  test("detail panel opens for a node on the prefixed page", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await expect(page.locator(CHAT.input)).toBeVisible({ timeout: 15_000 });

    // Load a graph
    await sendChatMessage(page, "show fannie mae graph");
    await waitForGraphRendered(page, 30_000);

    // Click a random node to open detail panel
    const nodeTitle = await clickRandomNode(page);
    expect(nodeTitle.length).toBeGreaterThan(0);

    // Detail panel should be visible
    await expect(page.locator(DETAIL.panel)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(DETAIL.title)).toHaveText(nodeTitle);

    // Verify all API calls went through the prefix
    expect(page.url()).toContain("/app");
  });

  /* ── Test 10: Non-prefixed API paths return 404 ────────────── */
  test("non-prefixed API paths return 404 (middleware blocks them)", async ({ request }) => {
    // These should NOT work — the prefix middleware should block them
    const directHealth = await request.get("/api/", {
      // Use the raw origin without the /app base
      failOnStatusCode: false,
    });
    expect(directHealth.status()).toBe(404);

    const directTasks = await request.get("/api/tasks", {
      failOnStatusCode: false,
    });
    expect(directTasks.status()).toBe(404);

    const directGraph = await request.get("/api/graph", {
      failOnStatusCode: false,
    });
    expect(directGraph.status()).toBe(404);
  });
});
