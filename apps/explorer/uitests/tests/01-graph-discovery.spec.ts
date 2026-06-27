/**
 * Flow 1 — Graph Discovery
 *
 * Scenario:
 *   1. User asks the assistant how many graphs are available.
 *   2. Assistant answers with the graph count.
 *   3. User asks to show one of the graphs (randomly chosen by the LLM).
 *   4. A graph renders in the right panel with nodes and edges.
 *   5. Verify that node count, link count, and graph-name badge are populated.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered, getGraphStats } from "./helpers/graph";
import { GRAPH, CHAT } from "./helpers/selectors";

test.describe("Flow 1 — Graph Discovery", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // Wait for the page to be ready (chat input is focusable)
    await page.locator(CHAT.input).waitFor({ state: "visible" });
  });

  test("Step 1-2: Ask assistant about the number of available graphs", async ({
    page,
  }) => {
    const response = await sendChatMessage(
      page,
      "How many graphs are available in the system?",
    );

    // The response should mention a number (at least 1 graph)
    expect(response.length).toBeGreaterThan(0);
    // The response should mention a number (digit or word like "four")
    const hasNumber = /\d|one|two|three|four|five|six|seven|eight|nine|ten/i.test(response);
    expect(hasNumber).toBe(true);
  });

  test("Step 3-5: Ask assistant to show a graph and verify it renders", async ({
    page,
  }) => {
    // First ask about graphs to set context
    await sendChatMessage(
      page,
      "How many graphs are available?",
    );

    // Now ask to show one (the LLM picks one)
    await sendChatMessage(
      page,
      "Show me one of the graphs, any one you choose.",
    );

    // Wait for the graph to render with nodes
    await waitForGraphRendered(page, 60_000);

    // Verify the graph has data
    const stats = await getGraphStats(page);
    expect(stats.nodes).toBeGreaterThan(0);
    expect(stats.links).toBeGreaterThanOrEqual(0);

    // Verify the graph name badge is visible
    const badge = page.locator(GRAPH.graphNameBadge);
    await expect(badge).toBeVisible();
    const badgeText = await badge.textContent();
    expect(badgeText).toBeTruthy();
    // The badge should contain a valid traversal source name (ends with _g)
    expect(badgeText).toMatch(/_g$/);
  });
});
