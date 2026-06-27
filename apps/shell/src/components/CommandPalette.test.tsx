import { describe, it, expect } from 'vitest';
import { Network } from 'lucide-react';
import { flattenGrouped, CATEGORY_ORDER, type SearchResult } from './CommandPalette';

function r(id: string, category: SearchResult['category']): SearchResult {
  return { id, label: id, description: '', category, route: `/${id}`, icon: Network };
}

describe('flattenGrouped', () => {
  it('orders results by CATEGORY_ORDER regardless of input order', () => {
    const input = [r('run1', 'run'), r('page1', 'page'), r('graph1', 'graph'), r('doc1', 'document')];
    const ordered = flattenGrouped(input).map((x) => x.id);
    expect(ordered).toEqual(['page1', 'graph1', 'doc1', 'run1']);
  });

  it('keeps stable order within a category', () => {
    const input = [r('p1', 'page'), r('g1', 'graph'), r('p2', 'page')];
    const ordered = flattenGrouped(input).map((x) => x.id);
    // p1 then p2 (stable), then g1
    expect(ordered).toEqual(['p1', 'p2', 'g1']);
  });

  it('flattened order matches what keyboard nav and render both index into', () => {
    // Interleaved categories used to desync nav (flat insertion order) from the
    // grouped render. flattenGrouped is the single source of truth now.
    const input = [r('page1', 'page'), r('graph1', 'graph'), r('page2', 'page')];
    const ordered = flattenGrouped(input);
    // The element at each index is unambiguous and grouped.
    expect(ordered.map((x) => x.category)).toEqual(['page', 'page', 'graph']);
  });

  it('CATEGORY_ORDER covers the known categories', () => {
    expect(CATEGORY_ORDER).toEqual(['page', 'graph', 'document', 'run']);
  });

  it('appends results with unknown categories at the end', () => {
    const weird = { ...r('x', 'page'), category: 'mystery' as SearchResult['category'] };
    const ordered = flattenGrouped([r('p', 'page'), weird]);
    expect(ordered[ordered.length - 1].id).toBe('x');
  });
});
