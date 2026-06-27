import { expect, test } from '@playwright/test';

test('incomplete impact analysis flow shows validation instead of silently submitting', async ({ page }) => {
  let analyzeRequests = 0;

  await page.route('**/api/kg/graphs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        graphs: [
          {
            name: 'Fannie_Mae',
            provider: 'openai',
            rules: 392,
            entities: 35,
          },
        ],
      }),
    });
  });

  await page.route('**/api/kg/impact/analyses', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ analyses: [] }),
    });
  });

  await page.route('**/api/kg/impact/analyze', async (route) => {
    analyzeRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'unexpected-analysis' }),
    });
  });

  await page.goto('/impact-analysis');

  await expect(page.getByRole('button', { name: 'Select a Graph to Continue' })).toBeVisible();
  await expect(page.getByText('No analyses yet')).toBeVisible();

  await page.getByRole('combobox', { name: 'Target Knowledge Graph' }).selectOption('Fannie_Mae');

  await expect(
    page.getByText('Graph selected. Next, upload both the old and new regulatory documents to run analysis.')
  ).toBeVisible();

  const continueButton = page.getByRole('button', { name: 'Upload Both Documents to Continue' });
  await continueButton.click();

  await expect(page.getByText('Complete These Steps First')).toBeVisible();
  await expect(page.getByText('Upload the old regulatory document')).toBeVisible();
  await expect(page.getByText('Upload the new regulatory document')).toBeVisible();

  const oldDropZone = page.locator('input[title="Old Regulatory Document"]').locator('xpath=..');
  const newDropZone = page.locator('input[title="New Regulatory Document"]').locator('xpath=..');

  await expect(oldDropZone).toHaveClass(/border-red-500\/60/);
  await expect(newDropZone).toHaveClass(/border-red-500\/60/);
  expect(analyzeRequests).toBe(0);
});