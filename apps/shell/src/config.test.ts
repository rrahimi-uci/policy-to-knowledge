import { describe, it, expect } from 'vitest';
import { apiUrl, wsUrl, API_BASE, normalizeBasePath } from './config';

describe('config url helpers', () => {
  it('apiUrl joins base and path without double slashes', () => {
    expect(apiUrl('/graphs')).toBe(`${API_BASE}/graphs`);
    expect(apiUrl('graphs')).toBe(`${API_BASE}/graphs`);
  });

  it('wsUrl uses ws/wss based on protocol and host', () => {
    const url = wsUrl('/pipeline/123');
    expect(url.startsWith('ws://') || url.startsWith('wss://')).toBe(true);
    expect(url).toContain(window.location.host);
    expect(url.endsWith('/pipeline/123')).toBe(true);
  });
});

describe('normalizeBasePath', () => {
  it('adds a leading slash and strips trailing slash', () => {
    expect(normalizeBasePath('app')).toBe('/app');
    expect(normalizeBasePath('/app/')).toBe('/app');
    expect(normalizeBasePath('/app')).toBe('/app');
  });

  it('returns empty string for root', () => {
    expect(normalizeBasePath('/')).toBe('');
    expect(normalizeBasePath('')).toBe('');
  });

  it('defaults to /app when undefined', () => {
    expect(normalizeBasePath(undefined)).toBe('/app');
  });

  it('never yields a relative (non-slash-prefixed) path', () => {
    for (const raw of ['app', 'x/y', '/deep/path/']) {
      expect(normalizeBasePath(raw).startsWith('/')).toBe(true);
    }
  });
});
