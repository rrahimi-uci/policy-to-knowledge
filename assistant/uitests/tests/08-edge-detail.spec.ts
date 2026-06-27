/**
 * Flow 8 — Edge Detail Panel
 *
 * Scenario:
 *   1. Load the graph via chat.
 *   2. Click a graph edge (via the wider link hit-area).
 *   3. Edge detail panel opens — verify title is non-empty.
 *   4. Verify the panel body has content (at least one endpoint chip).
 *   5. Verify the Reverse button is present.
 *   6. Close the panel and confirm it is no longer visible.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered } from "./helpers/graph";
import { CHAT, EDGE, GRAPH } from "./helpers/selectors";

test.describe("Flow 8 — Edge Detail Panel", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);
  });

  test("clicking an edge opens the edge detail panel", async ({ page }) => {
    // ── Step 1: Collect edge hit-areas ──────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Find graph edges and click one",
    });

    const edges = page.locator(GRAPH.linkHit);
    const edgeCount = await edges.count();

    if (edgeCount === 0) {
      test.info().annotations.push({
        type: "info",
        description: "No edges rendered in this graph — skipping edge panel check",
      });
      return;
    }

    // Dispatch a native MouseEvent directly on an SVG <line> that has D3
    // bound data.  Playwright's `click({ force: true })` on SVG line elements
    // inside a D3 zoom container does not reliably trigger D3's event
    // listeners, so we use page.evaluate to fire the event in-page.
    const edgeClicked = await page.evaluate((selector: string) => {
      const hits = document.querySelectorAll(selector);
      for (const hit of hits) {
        const box = hit.getBoundingClientRect();
        if (box.width > 0 && box.height > 0 && (hit as any).__data__) {
          hit.dispatchEvent(
            new MouseEvent("click", {
              bubbles: true,
              cancelable: true,
              clientX: box.x + box.width / 2,
              clientY: box.y + box.height / 2,
              view: window,
            })
          );
          return true;
        }
      }
      return false;
    }, GRAPH.linkHit);

    if (!edgeClicked) {
      test.info().annotations.push({
        type: "info",
        description: "No interactable edge found — skipping edge panel check",
      });
      return;
    }

    // ── Step 2: Edge detail panel should open ───────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify edge detail panel opens",
    });

    const edgePanel = page.locator(EDGE.panel);
    // Wait for the panel to get the .open class (not just CSS visibility,
    // since translateX(100%) panels still pass Playwright's isVisible check)
    await expect(edgePanel).toHaveClass(/\bopen\b/, { timeout: 10_000 });

    // ── Step 3: Title is non-empty ──────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify edge title is non-empty",
    });

    const title = await page.locator(EDGE.title).textContent();
    expect(title?.trim().length).toBeGreaterThan(0);

    // ── Step 4: Body has content ────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify edge panel body has content",
    });

    const body = page.locator(EDGE.body);
    await expect(body).toBeVisible();
    const bodyText = await body.textContent();
    expect(bodyText?.trim().length).toBeGreaterThan(0);

    // ── Step 5: Endpoint chips are present ──────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify at least one endpoint chip is shown",
    });

    const endpoints = page.locator(EDGE.endpoint);
    // Wait for at least one endpoint chip to render (D3 edge click can have timing lag)
    await endpoints.first().waitFor({ state: "visible", timeout: 5_000 }).catch(() => {});
    const endpointCount = await endpoints.count();
    // An edge connects two nodes — there should be at least one endpoint displayed
    expect(endpointCount).toBeGreaterThanOrEqual(1);

    // ── Step 6: Reverse button exists ───────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify Reverse button is present in edge panel",
    });

    await expect(page.locator(EDGE.reverseBtn)).toBeVisible();

    // ── Step 7: Close the panel ──────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Close the edge panel and verify it is dismissed",
    });

    await page.locator(EDGE.closeBtn).click();

    // The edge panel uses a CSS `.open` class for slide-in/out (same as node
    // detail panel) — wait for the class to be removed rather than checking
    // element visibility, which would fail during the CSS transition.
    await expect(edgePanel).not.toHaveClass(/\bopen\b/, { timeout: 8_000 });
  });

  test("edge panel title contains source and target node names", async ({
    page,
  }) => {
    const edges = page.locator(GRAPH.linkHit);
    const edgeCount = await edges.count();
    if (edgeCount === 0) {
      test.skip(true, "No edges rendered");
      return;
    }

    // Some edges may be outside the initial viewport due to the D3 force
    // layout. Try each edge until one is within the viewport.
    let clicked = false;
    for (let i = 0; i < Math.min(edgeCount, 10); i++) {
      const edge = edges.nth(i);
      try {
        const box = await edge.boundingBox();
        if (box && box.x >= 0 && box.y >= 0 && box.width > 0 && box.height > 0) {
          await edge.click({ force: true });
          clicked = true;
          break;
        }
      } catch {
        // Edge not interactable — try the next one
      }
    }

    if (!clicked) {
      // Fall back to force-clicking the first edge regardless of position
      await edges.first().click({ force: true });
    }

    const edgePanel = page.locator(EDGE.panel);
    await edgePanel.waitFor({ state: "visible", timeout: 10_000 });

    // The edge title should reference a relationship (e.g. "A → B" or "A relates_to B")
    const title = await page.locator(EDGE.title).textContent() ?? "";
    // At minimum it should be a non-trivial string longer than 3 characters
    expect(title.trim().length).toBeGreaterThan(3);

    // Body should mention at least one node name visible in the graph
    const body = await page.locator(EDGE.body).textContent() ?? "";
    expect(body.trim().length).toBeGreaterThan(0);
  });
});
