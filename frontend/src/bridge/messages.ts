/**
 * PostMessage bridge for communication between the Policy to Knowledge shell
 * and embedded micro-frontends (KG Extraction, Assistant).
 *
 * Both directions are origin-checked: outbound messages target the iframe's
 * own origin (never the "*" wildcard, which would leak payloads to whatever
 * page the frame happens to host), and inbound messages are validated against
 * an allowlist before the callback runs.
 */

export type MessageType =
  | 'theme-change'
  | 'navigate'
  | 'load-graph'
  | 'status-request'
  | 'status-response';

export interface BridgeMessage {
  source: 'p2k-suite' | 'kg-extraction' | 'assistant';
  type: MessageType;
  payload: Record<string, unknown>;
}

/** Origins we trust to exchange bridge messages with. */
function allowedOrigins(): Set<string> {
  const origins = new Set<string>([window.location.origin]);
  for (const raw of [
    import.meta.env.VITE_CA_URL as string | undefined,
    import.meta.env.VITE_KG_FRONTEND_URL as string | undefined,
  ]) {
    if (raw) {
      try {
        origins.add(new URL(raw, window.location.origin).origin);
      } catch {
        /* ignore malformed env URLs */
      }
    }
  }
  return origins;
}

/** Resolve the target origin for an iframe from its current src. */
function frameOrigin(frame: HTMLIFrameElement | null): string | null {
  if (!frame?.src) return null;
  try {
    return new URL(frame.src, window.location.origin).origin;
  } catch {
    return null;
  }
}

/** Send a message to an iframe (targets the frame's own origin). */
export function postToFrame(frame: HTMLIFrameElement | null, msg: Omit<BridgeMessage, 'source'>) {
  const target = frameOrigin(frame);
  if (!frame?.contentWindow || !target) return;
  frame.contentWindow.postMessage({ ...msg, source: 'p2k-suite' }, target);
}

/** Send a theme-change message to an iframe */
export function syncThemeToFrame(frame: HTMLIFrameElement | null, theme: 'dark' | 'light') {
  postToFrame(frame, { type: 'theme-change', payload: { theme } });
}

/** Listen for messages from child iframes */
export function onChildMessage(
  callback: (msg: BridgeMessage) => void,
): () => void {
  const allowed = allowedOrigins();
  const handler = (event: MessageEvent) => {
    if (!allowed.has(event.origin)) return;
    const data = event.data as BridgeMessage;
    if (data?.source === 'kg-extraction' || data?.source === 'assistant') {
      callback(data);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}
