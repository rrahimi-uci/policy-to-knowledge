import { describe, it, expect } from 'vitest';
import { isLinkActive } from './Sidebar';

describe('isLinkActive', () => {
  it('matches the home route only on exact "/"', () => {
    expect(isLinkActive('/', '/')).toBe(true);
    expect(isLinkActive('/analytics', '/')).toBe(false);
  });

  it('matches exact paths', () => {
    expect(isLinkActive('/obligations', '/obligations')).toBe(true);
  });

  it('matches nested paths on a segment boundary', () => {
    expect(isLinkActive('/extraction/runs', '/extraction')).toBe(true);
  });

  it('does NOT match a path that merely shares a prefix (regression)', () => {
    expect(isLinkActive('/obligations-archive', '/obligations')).toBe(false);
    expect(isLinkActive('/extraction-foo', '/extraction')).toBe(false);
  });
});
