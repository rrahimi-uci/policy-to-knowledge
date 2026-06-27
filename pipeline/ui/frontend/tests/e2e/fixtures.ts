import { test as base, expect } from '@playwright/test';
import { createMockState, mockApi } from './helpers/mockApi';

export const test = base.extend<{ mockState: ReturnType<typeof createMockState> }>({
  mockState: [async ({ page }, use) => {
    const state = createMockState();
    await mockApi(page, state);
    await page.addInitScript(() => {
      Object.defineProperty(window, 'Notification', {
        configurable: true,
        writable: true,
        value: class MockNotification {
          static permission = 'granted';
          static requestPermission() {
            return Promise.resolve('granted');
          }
          constructor() {}
        },
      });
    });
    await use(state);
  }, { auto: true }],
});

export { expect };