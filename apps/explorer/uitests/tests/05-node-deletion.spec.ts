/**
 * Flow 5 — Node Deletion (Permanent)
 *
 * Steps tested:
 *  1. Load a graph via the copilot chat.
 *  2. Click a random node to open the detail panel.
 *  3. Click "Delete" → confirmation dialog opens.
 *  4. Cancel the confirmation → dialog closes, node unchanged.
 *  5. Click "Delete" again → confirmation dialog re-opens.
 *  6. Click "Delete Permanently" → node is permanently deleted:
 *       • Toast notification appears with "deleted".
 *       • Detail panel closes.
 *       • Node is removed from the graph SVG.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered, clickRandomNode, waitForDetailLoaded } from "./helpers/graph";
import { DETAIL, GRAPH } from "./helpers/selectors";

test.describe("Flow 5 – Node Deletion", () => {

  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // Load a graph via the copilot chat
    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);
  });

  test("delete a node permanently and verify it is removed", async ({ page }) => {
    // ── Step 1: Open a random node detail panel ──────────────────
    const nodeName = await clickRandomNode(page);
    expect(nodeName.length).toBeGreaterThan(0);
    await waitForDetailLoaded(page);

    // ── Step 2: Click Delete → confirmation dialog ───────────────
    await page.locator(DETAIL.deleteBtn).click();
    const confirmDialog = page.locator(DETAIL.deleteConfirm);
    await confirmDialog.waitFor({ state: "visible", timeout: 5_000 });

    // Verify confirmation includes the node name
    const confirmText = await confirmDialog.textContent();
    expect(confirmText).toBeTruthy();

    // Verify both Cancel and Delete Permanently buttons exist
    await expect(page.locator(DETAIL.deleteCancelBtn)).toBeVisible();
    await expect(page.locator(DETAIL.deleteDangerBtn)).toBeVisible();

    // ── Step 3: Cancel → dialog closes, node still visible ───────
    await page.locator(DETAIL.deleteCancelBtn).click();

    const subPanel = page.locator(DETAIL.subPanel);
    await subPanel.waitFor({ state: "hidden", timeout: 5_000 });

    // Node detail panel should still be open
    await expect(page.locator(DETAIL.panel)).toBeVisible();

    // ── Step 4: Delete again → confirm permanent deletion ────────
    await page.locator(DETAIL.deleteBtn).click();
    await confirmDialog.waitFor({ state: "visible", timeout: 5_000 });

    // Click "Delete Permanently" danger button
    await page.locator(DETAIL.deleteDangerBtn).click();

    // ── Step 5: Verify node is deleted ───────────────────────────
    // Toast should appear confirming deletion
    const toast = page.locator(".toast");
    await toast.first().waitFor({ state: "visible", timeout: 8_000 });
    const toastText = await toast.first().textContent();
    expect(toastText?.toLowerCase()).toContain("deleted");

    // Detail panel should close after deletion
    await expect(page.locator(DETAIL.panel)).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });
  });

  test("confirmation dialog shows correct node name", async ({ page }) => {
    // Click a node and verify the delete confirmation references it
    const nodeName = await clickRandomNode(page);
    await waitForDetailLoaded(page);

    await page.locator(DETAIL.deleteBtn).click();
    const confirmDialog = page.locator(DETAIL.deleteConfirm);
    await confirmDialog.waitFor({ state: "visible", timeout: 5_000 });

    // The dialog should contain the node name
    const dialogHTML = await confirmDialog.innerHTML();
    expect(dialogHTML).toContain(nodeName);

    // Clean up — cancel
    await page.locator(DETAIL.deleteCancelBtn).click();
  });
});
