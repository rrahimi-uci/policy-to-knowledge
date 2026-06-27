/**
 * Flow 7 — Approval & Review Toggles
 *
 * Scenario:
 *   1. Load the graph via chat.
 *   2. Click a random node to open the detail panel.
 *   3. Toggle "Reviewed: Yes" → toast appears and toggle shows active.
 *   4. Toggle "Approved: Yes" → toast appears and toggle shows active.
 *   5. Verify both toggle states persist while the detail panel remains open.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import {
  waitForGraphRendered,
  clickRandomNode,
  waitForDetailLoaded,
} from "./helpers/graph";
import { CHAT, DETAIL, TOAST } from "./helpers/selectors";

test.describe("Flow 7 — Approval & Review Toggles", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);
  });

  test("toggling Reviewed: Yes shows toast and marks toggle active", async ({
    page,
  }) => {
    // ── Step 1: Open a random node ──────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Open a random node detail panel",
    });

    const nodeName = await clickRandomNode(page);
    expect(nodeName.length).toBeGreaterThan(0);
    await waitForDetailLoaded(page);

    // ── Step 2: Toggle "Reviewed: Yes" ─────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Click the Reviewed Yes toggle",
    });

    const reviewedYesBtn = page.locator(DETAIL.reviewedYes);
    await reviewedYesBtn.waitFor({ state: "visible", timeout: 5_000 });
    await reviewedYesBtn.click();

    // ── Step 3: Verify toast ────────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify toast notification appears",
    });

    const toast = page.locator(TOAST.toast).first();
    await toast.waitFor({ state: "visible", timeout: 8_000 });
    const toastText = await toast.textContent();
    expect(toastText?.toLowerCase()).toMatch(/review/);

    // ── Step 4: Verify toggle shows active state ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify reviewed-yes toggle is marked active",
    });

    // The clicked toggle should gain the 'active' class
    await expect(reviewedYesBtn).toHaveClass(/active/, { timeout: 5_000 });
  });

  test("toggling Approved: Yes shows toast and marks toggle active", async ({
    page,
  }) => {
    // ── Step 1: Open a random node ──────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Open a random node detail panel",
    });

    const nodeName = await clickRandomNode(page);
    expect(nodeName.length).toBeGreaterThan(0);
    await waitForDetailLoaded(page);

    // ── Step 2: Toggle "Approved: Yes" ─────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Click the Approved Yes toggle",
    });

    const approvedYesBtn = page.locator(DETAIL.approvedYes);
    await approvedYesBtn.waitFor({ state: "visible", timeout: 5_000 });
    await approvedYesBtn.click();

    // ── Step 3: Verify toast ────────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify toast notification appears",
    });

    const toast = page.locator(TOAST.toast).first();
    await toast.waitFor({ state: "visible", timeout: 8_000 });
    const toastText = await toast.textContent();
    expect(toastText?.toLowerCase()).toMatch(/approv/);

    // ── Step 4: Verify toggle shows active state ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Verify approved-yes toggle is marked active",
    });

    await expect(approvedYesBtn).toHaveClass(/active/, { timeout: 5_000 });
  });

  test("both toggles stay active after toggling in sequence", async ({
    page,
  }) => {
    // ── Step 1: Open a random node ──────────────────────────────
    const nodeName = await clickRandomNode(page);
    expect(nodeName.length).toBeGreaterThan(0);
    await waitForDetailLoaded(page);

    const reviewedYesBtn = page.locator(DETAIL.reviewedYes);
    const approvedYesBtn = page.locator(DETAIL.approvedYes);

    // ── Step 2: Toggle both to Yes ──────────────────────────────
    await reviewedYesBtn.waitFor({ state: "visible", timeout: 5_000 });
    await reviewedYesBtn.click();

    // Wait for the first toast to confirm success before the next click
    const firstToast = page.locator(TOAST.toast).first();
    await firstToast.waitFor({ state: "visible", timeout: 8_000 });

    await approvedYesBtn.waitFor({ state: "visible", timeout: 5_000 });
    await approvedYesBtn.click();

    const secondToast = page.locator(TOAST.toast).last();
    await secondToast.waitFor({ state: "visible", timeout: 8_000 });

    // ── Step 3: Both toggles should be active ───────────────────
    await expect(reviewedYesBtn).toHaveClass(/active/, { timeout: 5_000 });
    await expect(approvedYesBtn).toHaveClass(/active/, { timeout: 5_000 });

    // ── Step 4: "No" toggles should NOT be active ───────────────
    const reviewedNoBtn = page.locator(DETAIL.reviewedNo);
    const approvedNoBtn = page.locator(DETAIL.approvedNo);
    await expect(reviewedNoBtn).not.toHaveClass(/active/);
    await expect(approvedNoBtn).not.toHaveClass(/active/);
  });
});
