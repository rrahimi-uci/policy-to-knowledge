/**
 * Helper utilities for interacting with the Explorer graph panel
 * in Playwright tests.
 */

import { type Page, expect } from "@playwright/test";
import { GRAPH, DETAIL } from "./selectors";

/**
 * Wait for the graph to render at least one node in the SVG.
 */
export async function waitForGraphRendered(
  page: Page,
  timeoutMs = 30_000,
) {
  await page.locator(GRAPH.node).first().waitFor({
    state: "attached",
    timeout: timeoutMs,
  });
}

/**
 * Get the current node and link counts shown in the toolbar.
 */
export async function getGraphStats(page: Page) {
  const nodes = parseInt(
    (await page.locator(GRAPH.nodeCount).textContent()) ?? "0",
    10,
  );
  const links = parseInt(
    (await page.locator(GRAPH.linkCount).textContent()) ?? "0",
    10,
  );
  return { nodes, links };
}

/**
 * Click a random graph node (SVG circle).
 * Returns the d3 datum `id` attribute of the clicked node.
 */
export async function clickRandomNode(page: Page): Promise<string> {
  const nodes = page.locator(GRAPH.node);
  const count = await nodes.count();
  expect(count).toBeGreaterThan(0);

  const idx = Math.floor(Math.random() * count);
  const node = nodes.nth(idx);

  // Scroll the node into view — SVG nodes can be out of viewport
  await node.scrollIntoViewIfNeeded();

  // Force-click since SVG elements may overlap
  await node.click({ force: true });

  // Wait for detail panel to open
  await page
    .locator(DETAIL.panel)
    .waitFor({ state: "visible", timeout: 15_000 });

  // Return the node title shown in the detail panel
  const title =
    (await page.locator(DETAIL.title).textContent()) ?? "";
  return title.trim();
}

/**
 * Wait for the detail panel to finish loading (skeleton gone).
 */
export async function waitForDetailLoaded(page: Page, timeoutMs = 15_000) {
  // Wait for any skeleton to disappear
  const skeleton = page.locator(`${DETAIL.body} ${DETAIL.skeleton}`);
  if ((await skeleton.count()) > 0) {
    await skeleton.first().waitFor({ state: "detached", timeout: timeoutMs });
  }
  // The action grid should be visible
  await page.locator(DETAIL.actionGrid).waitFor({
    state: "visible",
    timeout: timeoutMs,
  });
}

/**
 * Close the detail panel if open.
 * The panel uses CSS transform (translateX) with an `.open` class,
 * so we wait for the class to be removed rather than state:hidden.
 */
export async function closeDetailPanel(page: Page) {
  const panel = page.locator(DETAIL.panel);
  if (await panel.isVisible()) {
    await page.locator(DETAIL.closeBtn).click();
    // Wait for the .open class to be removed (panel slides out)
    await expect(panel).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });
  }
}

/**
 * Type into the graph search bar and wait for filtering to apply.
 */
export async function searchGraph(page: Page, query: string) {
  const input = page.locator(GRAPH.searchInput);
  await input.fill(query);
  // Debounce is 150 ms; wait a bit for filtering
  await page.waitForTimeout(400);
}

/**
 * Clear the graph search bar.
 */
export async function clearGraphSearch(page: Page) {
  const clearBtn = page.locator(GRAPH.searchClear);
  if (await clearBtn.isVisible()) {
    await clearBtn.click();
    await page.waitForTimeout(200);
  }
}

/**
 * Get the number of search matches shown in the toolbar.
 */
export async function getSearchMatchCount(page: Page): Promise<number> {
  const el = page.locator(GRAPH.searchMatchCount);
  const text = (await el.textContent()) ?? "";
  const match = text.match(/(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}
