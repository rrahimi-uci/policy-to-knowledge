import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CommandPalette from './CommandPalette';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async (orig) => {
  const actual = await (orig() as Promise<Record<string, unknown>>);
  return { ...actual, useNavigate: () => navigateMock };
});

function renderPalette() {
  return render(
    <MemoryRouter>
      <CommandPalette />
    </MemoryRouter>
  );
}

function openPalette() {
  fireEvent.keyDown(window, { key: 'k', metaKey: true });
}

beforeEach(() => {
  navigateMock.mockReset();
  // jsdom does not implement scrollIntoView (used to keep the active row visible)
  Element.prototype.scrollIntoView = vi.fn();
  global.fetch = vi.fn(async (url: string) => {
    const u = String(url);
    const body = u.includes('graphs')
      ? { graphs: [{ name: 'alpha_bank', provider: 'openai', rules: 5, entities: 2 }] }
      : u.includes('documents')
      ? { subdirectories: [{ name: 'alpha_docs', file_count: 3 }] }
      : { runs: [{ id: 'abcd1234ef', domain: 'alpha', status: 'completed', provider: 'openai', documents: ['x.pdf'] }] };
    return { json: async () => body } as Response;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CommandPalette interactions', () => {
  it('is hidden until Cmd+K, then shows the pages list', async () => {
    renderPalette();
    expect(screen.queryByRole('dialog')).toBeNull();
    openPalette();
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByText('Dashboard')).toBeTruthy();
    expect(screen.getByText('Compare Graphs')).toBeTruthy();
  });

  it('Escape closes the palette', async () => {
    renderPalette();
    openPalette();
    await screen.findByRole('dialog');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('arrow-down + Enter navigates to the highlighted route', async () => {
    renderPalette();
    openPalette();
    const input = await screen.findByPlaceholderText(/Search graphs/i);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(navigateMock).toHaveBeenCalledTimes(1);
  });

  it('clicking a result navigates to its route', async () => {
    renderPalette();
    openPalette();
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByText('Settings'));
    expect(navigateMock).toHaveBeenCalledWith('/extraction/settings');
  });

  it('typing a query filters pages and merges fetched graph/doc/run results', async () => {
    renderPalette();
    openPalette();
    const input = await screen.findByPlaceholderText(/Search graphs/i);
    fireEvent.change(input, { target: { value: 'alpha' } });
    // Debounced fetch (200ms) then merged results render
    expect(await screen.findByText('alpha bank')).toBeTruthy();   // graph (underscores → spaces)
    expect(screen.getByText('alpha_docs')).toBeTruthy();          // document
    expect(screen.getByText(/Run abcd1234/)).toBeTruthy();        // run
    expect(global.fetch).toHaveBeenCalled();
  });

  it('shows an empty state for a query with no matches', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockImplementation(async () => ({
      json: async () => ({ graphs: [], subdirectories: [], runs: [] }),
    }));
    renderPalette();
    openPalette();
    const input = await screen.findByPlaceholderText(/Search graphs/i);
    fireEvent.change(input, { target: { value: 'zzzzznomatch' } });
    expect(await screen.findByText(/No results for/i)).toBeTruthy();
  });
});
