/**
 * Flow 9 — AI Rewrite Sparkle Button (Create Wizard)
 *
 * Scenario:
 *   1. Load the graph via chat (ensures the toolbar is shown).
 *   2. Open the Create Node wizard via the toolbar button.
 *   3. Fill the Content textarea with seed text.
 *   4. Click the ✨🖊️ AI Rewrite sparkle button next to the Content field.
 *   5. Wait for the API call to finish (button loading class is removed).
 *   6. Verify the Content field has been updated with new text.
 *   7. Verify a toast "Rewritten by AI" appears.
 *
 * Note: This test requires the backend server to be running with a valid
 * OpenAI API key. The test uses a generous timeout for the AI call.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered } from "./helpers/graph";
import { CHAT, CREATE, GRAPH, TOAST } from "./helpers/selectors";

const SEED_TEXT =
  "A regulated institution must maintain adequate capital reserves at all times " +
  "as defined by the applicable regulatory authority.";

test.describe("Flow 9 — AI Rewrite Sparkle Button", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
    // Load graph first so the create toolbar button is available
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);
  });

  test("sparkle button rewrites content field text via /api/rewrite", async ({
    page,
  }) => {
    // ── Step 1: Open the Create Node wizard ──────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Open the Create Node wizard",
    });

    await page.locator(GRAPH.createNodeBtn).click();
    await page.locator(CREATE.nameInput).waitFor({ state: "visible", timeout: 10_000 });

    // ── Step 2: Fill seed content ────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Fill the Content field with seed text",
    });

    // Step 1 of the wizard has a next button — navigate to the content tab
    // if the content field isn't visible on step 1.
    // First, fill a name so the wizard is in a valid state.
    await page.locator(CREATE.nameInput).fill("Test Rule for AI Rewrite");

    // Try to locate the content field; if it's on a later step click Next first.
    const contentField = page.locator(CREATE.contentInput);
    const isContentVisible = await contentField.isVisible();

    if (!isContentVisible) {
      // Navigate to next step(s) until content is visible or we exhaust steps
      for (let i = 0; i < 3; i++) {
        const nextBtn = page.locator(CREATE.nextBtn);
        if (await nextBtn.isVisible()) {
          await nextBtn.click();
          await page.waitForTimeout(300);
          if (await contentField.isVisible()) break;
        } else {
          break;
        }
      }
    }

    await contentField.waitFor({ state: "visible", timeout: 5_000 });
    await contentField.fill(SEED_TEXT);

    // Verify seed text is in the field
    const beforeValue = await contentField.inputValue();
    expect(beforeValue).toBe(SEED_TEXT);

    // ── Step 3: Click the sparkle button ────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Click the AI rewrite sparkle button on the Content field",
    });

    const sparkleBtn = page.locator(CREATE.contentSparkleBtn);
    await sparkleBtn.waitFor({ state: "visible", timeout: 5_000 });
    await sparkleBtn.click();

    // ── Step 4: Wait for the API call to complete ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Wait for sparkle button to finish loading (API call done)",
    });

    // The button gets `ai-rewrite-loading` class + `disabled` during the call
    // Wait for it to become enabled again (up to 30 s for the AI response)
    await expect(sparkleBtn).not.toHaveClass(/ai-rewrite-loading/, {
      timeout: 30_000,
    });
    await expect(sparkleBtn).toBeEnabled({ timeout: 5_000 });

    // ── Step 5: Content field should be updated ──────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify Content field has been updated by AI",
    });

    const afterValue = await contentField.inputValue();
    // The rewritten text should differ from the seed text
    expect(afterValue).not.toBe(SEED_TEXT);
    // And it should be non-empty
    expect(afterValue.trim().length).toBeGreaterThan(0);

    // ── Step 6: Toast "Rewritten by AI" should appear ────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify 'Rewritten by AI' toast notification",
    });

    const toast = page.locator(TOAST.toast).last();
    await toast.waitFor({ state: "visible", timeout: 5_000 });
    const toastText = await toast.textContent();
    expect(toastText?.toLowerCase()).toContain("rewritten");
  });
});
