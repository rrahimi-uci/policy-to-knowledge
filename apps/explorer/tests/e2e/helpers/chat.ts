/**
 * Helper utilities for interacting with the Explorer chat panel
 * in Playwright tests.
 */

import { type Page, expect } from "@playwright/test";
import { CHAT } from "./selectors";

/**
 * Send a message in the chat panel and wait for the assistant response
 * to finish streaming.
 *
 * @param page  Playwright page object
 * @param message  The text to type into the chat input
 * @param timeoutMs  Max time to wait for the streamed response (default 90 s)
 * @returns The text content of the final assistant bubble
 */
export async function sendChatMessage(
  page: Page,
  message: string,
  timeoutMs = 90_000,
): Promise<string> {
  // Fill the chat input
  const input = page.locator(CHAT.input);
  await input.fill(message);

  // Click send
  await page.locator(CHAT.sendBtn).click();

  // Wait for the streaming cursor to appear (message started)
  await page.locator(CHAT.streamingCursor).first().waitFor({
    state: "attached",
    timeout: 30_000,
  });

  // Wait for the streaming cursor to disappear (message finished)
  await page
    .locator(CHAT.streamingCursor)
    .first()
    .waitFor({ state: "detached", timeout: timeoutMs });

  // Get the latest assistant bubble text
  const bubble = page.locator(CHAT.lastBubble).last();
  await bubble.waitFor({ state: "visible", timeout: 10_000 });
  return (await bubble.textContent()) ?? "";
}

/**
 * Wait until the chat is idle (no streaming in progress).
 */
export async function waitForChatIdle(page: Page, timeoutMs = 90_000) {
  // If any streaming cursor exists, wait for it to vanish
  const cursor = page.locator(CHAT.streamingCursor);
  if ((await cursor.count()) > 0) {
    await cursor.first().waitFor({ state: "detached", timeout: timeoutMs });
  }
}

/**
 * Get all visible node cards from the latest assistant response.
 */
export async function getNodeCards(page: Page) {
  const cards = page.locator(
    `.message.assistant:last-child ${CHAT.nodeCard}`,
  );
  await cards.first().waitFor({ state: "visible", timeout: 10_000 });
  return cards;
}

/**
 * Click a random node card from the latest chat response.
 * Returns the name of the clicked node.
 */
export async function clickRandomNodeCard(page: Page): Promise<string> {
  const cards = await getNodeCards(page);
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);

  const idx = Math.floor(Math.random() * count);
  const card = cards.nth(idx);
  const name = (await card.locator(CHAT.nodeCardName).textContent()) ?? "";
  await card.click();
  return name.trim();
}
