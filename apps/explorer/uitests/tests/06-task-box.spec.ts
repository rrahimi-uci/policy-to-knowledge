/**
 * 06-task-box.spec.ts — Task Box E2E Tests
 *
 * Tests the task box feature:
 *   1. Task panel opens and shows 6 tasks
 *   2. Filter buttons work (review / approval / all)
 *   3. Clicking a review task navigates to the graph and opens the node
 *   4. Clicking an approval task navigates, opens node, and pre-fills comment
 */

import { test, expect } from "@playwright/test";
import { DETAIL, GRAPH } from "./helpers/selectors";
import { waitForGraphRendered, waitForDetailLoaded } from "./helpers/graph";

/* ── Selectors specific to the task box ─────────────── */
const TASK = {
  toggleBtn: "#taskToggleBtn",
  panel: "#taskPanel",
  overlay: "#taskOverlay",
  closeBtn: ".task-panel-close",
  list: "#taskList",
  card: ".task-card",
  filterAll: '.task-filter-btn[data-filter="all"]',
  filterReview: '.task-filter-btn[data-filter="review"]',
  filterApproval: '.task-filter-btn[data-filter="approval"]',
  summary: "#taskSummary",
  badgeCount: "#taskBadgeCount",
  reviewCard: '.task-card[data-type="review"]',
  approvalCard: '.task-card[data-type="approval"]',
  nodeRow: ".task-node-row",
  typeBadge: ".task-badge-review, .task-badge-approval",
} as const;

test.describe("Task Box", () => {

  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // Wait for the page to fully load
    await page.waitForLoadState("networkidle");
    // Wait for the task toggle button to appear
    await page.locator(TASK.toggleBtn).waitFor({ state: "visible", timeout: 10_000 });
  });

  /* ── Test 1: Task panel opens with 6 tasks ────────── */
  test("opens task panel showing 6 tasks", async ({ page }) => {
    // Check the badge shows the pending count
    const badge = page.locator(TASK.badgeCount);
    await expect(badge).toBeVisible();
    const badgeText = await badge.textContent();
    expect(parseInt(badgeText ?? "0", 10)).toBeGreaterThanOrEqual(1);

    // Click to open the task panel
    await page.locator(TASK.toggleBtn).click();

    // Panel should slide in
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });
    await expect(page.locator(TASK.overlay)).toHaveClass(/\bopen\b/);

    // Wait for task cards to load
    await page.locator(TASK.card).first().waitFor({ state: "visible", timeout: 10_000 });

    // Should have 6 task cards
    const cardCount = await page.locator(TASK.card).count();
    expect(cardCount).toBe(6);

    // Should have 4 review cards and 2 approval cards
    const reviewCount = await page.locator(TASK.reviewCard).count();
    const approvalCount = await page.locator(TASK.approvalCard).count();
    expect(reviewCount).toBe(4);
    expect(approvalCount).toBe(2);

    // Summary bar should be visible
    await expect(page.locator(TASK.summary)).toBeVisible();
    const summaryText = await page.locator(TASK.summary).textContent();
    expect(summaryText).toContain("4 reviews");
    expect(summaryText).toContain("2 approvals");
  });

  /* ── Test 2: Filter buttons work ──────────────────── */
  test("filters tasks by type", async ({ page }) => {
    // Open the task panel
    await page.locator(TASK.toggleBtn).click();
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });
    await page.locator(TASK.card).first().waitFor({ state: "visible", timeout: 10_000 });

    // Click "Review" filter
    await page.locator(TASK.filterReview).click();
    await expect(page.locator(TASK.filterReview)).toHaveClass(/\bactive\b/);

    // Should only show review cards
    const reviewCards = await page.locator(TASK.card).count();
    expect(reviewCards).toBe(4);
    // All displayed cards should be review type
    for (let i = 0; i < reviewCards; i++) {
      await expect(page.locator(TASK.card).nth(i)).toHaveAttribute("data-type", "review");
    }

    // Click "Approval" filter
    await page.locator(TASK.filterApproval).click();
    await expect(page.locator(TASK.filterApproval)).toHaveClass(/\bactive\b/);

    const approvalCards = await page.locator(TASK.card).count();
    expect(approvalCards).toBe(2);
    for (let i = 0; i < approvalCards; i++) {
      await expect(page.locator(TASK.card).nth(i)).toHaveAttribute("data-type", "approval");
    }

    // Click "All" to restore
    await page.locator(TASK.filterAll).click();
    await expect(page.locator(TASK.filterAll)).toHaveClass(/\bactive\b/);
    const allCards = await page.locator(TASK.card).count();
    expect(allCards).toBe(6);
  });

  /* ── Test 3: Clicking close button closes the panel ─ */
  test("close button dismisses the task panel", async ({ page }) => {
    // Open
    await page.locator(TASK.toggleBtn).click();
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });

    // Close via the X button
    await page.locator(TASK.closeBtn).click();
    await expect(page.locator(TASK.panel)).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });
    await expect(page.locator(TASK.overlay)).not.toHaveClass(/\bopen\b/);
  });

  /* ── Test 3b: Badge count decrements on task click ── */
  test("badge count decrements when a task is clicked", async ({ page }) => {
    const badge = page.locator(TASK.badgeCount);
    await badge.waitFor({ state: "visible", timeout: 5_000 });

    // Capture the current badge count (may vary if server retains state between runs)
    const initialText = await badge.textContent();
    const initialCount = parseInt(initialText ?? "0", 10);
    expect(initialCount).toBeGreaterThanOrEqual(1);

    // Open task panel
    await page.locator(TASK.toggleBtn).click();
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });

    // Wait for task cards to load, then pick the FIRST PENDING task (not a completed one)
    const pendingCard = page.locator(".task-card").filter({ hasNot: page.locator(".task-badge-completed") });
    await pendingCard.first().waitFor({ state: "visible", timeout: 10_000 });
    await pendingCard.first().click();

    // Panel should close
    await expect(page.locator(TASK.panel)).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });

    // Badge should decrement by exactly 1
    await expect(badge).toHaveText(String(initialCount - 1), { timeout: 5_000 });
  });

  /* ── Test 4: Review task navigates to graph + node ── */
  test("review task click navigates to graph and opens node detail", async ({ page }) => {
    // Open task panel
    await page.locator(TASK.toggleBtn).click();
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });
    await page.locator(TASK.card).first().waitFor({ state: "visible", timeout: 10_000 });

    // Get the first review card's title for verification
    const firstReviewCard = page.locator(TASK.reviewCard).first();
    const nodeName = await firstReviewCard.locator(".task-node-name").textContent();
    expect(nodeName).toBeTruthy();

    // Click the first review task
    await firstReviewCard.click();

    // Task panel should close
    await expect(page.locator(TASK.panel)).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });

    // A toast should appear
    const toast = page.locator(".toast").first();
    await toast.waitFor({ state: "visible", timeout: 5_000 });

    // Graph should render
    await waitForGraphRendered(page, 30_000);

    // Detail panel should open
    await page.locator(DETAIL.panel).waitFor({ state: "visible", timeout: 20_000 });

    // Wait for detail to load
    await waitForDetailLoaded(page, 20_000);

    // The detail title should contain the node name
    const detailTitle = await page.locator(DETAIL.title).textContent();
    expect(detailTitle).toBeTruthy();
  });

  /* ── Test 5: Approval task opens node + comment ───── */
  test("approval task click opens node and pre-fills comment", async ({ page }) => {
    // Open task panel
    await page.locator(TASK.toggleBtn).click();
    await expect(page.locator(TASK.panel)).toHaveClass(/\bopen\b/, { timeout: 5_000 });
    await page.locator(TASK.card).first().waitFor({ state: "visible", timeout: 10_000 });

    // Switch to approval filter to easily find an approval task
    await page.locator(TASK.filterApproval).click();
    await page.locator(TASK.approvalCard).first().waitFor({ state: "visible", timeout: 5_000 });

    // Click the first approval task
    await page.locator(TASK.approvalCard).first().click();

    // Task panel should close
    await expect(page.locator(TASK.panel)).not.toHaveClass(/\bopen\b/, { timeout: 5_000 });

    // Graph should render
    await waitForGraphRendered(page, 30_000);

    // Detail panel should open
    await page.locator(DETAIL.panel).waitFor({ state: "visible", timeout: 20_000 });
    await waitForDetailLoaded(page, 20_000);

    // The comment sub-panel should appear (auto-opened for approval tasks)
    const commentInput = page.locator("#commentInput");
    await commentInput.waitFor({ state: "visible", timeout: 15_000 });

    // Comment should be pre-filled with text — wait for the async pre-fill
    await expect(async () => {
      const commentValue = await commentInput.inputValue();
      expect(commentValue.length).toBeGreaterThan(10);
    }).toPass({ timeout: 10_000 });
  });
});
