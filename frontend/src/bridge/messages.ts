/**
 * PostMessage bridge for communication between the Policy to Knowledge shell
 * and embedded micro-frontends (KG Extraction, Assistant).
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

/** Send a message to an iframe */
export function postToFrame(frame: HTMLIFrameElement | null, msg: Omit<BridgeMessage, 'source'>) {
  frame?.contentWindow?.postMessage({ ...msg, source: 'p2k-suite' }, '*');
}

/** Send a theme-change message to an iframe */
export function syncThemeToFrame(frame: HTMLIFrameElement | null, theme: 'dark' | 'light') {
  postToFrame(frame, { type: 'theme-change', payload: { theme } });
}

/** Listen for messages from child iframes */
export function onChildMessage(
  callback: (msg: BridgeMessage) => void,
): () => void {
  const handler = (event: MessageEvent) => {
    const data = event.data as BridgeMessage;
    if (data?.source === 'kg-extraction' || data?.source === 'assistant') {
      callback(data);
    }
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}
