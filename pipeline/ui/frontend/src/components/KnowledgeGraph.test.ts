import { describe, it, expect } from 'vitest';
import { lighten } from './KnowledgeGraph';

describe('lighten()', () => {
  it('lightens a valid hex color toward white', () => {
    // black -> 40% white mix = #666666
    expect(lighten('#000000')).toBe('#666666');
    // white stays white
    expect(lighten('#ffffff')).toBe('#ffffff');
  });

  it('returns a valid hex for malformed input instead of "#nan…"', () => {
    for (const bad of ['', 'red', '#fff', '#zzzzzz', undefined as unknown as string]) {
      const out = lighten(bad);
      expect(out).toMatch(/^#[0-9a-f]{6}$/i);
      expect(out).not.toContain('nan');
    }
  });
});
