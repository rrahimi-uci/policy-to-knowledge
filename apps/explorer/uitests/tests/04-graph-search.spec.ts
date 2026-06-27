/**
 * Flow 4 — Graph Search
 *
 * Scenario:
 *   1. User asks the assistant to show the full graph (loads the visualization).
 *   2. User types "credit" in the graph search bar.
 *   3. Matching nodes remain bright; non-matching nodes and edges are dimmed.
 *   4. The match count indicator shows a positive number.
 *   5. User clears the search — all nodes return to their normal state.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import {
  waitForGraphRendered,
  searchGraph,
  clearGraphSearch,
  getSearchMatchCount,
} from "./helpers/graph";
import { CHAT, GRAPH } from "./helpers/selectors";

test.describe("Flow 4 — Graph Search", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
  });

  test("Search for 'credit' nodes on the graph", async ({ page }) => {
    // ── Step 1: Load the graph via chat ──────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Ask assistant to show the full graph",
    });

    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);

    // Record initial state — no nodes should be dimmed
    const initialDimmed = await page
      .locator(`${GRAPH.node}.${GRAPH.dimClass}`)
      .count();
    expect(initialDimmed).toBe(0);

    // ── Step 2: Type "credit" in the search bar ──────────────────
    test.info().annotations.push({
      type: "step",
      description: "Search for 'credit' nodes in graph search bar",
    });

    await searchGraph(page, "credit");

    // ── Step 3: Verify filtering ─────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify matching nodes bright, others dimmed",
    });

    // Some nodes should be dimmed (search-dim class)
    const dimmedNodes = page.locator(`${GRAPH.node}.${GRAPH.dimClass}`);
    const dimmedCount = await dimmedNodes.count();

    // At least some nodes should be dimmed (if "credit" doesn't match all)
    const totalNodes = await page.locator(GRAPH.node).count();
    // If there are matching nodes, dimmed count should be > 0 and < total
    const matchCount = await getSearchMatchCount(page);

    if (matchCount > 0 && matchCount < totalNodes) {
      expect(dimmedCount).toBeGreaterThan(0);
    }

    // ── Step 4: Verify match count indicator ─────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify match count badge shows a number",
    });

    const matchEl = page.locator(GRAPH.searchMatchCount);
    await expect(matchEl).toBeVisible();
    expect(matchCount).toBeGreaterThan(0);

    // The match count text should contain a number and "match"
    const matchText = await matchEl.textContent();
    expect(matchText).toMatch(/\d+ match/);

    // ── Step 5: Clear the search and verify reset ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Clear search and verify all nodes are restored",
    });

    await clearGraphSearch(page);

    // No nodes should be dimmed after clearing
    await page.waitForTimeout(300); // wait for CSS transition
    const dimmedAfterClear = await page
      .locator(`${GRAPH.node}.${GRAPH.dimClass}`)
      .count();
    expect(dimmedAfterClear).toBe(0);

    // Match count should no longer be visible
    const matchElAfter = page.locator(GRAPH.searchMatchCount);
    // It should either be hidden or have its text cleared
    const isVisible = await matchElAfter.isVisible();
    if (isVisible) {
      const hasVisibleClass = await matchElAfter.evaluate(
        (el) => el.classList.contains("visible"),
      );
      expect(hasVisibleClass).toBe(false);
    }
  });

  test("Search for a non-existent term shows empty state", async ({
    page,
  }) => {
    // Load the graph first
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);

    // Search for something that won't match
    await searchGraph(page, "xyznonexistent12345");

    // Match count should be 0
    const matchCount = await getSearchMatchCount(page);
    expect(matchCount).toBe(0);

    // Empty state message should appear
    const emptyEl = page.locator(GRAPH.searchEmpty);
    await expect(emptyEl).toBeVisible({ timeout: 2_000 });
    const emptyText = await emptyEl.textContent();
    expect(emptyText).toContain("No nodes matching");

    // Clear and restore
    await clearGraphSearch(page);
  });
});
