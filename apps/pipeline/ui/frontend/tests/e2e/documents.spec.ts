import fs from 'node:fs';
import path from 'node:path';

import { test, expect } from './fixtures';

test('documents page supports filtering and preview', async ({ page }) => {
  await page.goto('/documents');

  await expect(page.getByText('All domains is view-only. Switch to a domain tab to upload or create folders.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add Folder' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add Files' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Mortgage' }).click();

  await page.getByText('sample-guidelines').click();
  await expect(page.getByText('Fannie Mae November 2025 Selling Guide.md')).toBeVisible();
  await expect(page.getByText('Conventional escrow waiver policy.md')).toBeVisible();

  await page.getByLabel('Filter files').fill('escrow');
  await expect(page.getByText('Conventional escrow waiver policy.md')).toBeVisible();
  await expect(page.getByText('Fannie Mae November 2025 Selling Guide.md')).not.toBeVisible();

  await page.getByLabel('Filter files').fill('');
  const previewButton = page.getByLabel('Preview Fannie Mae November 2025 Selling Guide.md');
  await previewButton.hover();
  await previewButton.click();

  await expect(page.getByRole('heading', { name: 'Fannie Mae November 2025 Selling Guide.md' })).toBeVisible();
  await expect(page.getByText('Borrowers must meet credit, income, and occupancy eligibility rules.')).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();

  await page.getByLabel('Preview Servicing Guide Overview.docx').click();
  await expect(page.getByRole('heading', { name: 'Servicing Guide Overview.docx' })).toBeVisible();
  await expect(page.getByText('Escrow analysis is required for certain loan types.')).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();

  await page.getByLabel('Preview Mortgage Pricing Matrix.xlsx').click();
  await expect(page.getByRole('heading', { name: 'Mortgage Pricing Matrix.xlsx' })).toBeVisible();
  await expect(page.getByText('30YR Fixed')).toBeVisible();
  await expect(page.getByText('97%')).toBeVisible();
  await page.getByRole('button', { name: 'Close' }).click();

  await page.getByLabel('Preview Secondary Marketing Deck.pptx').click();
  await expect(page.getByRole('heading', { name: 'Secondary Marketing Deck.pptx' })).toBeVisible();
  await expect(page.getByText('Underwriting Flow')).toBeVisible();
  await expect(page.getByText('Gather borrower docs')).toBeVisible();
});

test('documents page preserves folder uploads and hands off to extraction', async ({ page }, testInfo) => {
  const uploadRoot = testInfo.outputPath('folder-upload');
  fs.mkdirSync(path.join(uploadRoot, 'nested'), { recursive: true });
  fs.writeFileSync(path.join(uploadRoot, 'policy.md'), '# Uploaded policy\n\nReady for extraction.');
  fs.writeFileSync(path.join(uploadRoot, 'nested', 'appendix.txt'), 'Nested appendix content');

  await page.goto('/documents');
  await page.getByRole('button', { name: 'AML' }).click();
  await page.getByLabel('Upload folder').setInputFiles(uploadRoot);

  await expect(page.getByText('Folder upload complete')).toBeVisible();
  await expect(page.getByText('uploaded-folder', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('2 files · AML')).toBeVisible();

  await page.getByRole('button', { name: 'Run Pipeline' }).click();

  await expect(page.getByRole('heading', { name: 'Knowledge Extraction Pipeline' })).toBeVisible();
  await expect(page.getByText('uploaded-folder', { exact: true }).first()).toBeVisible();
  await expect(page.getByTitle('Domain')).toHaveValue('aml');
});