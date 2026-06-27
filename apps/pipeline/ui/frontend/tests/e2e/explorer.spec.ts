import { test, expect } from './fixtures';

test('explorer renders rules and entity-driven filtering', async ({ page }) => {
  await page.goto('/explorer');

  await expect(page.getByRole('heading', { name: 'Knowledge Graph Explorer' })).toBeVisible();
  await expect(page.getByLabel('Knowledge graph')).toHaveValue('Fannie_Mae');

  await page.getByRole('button', { name: /Rules \(/ }).click();
  await page.getByPlaceholder('Search rules...').fill('LTV');
  await expect(page.getByText('Maximum LTV 97% First-Time Buyer')).toBeVisible();
  await expect(page.getByText('Borrower Credit Score Minimum 620 Conventional')).not.toBeVisible();

  await page.getByPlaceholder('Search rules...').fill('');
  await page.getByRole('button', { name: /Entities \(/ }).click();
  await page.getByText('BORROWER').click();

  await expect(page.getByText('Entity: BORROWER')).toBeVisible();
  await expect(page.getByText('Borrower Credit Score Minimum 620 Conventional')).toBeVisible();
});