import { describe, it, expect } from 'vitest';
import { apiUrl, wsUrl, API_BASE } from './config';

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
