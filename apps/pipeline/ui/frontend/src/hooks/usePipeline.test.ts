import { describe, it, expect } from 'vitest';
import { inferLabel } from './usePipeline';

describe('inferLabel', () => {
  it('returns "g1 vs g2" for comparison runs', () => {
    expect(inferLabel('comparison', { g1: 'A', g2: 'B' })).toBe('A vs B');
    expect(inferLabel('comparison', { g1: 'A' })).toBeUndefined();
  });

  it('uses an explicit folder when present', () => {
    expect(inferLabel('extraction', { folder: 'mortgage' })).toBe('mortgage');
  });

  it('derives the folder from the first document path', () => {
    expect(inferLabel('extraction', { documents: ['mortgage/a.pdf'] })).toBe('mortgage');
  });

  it('counts multiple documents', () => {
    expect(inferLabel('extraction', { documents: ['m/a.pdf', 'm/b.pdf', 'm/c.pdf'] }))
      .toBe('m (3 files)');
  });

  it('handles leading-slash paths without an empty folder label (regression)', () => {
    expect(inferLabel('extraction', { documents: ['/abs/a.pdf', '/abs/b.pdf'] }))
      .toBe('abs (2 files)');
  });

  it('returns undefined when there is nothing to label', () => {
    expect(inferLabel('extraction', undefined)).toBeUndefined();
    expect(inferLabel('extraction', {})).toBeUndefined();
  });
});
