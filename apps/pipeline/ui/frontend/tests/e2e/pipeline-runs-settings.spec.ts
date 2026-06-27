import fs from 'node:fs';
import path from 'node:path';

import { test, expect } from './fixtures';

test('pipeline creation and joining forms stay interactive', async ({ page }) => {
  await page.goto('/pipeline');

  const startPipeline = page.getByRole('button', { name: 'Start Pipeline' });
  await expect(startPipeline).toBeDisabled();

  await page.getByRole('button', { name: /sample-guidelines/ }).click();
  await expect(startPipeline).toBeEnabled();

  await page.getByRole('button', { name: /KG Joining/ }).click();
  await expect(page.getByRole('button', { name: 'Start Joining Pipeline' })).toBeEnabled();
});

test('folder uploads launch as batch runs and show folder source in run history', async ({ page }, testInfo) => {
  const uploadRoot = testInfo.outputPath('folder-batch-run');
  fs.mkdirSync(path.join(uploadRoot, 'nested'), { recursive: true });
  fs.writeFileSync(path.join(uploadRoot, 'policy.md'), '# Uploaded policy\n\nReady for batch extraction.');
  fs.writeFileSync(path.join(uploadRoot, 'nested', 'appendix.txt'), 'Nested appendix content');

  await page.goto('/documents');
  await page.getByLabel('Upload folder').setInputFiles(uploadRoot);

  await expect(page.getByText('Folder upload complete')).toBeVisible();
  await page.getByRole('button', { name: 'Open In Pipeline' }).click();

  await expect(page.getByText('Folder uploads run as one batch')).toBeVisible();
  await expect(page.getByText('uploaded-folder · unified batch')).toBeVisible();

  await page.getByRole('button', { name: 'Start Pipeline' }).click();
  await expect(page.getByText('Pipeline Completed')).toBeVisible();

  await page.goto('/runs');
  await page.getByRole('button', { name: 'KG Creation mortgage completed' }).first().click();
  await expect(page.getByText('Source')).toBeVisible();
  await expect(page.getByText('uploaded-folder · batch')).toBeVisible();
});

test('compare page renders completed comparison visualizations', async ({ page }) => {
  await page.goto('/compare');

  await expect(page.getByRole('heading', { name: 'Graph Compare' })).toBeVisible();
  await page.getByText('Fannie_Mae vs Freddie_Mac').click();
  await expect(page.getByRole('button', { name: /Intersection/ })).toBeVisible();
  await expect(page.getByTitle(/Fannie_Mae_vs_Freddie_Mac/)).toBeVisible();
});

test('run history filters and expands completed runs', async ({ page }) => {
  await page.goto('/runs');

  await page.getByRole('combobox', { name: 'Filter by status' }).selectOption('completed');
  await expect(page.getByText('1 of 3 runs')).toBeVisible();

  await page.getByRole('button', { name: 'KG Creation mortgage completed' }).click();
  await expect(page.getByText('Source')).toBeVisible();
  await expect(page.getByText('sample-guidelines · batch')).toBeVisible();
});

test('settings persist mocked updates and show success feedback', async ({ page }) => {
  await page.goto('/settings');

  await page.getByRole('button', { name: 'pipeline' }).click();
  await page.getByRole('button', { name: /Save/ }).click();

  await expect(page.getByText('Settings saved successfully')).toBeVisible();

  // Domain tab was removed — verify it no longer exists
  await expect(page.getByRole('button', { name: 'domain' })).toHaveCount(0);
});