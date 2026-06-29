import { describe, it, expect } from 'vitest';
import { apiUrl, API_BASE } from '@/config';

/**
 * Regression for the bug where the CSV/JSON export anchors in Obligations.tsx
 * and ImpactAnalysis.tsx used a root-absolute `/api/...` href instead of going
 * through apiUrl(). Under a non-root base path (VITE_BASE_PATH) those hrefs 404
 * because they skip the configured prefix.
 *
 * These data-heavy pages are exercised end-to-end by the Playwright suite (and
 * are excluded from unit coverage), so we assert the URL-construction contract
 * that the fix relies on: export hrefs built via apiUrl carry API_BASE and are
 * never a bare root-absolute `/api/...`.
 */
describe('export URLs go through apiUrl (base-path aware)', () => {
  it('API_BASE is the configured prefixed base, not a bare /api', () => {
    // Default base path is "/app" -> API_BASE === "/app/api".
    expect(API_BASE).not.toBe('/api');
    expect(API_BASE.endsWith('/api')).toBe(true);
  });

  it('obligation export URLs are prefixed with API_BASE, never root-absolute', () => {
    const csv = apiUrl('kg/obligations/g1/export/csv?provider=openai');
    const json = apiUrl('kg/obligations/g1/export/json?provider=openai');
    expect(csv).toBe(`${API_BASE}/kg/obligations/g1/export/csv?provider=openai`);
    expect(json).toBe(`${API_BASE}/kg/obligations/g1/export/json?provider=openai`);
    expect(csv.startsWith(`${API_BASE}/`)).toBe(true);
    expect(csv.startsWith('/api/')).toBe(false);
    expect(json.startsWith('/api/')).toBe(false);
  });

  it('impact-analysis export URLs are prefixed with API_BASE, never root-absolute', () => {
    const csv = apiUrl('kg/impact/analyses/42/export/csv');
    const json = apiUrl('kg/impact/analyses/42/export/json');
    expect(csv).toBe(`${API_BASE}/kg/impact/analyses/42/export/csv`);
    expect(json).toBe(`${API_BASE}/kg/impact/analyses/42/export/json`);
    expect(csv.startsWith('/api/')).toBe(false);
    expect(json.startsWith('/api/')).toBe(false);
  });
});
