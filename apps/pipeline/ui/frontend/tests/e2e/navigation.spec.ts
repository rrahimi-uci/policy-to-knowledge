import { test, expect } from './fixtures';

test('app shell navigation and theme toggle remain stable', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByText('Sample_Guidelines')).toBeVisible();
  await expect(page.getByText('AML_Handbook')).toBeVisible();

  await page.getByRole('button', { name: 'Light Mode' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.getByRole('button', { name: 'Dark Mode' })).toBeVisible();

  await page.getByRole('link', { name: 'Domain Documents' }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole('heading', { name: 'Domain Documents' })).toBeVisible();

  await page.getByRole('link', { name: 'Knowledge Extraction Pipeline' }).click();
  await expect(page).toHaveURL(/\/pipeline$/);
  await expect(page.getByRole('heading', { name: 'Knowledge Extraction Pipeline' })).toBeVisible();

  await page.getByRole('link', { name: 'Explorer' }).click();
  await expect(page).toHaveURL(/\/explorer$/);
  await expect(page.getByRole('heading', { name: 'Knowledge Graph Explorer' })).toBeVisible();

  await page.getByRole('link', { name: 'Run History' }).click();
  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByRole('heading', { name: 'Run History' })).toBeVisible();

  await page.getByRole('link', { name: 'Settings' }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

  await page.goto('/compare');
  await expect(page.getByRole('heading', { name: 'Graph Compare' })).toBeVisible();
});