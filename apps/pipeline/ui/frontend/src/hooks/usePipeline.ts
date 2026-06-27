import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { startPipeline, startComparison, fetchPipelineStatus, fetchPipelineLogs, cancelPipeline } from '../api';
import { WsMessage } from './useWebSocket';

export interface PipelineStep {
  step: string;
  status: string;
  detail?: string;
  started_at?: string;
  finished_at?: string;
}

export interface LLMCost {
  total_cost: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cached_tokens: number;
  llm_calls: number;
}

export interface RunState {
  id: string;
  status: string;
  steps: PipelineStep[];
  logs: WsMessage[];
  cost: LLMCost | null;
  connected: boolean;
  isCancelling: boolean;
  config?: any;
  label?: string; // human-friendly tab label (folder, "g1 vs g2", etc.)
}

const SESSION_KEY = (type: string) => `p2k_runs_${type}`;
const ACTIVE_KEY = (type: string) => `p2k_active_${type}`;

function inferLabel(type: string, config: any | undefined): string | undefined {
  if (!config) return undefined;
  if (type === 'comparison') {
    if (config.g1 && config.g2) return `${config.g1} vs ${config.g2}`;
    return undefined;
  }
  if (config.folder) return config.folder;
  if (config.documents && config.documents.length > 0) {
    const first = String(config.documents[0]);
    const folder = first.includes('/') ? first.split('/')[0] : first;
    return config.documents.length > 1 ? `${folder} (${config.documents.length} files)` : folder;
  }
  return undefined;
}

function loadStoredIds(type: string): string[] {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY(type));
    if (!raw) return [];
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.filter(x => typeof x === 'string') : [];
  } catch { return []; }
}

function loadStoredActive(type: string): string | null {
  try { return sessionStorage.getItem(ACTIVE_KEY(type)); } catch { return null; }
}

function emptyRun(id: string): RunState {
  return {
    id, status: 'running', steps: [], logs: [], cost: null,
    connected: false, isCancelling: false,
  };
}

export function usePipeline(type: 'extraction' | 'comparison' = 'extraction') {
  const [runs, setRuns] = useState<Record<string, RunState>>(() => {
    const ids = loadStoredIds(type);
    const init: Record<string, RunState> = {};
    for (const id of ids) init[id] = emptyRun(id);
    return init;
  });
  const [activeRunId, setActiveRunIdState] = useState<string | null>(() => {
    const stored = loadStoredActive(type);
    if (stored && loadStoredIds(type).includes(stored)) return stored;
    const ids = loadStoredIds(type);
    return ids[ids.length - 1] || null;
  });

  const setActiveRunId = useCallback((id: string | null) => {
    setActiveRunIdState(id);
    try {
      if (id) sessionStorage.setItem(ACTIVE_KEY(type), id);
      else sessionStorage.removeItem(ACTIVE_KEY(type));
    } catch { /* ignore */ }
  }, [type]);

  // Persist run IDs whenever the registry changes
  useEffect(() => {
    const ids = Object.keys(runs);
    try {
      if (ids.length) sessionStorage.setItem(SESSION_KEY(type), JSON.stringify(ids));
      else sessionStorage.removeItem(SESSION_KEY(type));
    } catch { /* ignore */ }
  }, [runs, type]);

  // Functional updater that always sees fresh state — safe to call from
  // long-lived callbacks like WS onmessage and setInterval polls.
  const updateRun = useCallback((id: string, patch: Partial<RunState> | ((prev: RunState) => Partial<RunState>)) => {
    setRuns(prev => {
      const cur = prev[id];
      if (!cur) return prev;
      const p = typeof patch === 'function' ? (patch as (p: RunState) => Partial<RunState>)(cur) : patch;
      return { ...prev, [id]: { ...cur, ...p } };
    });
  }, []);

  const removeRunRef = useCallback((id: string) => {
    setRuns(prev => {
      if (!(id in prev)) return prev;
      const { [id]: _drop, ...rest } = prev;
      return rest;
    });
    setActiveRunIdState(prev => (prev === id ? null : prev));
  }, []);

  // Per-run WebSocket + polling lifecycle.
  // We track active sockets/intervals in refs so they survive re-renders and
  // are torn down only when their run leaves the registry.
  const wsRefs = useRef<Map<string, WebSocket>>(new Map());
  const pollRefs = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const lastLogIds = useRef<Map<string, number>>(new Map());
  const notifiedRefs = useRef<Set<string>>(new Set());
  const cancelledRefs = useRef<Set<string>>(new Set());

  const stopPolling = useCallback((id: string) => {
    const t = pollRefs.current.get(id);
    if (t) {
      clearInterval(t);
      pollRefs.current.delete(id);
    }
  }, []);

  const closeWs = useCallback((id: string) => {
    const ws = wsRefs.current.get(id);
    if (ws) {
      try { ws.close(); } catch { /* ignore */ }
      wsRefs.current.delete(id);
    }
  }, []);

  // Re-evaluated whenever the set of runIds changes
  const runIdsSig = Object.keys(runs).sort().join(',');

  useEffect(() => {
    const ids = Object.keys(runs);

    // --- spin up WS + poller for any new id ---
    for (const id of ids) {
      if (!wsRefs.current.has(id)) {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsBase = (import.meta.env.VITE_WS_BASE_PREFIX as string) ?? '';
        const ws = new WebSocket(`${proto}://${window.location.host}${wsBase}/ws/pipeline/${id}`);
        wsRefs.current.set(id, ws);

        ws.onopen = () => updateRun(id, { connected: true });
        ws.onclose = () => updateRun(id, { connected: false });
        // Surface socket errors instead of silently staying disconnected; the
        // HTTP poller below remains the source of truth for run status.
        ws.onerror = () => updateRun(id, { connected: false });
        ws.onmessage = (e) => {
          try {
            const msg: WsMessage = JSON.parse(e.data);
            updateRun(id, prev => {
              const next: Partial<RunState> = { logs: [...prev.logs, msg] };
              if (msg.type === 'status') {
                next.status = msg.status || 'completed';
              } else if (msg.type === 'cost') {
                next.cost = {
                  total_cost: msg.total_cost ?? 0,
                  total_prompt_tokens: msg.total_prompt_tokens ?? 0,
                  total_completion_tokens: msg.total_completion_tokens ?? 0,
                  total_cached_tokens: msg.total_cached_tokens ?? 0,
                  llm_calls: msg.llm_calls ?? 0,
                };
              }
              return next;
            });
          } catch { /* ignore non-json */ }
        };

        // Keep-alive
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 30000);
        ws.addEventListener('close', () => clearInterval(ping));
      }

      if (!pollRefs.current.has(id)) {
        const poll = async () => {
          try {
            const data = await fetchPipelineStatus(id);
            updateRun(id, prev => {
              const next: Partial<RunState> = { steps: data.steps };
              if (data.run.status !== 'running' && prev.status !== data.run.status) {
                next.status = data.run.status;
              }
              if (!prev.config && data.run.config) next.config = data.run.config;
              if (!prev.label) {
                const lbl = inferLabel(type, data.run.config);
                if (lbl) next.label = lbl;
              }
              const result = data.run?.result;
              if (result && result.total_cost != null && (!prev.cost || prev.cost.llm_calls === 0)) {
                next.cost = result;
              }
              return next;
            });
          } catch (err: any) {
            const msg = err?.message || '';
            if (msg.startsWith('404') || msg.includes('404')) {
              // Run no longer on server — remove from registry
              stopPolling(id);
              closeWs(id);
              removeRunRef(id);
              return;
            }
          }

          try {
            const lastId = lastLogIds.current.get(id) || 0;
            const logData = await fetchPipelineLogs(id, lastId);
            if (logData.logs && logData.logs.length > 0) {
              const newMsgs: WsMessage[] = logData.logs.map((l: any) => ({
                type: 'log' as const, level: l.level, message: l.message,
              }));
              lastLogIds.current.set(id, logData.logs[logData.logs.length - 1].id);
              updateRun(id, prev => ({ logs: [...prev.logs, ...newMsgs] }));
            }
          } catch { /* ignore */ }
        };

        // Kick off immediately, then every 1.5s while running
        poll();
        pollRefs.current.set(id, setInterval(poll, 1500));
      }
    }

    // --- tear down resources for runs no longer in the registry ---
    for (const id of Array.from(wsRefs.current.keys())) {
      if (!ids.includes(id)) closeWs(id);
    }
    for (const id of Array.from(pollRefs.current.keys())) {
      if (!ids.includes(id)) stopPolling(id);
    }
    // Note: we deliberately keep the run state (incl. terminal status) until
    // the user dismisses the tab. WS/polling stops below for terminal runs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runIdsSig]);

  // Stop polling for terminal runs (keep state for display) + browser notif
  useEffect(() => {
    for (const [id, run] of Object.entries(runs)) {
      const terminal = run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
      if (!terminal) continue;
      stopPolling(id);
      closeWs(id);
      if (notifiedRefs.current.has(id)) continue;
      notifiedRefs.current.add(id);
      const label = type === 'comparison' ? 'KG Joining' : 'KG Creation';
      const title = run.status === 'completed'
        ? `${label} Pipeline Completed`
        : `${label} Pipeline ${run.status.charAt(0).toUpperCase() + run.status.slice(1)}`;
      const body = run.status === 'completed'
        ? `Run ${run.label || id.slice(0, 8)} finished successfully!`
        : `Run ${run.label || id.slice(0, 8)} ended.`;
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body, icon: '/favicon.ico' });
      } else if ('Notification' in window && Notification.permission !== 'denied') {
        Notification.requestPermission().then(p => {
          if (p === 'granted') new Notification(title, { body, icon: '/favicon.ico' });
        });
      }
    }
  }, [runs, type, stopPolling, closeWs]);

  // Cleanup on unmount: close all sockets and intervals
  useEffect(() => {
    return () => {
      for (const id of Array.from(wsRefs.current.keys())) {
        try { wsRefs.current.get(id)?.close(); } catch { /* ignore */ }
      }
      wsRefs.current.clear();
      for (const t of pollRefs.current.values()) clearInterval(t);
      pollRefs.current.clear();
    };
  }, []);

  const launch = useCallback(async (config: any) => {
    const res = type === 'comparison'
      ? await startComparison(config)
      : await startPipeline(config);

    let stepIds: string[];
    if (type === 'comparison') {
      stepIds = ['7', '8', '9', '10'];
    } else if (config.step) {
      stepIds = [String(config.step)];
    } else {
      stepIds = ['1', '2', '3', '3.5', '4', '5', '6'];
    }

    const newRun: RunState = {
      id: res.run_id,
      status: 'running',
      steps: stepIds.map(s => ({ step: s, status: 'pending' })),
      logs: [],
      cost: null,
      connected: false,
      isCancelling: false,
      config,
      label: inferLabel(type, config),
    };

    setRuns(prev => ({ ...prev, [res.run_id]: newRun }));
    setActiveRunId(res.run_id);
    return res.run_id;
  }, [type, setActiveRunId]);

  const cancel = useCallback(async (id?: string) => {
    const target = id || activeRunId;
    if (!target) return;
    if (cancelledRefs.current.has(target)) return;
    cancelledRefs.current.add(target);
    updateRun(target, prev => ({
      status: 'cancelling',
      isCancelling: true,
      logs: [...prev.logs, { type: 'log' as const, level: 'WARN', message: '⏹ Cancellation requested — stopping pipeline...' }],
    }));
    try {
      await cancelPipeline(target);
    } catch (err) {
      // The cancel request itself failed — don't claim success. Allow a retry.
      cancelledRefs.current.delete(target);
      const message = err instanceof Error ? err.message : String(err);
      updateRun(target, prev => ({
        isCancelling: false,
        logs: [...prev.logs, { type: 'log' as const, level: 'ERROR', message: `⚠ Cancellation failed: ${message}. You can try again.` }],
      }));
      return;
    }
    updateRun(target, prev => ({
      status: 'cancelled',
      isCancelling: false,
      logs: [...prev.logs, { type: 'log' as const, level: 'WARN', message: '✅ Pipeline cancelled successfully.' }],
    }));
  }, [activeRunId, updateRun]);

  const dismiss = useCallback((id: string) => {
    stopPolling(id);
    closeWs(id);
    lastLogIds.current.delete(id);
    notifiedRefs.current.delete(id);
    cancelledRefs.current.delete(id);
    setRuns(prev => {
      if (!(id in prev)) return prev;
      const { [id]: _drop, ...rest } = prev;
      return rest;
    });
    setActiveRunIdState(prev => {
      if (prev !== id) return prev;
      return null; // caller / effect can pick a new tab if desired
    });
  }, [stopPolling, closeWs]);

  // Auto-pick a new active tab when the current one is dismissed
  useEffect(() => {
    if (activeRunId && runs[activeRunId]) return;
    const ids = Object.keys(runs);
    if (ids.length === 0) {
      if (activeRunId !== null) setActiveRunIdState(null);
      try { sessionStorage.removeItem(ACTIVE_KEY(type)); } catch { /* ignore */ }
      return;
    }
    const next = ids[ids.length - 1];
    setActiveRunIdState(next);
    try { sessionStorage.setItem(ACTIVE_KEY(type), next); } catch { /* ignore */ }
  }, [activeRunId, runs, type]);

  // Backward-compatible "active run" view for callers that haven't been
  // updated yet (Compare.tsx). These mirror the previous single-run API.
  const active: RunState | null = activeRunId ? runs[activeRunId] || null : null;
  const runList = useMemo(() => Object.values(runs), [runs]);

  const legacyCancel = useCallback(() => cancel(undefined), [cancel]);

  return {
    // New multi-run API
    runs: runList,
    runsById: runs,
    activeRunId,
    setActiveRunId,
    launch,
    cancel,
    dismiss,
    // Backward-compat (active run shortcuts)
    runId: active?.id ?? null,
    status: active?.status ?? 'idle',
    steps: active?.steps ?? [],
    logs: active?.logs ?? [],
    cost: active?.cost ?? null,
    connected: active?.connected ?? false,
    isCancelling: active?.isCancelling ?? false,
    legacyCancel,
  };
}
