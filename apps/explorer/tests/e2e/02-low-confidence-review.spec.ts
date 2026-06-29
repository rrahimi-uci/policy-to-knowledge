/**
 * Flow 2 — Low-Confidence Review
 *
 * Scenario:
 *   1. Load the graph via assistant and click a random node.
 *   2. Detail panel opens — check reference link.
 *   3. Add a comment with a random author.
 *   4. Select another node and edit its name & content, then save.
 */

import { test, expect } from "@playwright/test";
import { sendChatMessage } from "./helpers/chat";
import { waitForGraphRendered, clickRandomNode, waitForDetailLoaded, closeDetailPanel } from "./helpers/graph";
import { CHAT, DETAIL, GRAPH } from "./helpers/selectors";

const COMMENT_AUTHORS = ["Jack", "Tom", "Gina", "Rose"];

test.describe("Flow 2 — Low-Confidence Review", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.locator(CHAT.input).waitFor({ state: "visible" });
  });

  test("Full review flow: search → inspect → comment → edit", async ({
    page,
  }) => {
    // ── Step 1: Load the graph ───────────────────────────────────
    test.info().annotations.push({
      type: "step",
      description: "Load the graph via chat",
    });

    await sendChatMessage(page, "Show me the full graph.");
    await waitForGraphRendered(page, 60_000);

    // ── Step 2: Click a random node → detail panel opens ─────────
    test.info().annotations.push({
      type: "step",
      description: "Click a random graph node and check detail panel",
    });

    const clickedName = await clickRandomNode(page);
    expect(clickedName).toBeTruthy();

    // Wait for the detail panel to fully load
    await waitForDetailLoaded(page);

    // Verify basic detail panel content
    const title = await page.locator(DETAIL.title).textContent();
    expect(title).toBeTruthy();

    // ── Step 4: Check reference link (if present) ────────────────
    test.info().annotations.push({
      type: "step",
      description: "Check reference link opens correctly in new tab",
    });

    const refLinks = page.locator(`${DETAIL.body} ${DETAIL.refLink}`);
    const refCount = await refLinks.count();

    if (refCount > 0) {
      // Click the first reference link — should open a new tab
      const [newPage] = await Promise.all([
        page.context().waitForEvent("page", { timeout: 15_000 }),
        refLinks.first().click(),
      ]);

      // Wait for the new page to load
      await newPage.waitForLoadState("domcontentloaded", { timeout: 15_000 });
      const newUrl = newPage.url();

      // The reference page should be a chunk URL
      expect(newUrl).toContain("/api/reference/chunk");

      // Verify the page has content (styled HTML page for chunk)
      const body = await newPage.locator("body").textContent();
      expect(body?.length).toBeGreaterThan(0);

      await newPage.close();
    } else {
      test.info().annotations.push({
        type: "info",
        description: "No reference links found on this node — skipping link check",
      });
    }

    // ── Step 5: Add a comment with a random author ───────────────
    test.info().annotations.push({
      type: "step",
      description: "Add a comment and assign to a random person",
    });

    // Click the Comment action button
    const commentBtn = page.locator(`${DETAIL.body} ${DETAIL.commentBtn}`);
    await commentBtn.click();

    // Wait for the comment sub-panel
    await page.locator(DETAIL.subPanel).waitFor({ state: "visible", timeout: 5_000 });

    // Pick a random author
    const randomAuthor =
      COMMENT_AUTHORS[Math.floor(Math.random() * COMMENT_AUTHORS.length)];
    await page.locator(DETAIL.commentAuthor).selectOption(randomAuthor);

    // Type a comment
    const commentText = `Review needed — low confidence score. Flagged by ${randomAuthor} during UI test at ${new Date().toISOString()}`;
    await page.locator(DETAIL.commentInput).fill(commentText);

    // Submit
    await page.locator(DETAIL.commentSubmit).click();

    // Verify the comment appears in the list
    const commentItem = page.locator(`${DETAIL.commentList} ${DETAIL.commentItem}`);
    await commentItem.first().waitFor({ state: "visible", timeout: 5_000 });
    const commentCount = await commentItem.count();
    expect(commentCount).toBeGreaterThan(0);

    // Verify the comment text is present
    const lastComment = commentItem.last();
    const lastCommentText = await lastComment.textContent();
    expect(lastCommentText).toContain("Review needed");

    // Verify the author badge is present
    const authorBadge = lastComment.locator(".comment-author");
    const authorText = await authorBadge.textContent();
    expect(authorText).toContain(randomAuthor);

    // Close the comment sub-panel
    await page.locator(DETAIL.subPanelClose).click();

    // ── Step 6: Select another node and edit it ──────────────────
    test.info().annotations.push({
      type: "step",
      description: "Select another node, edit name & content, and save",
    });

    // Close current detail panel and click a different graph node
    await closeDetailPanel(page);

    await clickRandomNode(page);
    await waitForDetailLoaded(page);

    // Click the Edit action button
    const editBtn = page.locator(`${DETAIL.body} ${DETAIL.editBtn}`);
    await editBtn.click();

    // Wait for the edit sub-panel
    await page.locator(DETAIL.subPanel).waitFor({ state: "visible", timeout: 5_000 });

    // Edit the name (append " [Reviewed]")
    const nameInput = page.locator(DETAIL.editName);
    const currentName = await nameInput.inputValue();
    await nameInput.fill(`${currentName} [Reviewed]`);

    // Edit the content (append a note)
    const contentInput = page.locator(DETAIL.editContent);
    const currentContent = await contentInput.inputValue();
    await contentInput.fill(
      `${currentContent}\n\n--- Reviewed during UI test at ${new Date().toISOString()} ---`,
    );

    // Save
    await page.locator(DETAIL.editSave).click();

    // Verify a toast or visual confirmation appears
    // The save triggers an overlay badge "edited" on the detail header
    const editBadge = page.locator(".edit-overlay-badge");
    await expect(editBadge).toBeVisible({ timeout: 5_000 });
  });
});
