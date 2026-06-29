/**
 * Flow 14 — Loaded Knowledge Graph Data & Traceability
 *
 * Validates the end-to-end result of loading real pipeline KGs into JanusGraph
 * and serving them through the Explorer, independent of the AI assistant:
 *
 *   1. /app/ loads and renders the shell (chat + graph panels).
 *   2. The graph API returns a populated node/link set.
 *   3. Every business-rule node carries a source_reference (document→graph
 *      traceability — no missing citations).
 *   4. Switching graphs via ?graph_name= returns a different populated graph.
 *   5. Non-prefixed API paths are blocked (prefix middleware).
 *
 * These assertions are data-agnostic: they assert structure and invariants,
 * not specific rule text, so they hold for whatever KGs are currently loaded.
 */

import { test, expect } from "@playwright/test";
import { CHAT, GRAPH } from "./helpers/selectors";

test.describe("Flow 14 — Loaded graph data & traceability", () => {
  test("the app shell loads under /app/ with chat and graph panels", async ({ page }) => {
    await page.goto("/app/");
    await expect(page.locator(CHAT.input)).toBeVisible();
    await expect(page.locator(GRAPH.container)).toBeAttached();
  });

  test("graph API returns a populated node/link set", async ({ request }) => {
    const resp = await request.get("/app/api/graph");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(Array.isArray(body.nodes)).toBe(true);
    expect(Array.isArray(body.links)).toBe(true);
    expect(body.nodes.length).toBeGreaterThan(0);
    expect(body.links.length).toBeGreaterThan(0);
  });

  test("every business-rule node carries a source_reference (traceability)", async ({ request }) => {
    const resp = await request.get("/app/api/graph");
    const body = await resp.json();
    const ruleNodes = body.nodes.filter((n: any) => {
      const t = n.node_type ?? n.properties?.node_type ?? n.type;
      return t === "business_rule";
    });
    expect(ruleNodes.length).toBeGreaterThan(0);
    const withRef = ruleNodes.filter(
      (n: any) => n.source_reference ?? n.properties?.source_reference,
    );
    // No missing citations: every rule node has a source reference.
    expect(withRef.length).toBe(ruleNodes.length);
  });

  test("a second configured graph also returns populated data", async ({ request }) => {
    const a = await (await request.get("/app/api/graph?graph_name=sample_guidelines_g")).json();
    const b = await (await request.get("/app/api/graph?graph_name=example_policies_g")).json();
    expect(a.nodes.length).toBeGreaterThan(0);
    expect(b.nodes.length).toBeGreaterThan(0);
    // The two graphs are distinct in size.
    expect(a.nodes.length).not.toBe(b.nodes.length);
  });

  test("non-prefixed API path is blocked by the prefix middleware", async ({ request }) => {
    const resp = await request.get("/api/graph");
    expect(resp.status()).toBe(404);
  });
});
