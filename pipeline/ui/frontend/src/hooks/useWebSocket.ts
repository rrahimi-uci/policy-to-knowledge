import { useEffect, useRef, useState, useCallback } from 'react';

export interface WsMessage {
  type: 'log' | 'status' | 'cost';
  level?: string;
  message?: string;
  step?: string;
  status?: string;
  // Cost fields (type === 'cost')
  total_cost?: number;
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_cached_tokens?: number;
  llm_calls?: number;
}

export function usePipelineWs(runId: string | null) {
  const [messages, setMessages] = useState<WsMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runId) return;
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsBase = (import.meta.env.VITE_WS_BASE_PREFIX as string) ?? '';
    const ws = new WebSocket(`${proto}://${window.location.host}${wsBase}/ws/pipeline/${runId}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const msg: WsMessage = JSON.parse(e.data);
        setMessages(prev => [...prev, msg]);
      } catch { /* ignore non-json */ }
    };

    // Keep alive ping every 30s
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 30000);

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, [runId]);

  const clear = useCallback(() => setMessages([]), []);
  return { messages, connected, clear };
}
