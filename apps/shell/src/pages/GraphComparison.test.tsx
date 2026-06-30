import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import GraphComparison from './GraphComparison';

/**
 * Regression for the `justFinished` stale-closure bug in connectWs().
 *
 * The websocket `onclose` handler used to read the `justFinished` state value
 * captured when connectWs() was created (always `false`). When the comparison
 * pipeline finished, the server sends a "done" message (which starts a 1.5s
 * "Comparison complete!" transition) and then closes the socket. With the stale
 * closure, onclose saw justFinished === false and immediately flipped `running`
 * off, skipping the transition. The fix mirrors the flag into a ref so onclose
 * reads the live value.
 */

/** Minimal controllable WebSocket stand-in. */
class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  url: string;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.last = this;
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.();
  }
  // Test helpers
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.last = null;
  // @ts-expect-error override global for the test
  globalThis.WebSocket = FakeWebSocket;
  globalThis.fetch = vi.fn(async (url: string | URL) => {
    const u = String(url);
    if (u.includes('kg/graphs/')) return { ok: true, json: async () => ({}) } as Response;
    if (u.includes('kg/graphs')) {
      return {
        ok: true,
        json: async () => ({
          graphs: [
            { name: 'mortgage_a', provider: 'openai', rules: 3, entities: 1, domain: 'mortgage' },
            { name: 'mortgage_b', provider: 'openai', rules: 4, entities: 2, domain: 'mortgage' },
          ],
        }),
      } as Response;
    }
    if (u.includes('kg/compare') && u.includes('/data')) {
      return { ok: true, json: async () => ({}) } as Response;
    }
    if (u.includes('kg/compare')) {
      // POST returns a run id; GET returns the (empty) comparison list.
      return { ok: true, json: async () => ({ comparisons: [], run_id: 'run-1' }) } as Response;
    }
    return { ok: true, json: async () => ({}) } as Response;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function selectBothGraphsAndRun() {
  render(<GraphComparison />);
  // Let the initial graph/comparison fetches resolve.
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });

  const [selectA, selectB] = screen.getAllByRole('combobox') as HTMLSelectElement[];
  fireEvent.change(selectA, { target: { value: 'mortgage_a' } });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  fireEvent.change(selectB, { target: { value: 'mortgage_b' } });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });

  fireEvent.click(screen.getByRole('button', { name: /Run Semantic Comparison/i }));
  // runComparison POSTs then connects the socket.
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe('GraphComparison pipeline finish transition', () => {
  it('keeps the "Comparison complete!" transition after the socket closes on done', async () => {
    await selectBothGraphsAndRun();

    const ws = FakeWebSocket.last;
    expect(ws).toBeTruthy();

    // The pipeline-progress panel is shown while running.
    expect(screen.getByText(/Comparing Knowledge Graphs/i)).toBeInTheDocument();

    // Server signals completion, then closes the socket in the same tick.
    await act(async () => {
      ws!.emit({ step: 'done', status: 'completed' });
      ws!.close();
      await Promise.resolve();
    });

    // With the fix, onclose sees justFinished === true and leaves `running`
    // on, so the progress panel stays up and the "no comparison" empty state
    // does NOT flash. (Pre-fix, the stale closure dropped `running` here and
    // the empty CTA appeared immediately.)
    expect(screen.getByText(/Comparing Knowledge Graphs/i)).toBeInTheDocument();
    expect(screen.queryByText(/No comparison found for this pair/i)).toBeNull();

    // After the 1.5s graceful transition, `running` clears.
    await act(async () => { vi.advanceTimersByTime(1600); await Promise.resolve(); });
    expect(screen.queryByText(/Comparing Knowledge Graphs/i)).toBeNull();
  });
});
