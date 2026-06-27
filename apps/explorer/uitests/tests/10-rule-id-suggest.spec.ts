/**
 * Flow 10 — Rule ID Suggestion (Create Wizard)
 *
 * Scenario:
 *   1. Load the graph via chat.
 *   2. Open the Create Node wizard.
 *   3. Select a label (e.g. "Regulation") and fill the Name field.
 *   4. Optionally select Entity and Rule Type for a richer suggestion.
 *   5. Click the ✨🖊️ "Suggest Rule ID" button next to the Rule ID field.
 *   6. Wait for the API call to finish.
 *   7. Verify the Rule ID field is populated with a string matching BR_…
 *   8. Verify a toast "Rule ID suggested" appears.
 *
 * Note: Requires the backend + OpenAI API key. Generous timeout used.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered } from "./helpers/graph";
import { CHAT, CREATE, GRAPH, TOAST } from "./helpers/selectors";

test.describe("Flow 10 — Rule ID Suggestion", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);
  });

  test("suggest rule ID button fills the Rule ID field with a BR_ pattern", async ({
    page,
  }) => {
    // ── Step 1: Open create wizard ───────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Open the Create Node wizard",
    });

    await page.locator(GRAPH.createNodeBtn).click();
    await page.locator(CREATE.nameInput).waitFor({ state: "visible", timeout: 10_000 });

    // ── Step 2: Fill the Name field ──────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Enter a node name to drive the suggestion",
    });

    await page.locator(CREATE.nameInput).fill("Capital Reserve Requirement");

    // ── Step 3: Select a label ───────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Select a label for the new node",
    });

    // Labels are radio buttons — pick the first available one
    const labelRadios = page.locator(CREATE.labelRadio);
    const radioCount = await labelRadios.count();
    if (radioCount > 0) {
      await labelRadios.first().check();
    }

    // ── Step 4: Optionally select Entity and Rule Type ───────────
    test.info().annotations.push({
      type: "step",
      description: "Select entity and rule type if dropdowns have options",
    });

    const entitySelect = page.locator(CREATE.entitySelect);
    const entityOptions = await entitySelect.locator("option").count();
    if (entityOptions > 1) {
      // Pick the second option (first is usually the placeholder)
      await entitySelect.selectOption({ index: 1 });
    }

    const ruleTypeSelect = page.locator(CREATE.ruleTypeSelect);
    const ruleTypeOptions = await ruleTypeSelect.locator("option").count();
    if (ruleTypeOptions > 1) {
      await ruleTypeSelect.selectOption({ index: 1 });
    }

    // ── Step 5: Click the Suggest Rule ID sparkle button ─────────
    test.info().annotations.push({
      type: "step",
      description: "Click the Rule ID suggestion sparkle button",
    });

    const suggestBtn = page.locator(CREATE.suggestRuleIdBtn);
    await suggestBtn.waitFor({ state: "visible", timeout: 5_000 });
    await suggestBtn.click();

    // ── Step 6: Wait for the API call to complete ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Wait for Rule ID suggestion API call to finish",
    });

    // Button gets `ai-rewrite-loading` class during the network call
    await expect(suggestBtn).not.toHaveClass(/ai-rewrite-loading/, {
      timeout: 30_000,
    });
    await expect(suggestBtn).toBeEnabled({ timeout: 5_000 });

    // ── Step 7: Rule ID field should be filled ───────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify Rule ID field is populated with a BR_ pattern",
    });

    const ruleIdValue = await page.locator(CREATE.ruleIdInput).inputValue();
    expect(ruleIdValue.trim().length).toBeGreaterThan(0);
    // Standard pattern: BR_{ENTITY}_{TYPE}_{SEQ}_{SUB}
    expect(ruleIdValue).toMatch(/^BR_/i);

    // ── Step 8: Toast confirmation ───────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify 'Rule ID suggested' toast appears",
    });

    const toast = page.locator(TOAST.toast).last();
    await toast.waitFor({ state: "visible", timeout: 5_000 });
    const toastText = await toast.textContent();
    expect(toastText?.toLowerCase()).toContain("rule id");
  });

  test("suggest rule ID button shows a toast if Name is empty", async ({
    page,
  }) => {
    // Open wizard without filling the name
    await page.locator(GRAPH.createNodeBtn).click();
    await page.locator(CREATE.nameInput).waitFor({ state: "visible", timeout: 10_000 });

    // Do NOT fill the name — click suggest immediately
    const suggestBtn = page.locator(CREATE.suggestRuleIdBtn);
    await suggestBtn.waitFor({ state: "visible", timeout: 5_000 });
    await suggestBtn.click();

    // Should show a warning toast (no network call attempted)
    const toast = page.locator(TOAST.toast).last();
    await toast.waitFor({ state: "visible", timeout: 5_000 });
    const toastText = await toast.textContent();
    expect(toastText?.toLowerCase()).toContain("name");

    // Rule ID field should remain empty
    const ruleIdValue = await page.locator(CREATE.ruleIdInput).inputValue();
    expect(ruleIdValue.trim().length).toBe(0);
  });
});
