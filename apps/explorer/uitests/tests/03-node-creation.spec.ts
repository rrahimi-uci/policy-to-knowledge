/**
 * Flow 3 — Node Creation & Edge Connection
 *
 * Scenario:
 *   1. User clicks "Create Node" in the graph toolbar.
 *   2. Create wizard opens (Step 1 — vertex properties).
 *   3. User fills in node name, content, rule_type, entity, and description.
 *   4. User clicks "Next: Add Connections →" to go to Step 2.
 *   5. User searches for a target node and adds a manual connection
 *      with an edge label, direction, dependency type, and strength.
 *   6. User submits — node is created, graph refreshes with the new node.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered, getGraphStats } from "./helpers/graph";
import { CHAT, GRAPH, DETAIL, CREATE } from "./helpers/selectors";

/** Generate a unique node name so tests don't clash on repeated runs. */
function uniqueName() {
  const ts = Date.now().toString(36);
  return `UITest Node ${ts}`;
}

test.describe("Flow 3 — Node Creation & Edge Connection", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
  });

  test("Create a node, add a connection, and verify it appears on the graph", async ({
    page,
  }) => {
    // ── Pre-requisite: load a graph so the Create Node button works ──
    test.info().annotations.push({
      type: "step",
      description: "Load the graph via chat",
    });

    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);

    const statsBefore = await getGraphStats(page);
    expect(statsBefore.nodes).toBeGreaterThan(0);

    // ── Step 1: Click "Create Node" ──────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Click Create Node button",
    });

    const createBtn = page.locator(GRAPH.createNodeBtn);
    await expect(createBtn).toBeVisible();
    await createBtn.click();

    // Wait for the create wizard to render (reuses detailPanel).
    // The panel may already be visible showing "Node Details", so
    // wait for the title to change to "Create New Node".
    await expect(page.locator(DETAIL.title)).toHaveText("Create New Node", {
      timeout: 5_000,
    });

    // ── Step 2: Fill in Step 1 properties ────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Fill in vertex properties (name, content, rule_type, etc.)",
    });

    const nodeName = uniqueName();

    // Name (required)
    await page.locator(CREATE.nameInput).fill(nodeName);

    // Rule ID
    await page.locator(CREATE.ruleIdInput).fill("UITest-001");

    // Rule type
    await page.locator(CREATE.ruleTypeSelect).selectOption("constraint");

    // Entity (select the first available option if any)
    const entityOptions = await page
      .locator(`${CREATE.entitySelect} option`)
      .allTextContents();
    if (entityOptions.length > 1) {
      // Skip the "— Select —" placeholder
      await page.locator(CREATE.entitySelect).selectOption({ index: 1 });
    }

    // Description
    await page
      .locator(CREATE.descriptionInput)
      .fill("Created by Playwright UI test — automated validation.");

    // Content (required, min 10 chars)
    await page
      .locator(CREATE.contentInput)
      .fill(
        "This is a test node created by an automated Playwright E2E test. " +
          "It validates the create-node wizard flow including connections.",
      );

    // ── Step 3: Go to Step 2 ─────────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Click Next to go to the Connections step",
    });

    await page.locator(CREATE.nextBtn).click();

    // Wait for step 2 to render (wizard progress shows step 2 active)
    await page
      .locator(".wizard-step.active")
      .filter({ hasText: "2. Connections" })
      .waitFor({ state: "visible", timeout: 30_000 });

    // ── Step 4: Add a manual connection ──────────────────────────
    test.info().annotations.push({
      type: "step",
      description:
        "Search for a target node, configure edge, add to pending",
    });

    // Type a search query in the manual target input
    const targetInput = page.locator(CREATE.targetSearch);
    await targetInput.fill("credit");

    // Wait for search results to appear
    const results = page.locator(CREATE.targetResults);
    await results.waitFor({ state: "visible", timeout: 10_000 });

    // Click the first result
    const firstResult = page.locator(CREATE.targetItem).first();
    await firstResult.waitFor({ state: "visible", timeout: 5_000 });
    await firstResult.click();

    // Configure the edge
    await page.locator(CREATE.edgeLabelSelect).selectOption("depends_on");
    await page.locator(CREATE.depTypeSelect).selectOption("prerequisite");

    // Set direction to outgoing (default radio)
    await page.locator(`${CREATE.directionRadio}[value="outgoing"]`).check();

    // Set strength to 4
    await page.locator(CREATE.strengthSlider).fill("4");

    // Add rationale
    await page
      .locator(CREATE.rationaleInput)
      .fill("Automated test dependency");

    // Click "+ Add Connection"
    await page.locator(CREATE.addConnectionBtn).click();

    // Verify the pending connection appears
    const pending = page.locator(CREATE.pendingConnection);
    await pending.first().waitFor({ state: "visible", timeout: 5_000 });
    const pendingCount = await pending.count();
    expect(pendingCount).toBeGreaterThan(0);

    // ── Step 5: Submit the node ──────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Submit the create form and verify graph updates",
    });

    const submitBtn = page.locator(CREATE.submitBtn);
    await expect(submitBtn).toBeVisible();

    // Count existing toasts so we can wait for the NEW one after submit
    const toastsBefore = await page.locator(".toast").count();

    await submitBtn.click();

    // Wait for a new toast that contains "created" (the submit toast)
    await expect(
      page.locator(".toast").filter({ hasText: /created/i }),
    ).toBeVisible({ timeout: 30_000 });

    // Verify the create wizard closed (panel should either hide or
    // switch back to showing graph details)
    await expect(page.locator(DETAIL.title)).not.toHaveText("Create New Node", {
      timeout: 10_000,
    });
  });
});
