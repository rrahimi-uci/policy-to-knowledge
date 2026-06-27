import { describe, it, expect, vi, afterEach } from 'vitest';
import { onChildMessage, postToFrame } from './messages';

describe('bridge/messages origin checks', () => {
  afterEach(() => vi.restoreAllMocks());

  it('ignores messages from disallowed origins', () => {
    const cb = vi.fn();
    const off = onChildMessage(cb);
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: 'https://evil.example.com',
        data: { source: 'assistant', type: 'navigate', payload: {} },
      }),
    );
    expect(cb).not.toHaveBeenCalled();
    off();
  });

  it('accepts messages from the same origin with a known child source', () => {
    const cb = vi.fn();
    const off = onChildMessage(cb);
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        data: { source: 'kg-extraction', type: 'navigate', payload: { route: '/x' } },
      }),
    );
    expect(cb).toHaveBeenCalledTimes(1);
    off();
  });

  it('ignores same-origin messages with an unknown source', () => {
    const cb = vi.fn();
    const off = onChildMessage(cb);
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        data: { source: 'somebody-else', type: 'navigate', payload: {} },
      }),
    );
    expect(cb).not.toHaveBeenCalled();
    off();
  });

  it('postToFrame targets the frame origin, never the "*" wildcard', () => {
    const postMessage = vi.fn();
    const frame = {
      src: `${window.location.origin}/app/`,
      contentWindow: { postMessage },
    } as unknown as HTMLIFrameElement;
    postToFrame(frame, { type: 'theme-change', payload: { theme: 'dark' } });
    expect(postMessage).toHaveBeenCalledTimes(1);
    const targetOrigin = postMessage.mock.calls[0][1];
    expect(targetOrigin).toBe(window.location.origin);
    expect(targetOrigin).not.toBe('*');
  });
});
