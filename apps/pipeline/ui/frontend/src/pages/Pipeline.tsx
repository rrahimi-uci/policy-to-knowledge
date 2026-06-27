import { useState, useEffect, useRef } from 'react';
import { usePipeline } from '../hooks/usePipeline';
import type { LLMCost, RunState } from '../hooks/usePipeline';
import { fetchDocuments, fetchSubdirFiles, fetchGraphs, fetchRunningPipelines, fetchPipelineHistory } from '../api';
import WorkflowDiagram from '../components/WorkflowDiagram';
import LogViewer from '../components/LogViewer';
import type { WsMessage } from '../hooks/useWebSocket';
import { useLocation } from 'react-router-dom';
import { useEmbeddedNavigate } from '../hooks/useEmbeddedNavigate';
import {
  Play, Square, CheckCircle, XCircle, FolderOpen, X, FileText,
  ChevronDown, ChevronUp, ChevronRight, Terminal,
  Network, GitCompareArrows, Loader2, AlertTriangle, Clock, RotateCcw,
} from 'lucide-react';

/** Same naming conventions as Documents.tsx + Dashboard.tsx */
function getFolderDomain(name: string): string {
  const l = name.toLowerCase();
  const normalized = l.replace(/[-\s]+/g, '_');
  if (
    normalized.startsWith('p2k') ||
    normalized.startsWith('mortgage') ||
    normalized.includes('sample_guidelines') ||
    normalized.includes('example_policies')
  ) return 'mortgage';
  if (l.startsWith('aml') || l.includes('anti_money') || l.includes('anti-money')) return 'aml';
  if (l.startsWith('healthcare') || l.startsWith('cms') || l.includes('hipaa') || l.includes('medicare') || l.includes('medicaid')) return 'healthcare';
  if (l.includes('lending') || l.includes('commercial') || l.includes('comercial')) return 'commercial_lending';
  return '';
}

function resolveFolderDomain(folder: { name: string; domain?: string | null } | string): string {
  if (typeof folder === 'string') return getFolderDomain(folder);
  return folder.domain || getFolderDomain(folder.name);
}

interface Subdir { name: string; file_count: number; domain?: string | null; }
interface DocFile { name: string; relative_path: string; size: number; extension: string; }
interface GraphInfo { name: string; rules?: number; entities?: number; }

/* ================================================================== */
/*  Shared log viewer section                                         */
/* ================================================================== */

function LogSection({
  status,
  logs,
}: {
  status: string;
  logs: WsMessage[];
}) {
  const hasErrors = logs.some(l => l.level === 'ERROR');
  const isRunning = status === 'running';
  const [open, setOpen] = useState(isRunning || hasErrors);

  // Auto-open when pipeline starts running; stay open once opened
  useEffect(() => {
    if (isRunning || hasErrors) setOpen(true);
  }, [isRunning, hasErrors]);

  const lineCount = logs.filter(l => l.type === 'log').length;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-6 py-3 select-none"
      >
        <div className="flex items-center gap-2">
          <Terminal size={16} className={hasErrors ? 'text-red-400' : isRunning ? 'text-blue-400' : 'text-gray-400'} />
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
            Live Output
          </h3>
          {lineCount > 0 && (
            <span className="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">
              {lineCount} lines
            </span>
          )}
          {hasErrors && (
            <span className="text-[10px] bg-red-500/20 text-red-400 px-2 py-0.5 rounded-full">
              errors
            </span>
          )}
          {isRunning && !hasErrors && (
            <span className="text-[10px] bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded-full animate-pulse">
              live
            </span>
          )}
        </div>
        {open
          ? <ChevronUp size={16} className="text-gray-500" />
          : <ChevronDown size={16} className="text-gray-500" />
        }
      </button>
      {open && (
        <div className="px-6 pb-4">
          <LogViewer logs={logs} />
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Status badge                                                       */
/* ================================================================== */

function StatusBanner({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <div className="flex items-center gap-2 text-sm">
        <CheckCircle size={18} className="text-green-400" />
        <span className="text-green-400">Pipeline completed successfully</span>
      </div>
    );
  }
  if (status === 'cancelling') {
    return (
      <div className="flex items-center gap-2 text-sm">
        <Loader2 size={18} className="text-amber-400 animate-spin" />
        <span className="text-amber-400">Cancelling pipeline...</span>
      </div>
    );
  }
  if (status === 'failed' || status === 'cancelled') {
    return (
      <div className="flex items-center gap-2 text-sm">
        <XCircle size={18} className="text-red-400" />
        <span className="text-red-400">Pipeline {status}</span>
      </div>
    );
  }
  return null;
}

/* ================================================================== */
/*  LLM Cost display                                                   */
/* ================================================================== */

function formatCost(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function CostBanner({ cost, isRunning }: { cost: LLMCost | null; isRunning?: boolean }) {
  if (!cost || cost.llm_calls === 0) return null;
  return (
    <div className="flex items-center gap-4 px-4 py-2.5 bg-gray-900/60 border border-gray-800/60 rounded-xl text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-gray-500">LLM Cost</span>
        <span className="font-mono font-semibold text-emerald-400">{formatCost(cost.total_cost)}</span>
        {isRunning && <span className="text-gray-600 animate-pulse">●</span>}
      </div>
      <span className="text-gray-700">|</span>
      <div className="flex items-center gap-3 text-gray-400">
        <span title="LLM API calls">{cost.llm_calls} calls</span>
        <span title="Prompt tokens">{formatTokens(cost.total_prompt_tokens)} prompt</span>
        <span title="Completion tokens">{formatTokens(cost.total_completion_tokens)} completion</span>
        {cost.total_cached_tokens > 0 && (
          <span title="Cached tokens (saved)" className="text-blue-400">
            {formatTokens(cost.total_cached_tokens)} cached
          </span>
        )}
      </div>
    </div>
  );
}

const DOMAINS = [
  { value: 'mortgage', label: 'Mortgage' },
  { value: 'aml', label: 'AML' },
  { value: 'healthcare', label: 'Healthcare' },
  { value: 'commercial_lending', label: 'Commercial Lending' },
];

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
];

const STEP_LABELS: Record<number, string> = {
  1: 'Document Segmentation & Organization',
  2: 'Domain Entity & Relationship Discovery',
  3: 'Business Rules Extraction',
  4: 'Rules & Entity Integration',
  5: 'Knowledge Graph Deduplication & Optimization',
  6: 'Graph Visualization & Export',
};

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/* ================================================================== */
/*  Run History Panel — restart any past run                           */
/* ================================================================== */

interface HistoryRun {
  id: string;
  type: string;
  status: string;
  domain?: string;
  provider?: string;
  config: any;
  documents: string[];
  started_at?: string;
  finished_at?: string;
  created_at?: string;
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (Number.isNaN(diff)) return '';
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const dd = Math.floor(h / 24);
  if (dd < 30) return `${dd}d ago`;
  return d.toLocaleDateString();
}

function historyLabel(type: string, run: HistoryRun): string {
  if (type === 'comparison') {
    const c = run.config || {};
    if (c.g1 && c.g2) return `${c.g1} vs ${c.g2}`;
    return run.id.slice(0, 8);
  }
  const c = run.config || {};
  if (c.folder) return c.folder;
  if (run.documents && run.documents.length > 0) {
    const first = String(run.documents[0]);
    const folder = first.includes('/') ? first.split('/')[0] : first;
    return run.documents.length > 1 ? `${folder} (${run.documents.length} files)` : folder;
  }
  return run.id.slice(0, 8);
}

function HistoryPanel({
  type,
  trackedRunIds,
  onRestart,
  refreshKey,
}: {
  type: 'extraction' | 'comparison';
  trackedRunIds: string[];
  onRestart: (run: HistoryRun) => void;
  refreshKey: number;
}) {
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPipelineHistory(type, 25)
      .then((data: { runs?: HistoryRun[] }) => {
        if (!cancelled) setHistory(data.runs || []);
      })
      .catch(() => { if (!cancelled) setHistory([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [type, refreshKey]);

  // Hide runs that are already represented by an active tab so we don't
  // duplicate the per-tab Restart action.
  const trackedSet = new Set(trackedRunIds);
  const visible = history.filter(r => !trackedSet.has(r.id));

  if (!loading && visible.length === 0) return null;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 select-none"
      >
        <div className="flex items-center gap-2">
          <Clock size={14} className="text-gray-400" />
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Recent Runs
          </span>
          {!loading && (
            <span className="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">
              {visible.length}
            </span>
          )}
        </div>
        {open
          ? <ChevronUp size={16} className="text-gray-500" />
          : <ChevronDown size={16} className="text-gray-500" />
        }
      </button>
      {open && (
        <div className="px-5 pb-4 border-t border-gray-800">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 size={16} className="animate-spin text-blue-400" />
            </div>
          ) : (
            <div className="divide-y divide-gray-800/60 max-h-80 overflow-y-auto -mx-1">
              {visible.map(r => {
                const label = historyLabel(type, r);
                const canRestart = !!(r.config && Object.keys(r.config).length > 0);
                return (
                  <div key={r.id} className="flex items-center gap-3 px-1 py-2.5">
                    <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(r.status)}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-200 truncate" title={r.id}>{label}</p>
                      <p className="text-[11px] text-gray-500 flex items-center gap-2">
                        <span className="uppercase tracking-wider">{r.status}</span>
                        {r.finished_at && <span>· finished {formatRelativeTime(r.finished_at)}</span>}
                        {!r.finished_at && r.started_at && <span>· started {formatRelativeTime(r.started_at)}</span>}
                        {r.domain && <span>· {r.domain}</span>}
                      </p>
                    </div>
                    <button type="button"
                      onClick={() => {
                        setPendingId(r.id);
                        // Clear pending after parent handler resolves; use a short fallback timer
                        // because onRestart is fire-and-forget here.
                        try { onRestart(r); } finally {
                          setTimeout(() => setPendingId(curr => (curr === r.id ? null : curr)), 1500);
                        }
                      }}
                      disabled={!canRestart || pendingId === r.id}
                      title={canRestart ? 'Re-run with the same configuration (creates a new tab)' : 'Original configuration is unavailable'}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-[0.95] ${
                        pendingId === r.id
                          ? (type === 'comparison' ? 'bg-purple-700 cursor-wait text-white' : 'bg-blue-700 cursor-wait text-white')
                          : canRestart
                          ? (type === 'comparison' ? 'bg-purple-600 hover:bg-purple-500 text-white' : 'bg-blue-600 hover:bg-blue-500 text-white')
                          : 'bg-gray-800 text-gray-500 cursor-not-allowed'
                      }`}
                    >
                      {pendingId === r.id
                        ? <Loader2 size={12} className="animate-spin" />
                        : <RotateCcw size={12} />}
                      {pendingId === r.id ? 'Starting…' : 'Restart'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Run Tabs (one tab per active/recent run)                           */
/* ================================================================== */

function statusDot(status: string): string {
  if (status === 'running') return 'bg-blue-400 animate-pulse';
  if (status === 'cancelling') return 'bg-amber-400 animate-pulse';
  if (status === 'completed') return 'bg-green-400';
  if (status === 'failed') return 'bg-red-400';
  if (status === 'cancelled') return 'bg-gray-400';
  return 'bg-gray-500';
}

function RunTabs({
  runs, activeRunId, setActiveRunId, dismiss,
}: {
  runs: RunState[];
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  dismiss: (id: string) => void;
}) {
  if (runs.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto bg-gray-900 border border-gray-800 rounded-xl p-1.5">
      {runs.map(r => {
        const active = r.id === activeRunId;
        const label = r.label || r.id.slice(0, 8);
        const terminal = r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled';
        return (
          <div key={r.id}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors ${
              active
                ? 'bg-blue-500/15 border border-blue-500/40 text-blue-200'
                : 'bg-gray-800/60 border border-gray-700/60 text-gray-300 hover:border-gray-600'
            }`}
          >
            <button type="button" onClick={() => setActiveRunId(r.id)} className="flex items-center gap-2 min-w-0">
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${statusDot(r.status)}`} />
              <span className="truncate max-w-[200px]" title={`${label} • ${r.status} • ${r.id}`}>{label}</span>
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">{r.status}</span>
            </button>
            {terminal && (
              <button type="button" onClick={(e) => { e.stopPropagation(); dismiss(r.id); }}
                title="Dismiss"
                className="text-gray-500 hover:text-gray-200"
              >
                <X size={12} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ================================================================== */
/*  KG Creation Pipeline (Steps 1-6)                                   */
/* ================================================================== */

function CreationPipeline({
  domain, setDomain,
  provider,
  preselectedFolder,
  preselectedFile,
}: {
  domain: string; setDomain: (d: string) => void;
  provider: string;
  preselectedFolder?: string | null;
  preselectedFile?: string | null;
}) {
  const { runs, activeRunId, setActiveRunId, launch, cancel, dismiss } = usePipeline('extraction');
  const activeRun = runs.find(r => r.id === activeRunId) || null;
  const nav = useEmbeddedNavigate();

  const handleCancel = (id: string) => {
    if (window.confirm('Are you sure you want to cancel the running pipeline? This cannot be undone.')) {
      cancel(id);
    }
  };
  const startRef = useRef<HTMLDivElement>(null);

  // ── Running pipelines (global, from server) ─────────────────────
  const [runningFolders, setRunningFolders] = useState<Map<string, string>>(new Map());
  const runningPollRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [isStarting, setIsStarting] = useState(false);

  const handleRestart = (run: { id: string; config?: any }) => {
    if (!run.config || Object.keys(run.config).length === 0) {
      window.alert('Cannot restart — original configuration is no longer available for this run.');
      return;
    }
    const folder = run.config?.folder;
    if (folder && runningFolders.has(folder) && runningFolders.get(folder) !== run.id) {
      window.alert(`A pipeline is already running for "${folder}". Wait for it to finish before restarting.`);
      return;
    }
    if (!window.confirm('Restart this pipeline from scratch with the same configuration? A new run tab will be created.')) return;
    setIsStarting(true);
    launch(run.config)
      .then(() => setHistoryRefresh(k => k + 1))
      .catch(err => window.alert(`Failed to start: ${err?.message || err}`))
      .finally(() => setIsStarting(false));
  };

  useEffect(() => {
    const loadRunning = () => {
      fetchRunningPipelines()
        .then((data: { runs?: any[] }) => {
          const m = new Map<string, string>();
          for (const r of data.runs || []) {
            const folder = r.config?.folder;
            if (folder && r.status === 'running') m.set(folder, r.id);
          }
          setRunningFolders(m);
        })
        .catch(() => {});
    };
    loadRunning();
    runningPollRef.current = setInterval(loadRunning, 5000);
    return () => clearInterval(runningPollRef.current);
  }, []);

  // ── Source selection ──────────────────────────────────────────────
  const [subdirs, setSubdirs] = useState<Subdir[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [folderFiles, setFolderFiles] = useState<DocFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [fileMode, setFileMode] = useState<'batch' | 'select'>('batch');

  // ── Advanced options ──────────────────────────────────────────────
  const [targetRules, setTargetRules] = useState(200);
  const [workers, setWorkers] = useState(20);
  const [skipOptimize, setSkipOptimize] = useState(false);
  const [singleStep, setSingleStep] = useState(false);
  const [stepNum, setStepNum] = useState(1);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    fetchDocuments().then((data: { subdirectories?: Subdir[] }) => {
      setSubdirs(data.subdirectories || []);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!preselectedFolder) return;
    if (!subdirs.some((entry) => entry.name === preselectedFolder)) return;
    setSelectedFolder(preselectedFolder);
    // Auto-scroll to the start button after a short delay so layout is ready
    setTimeout(() => startRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 300);
  }, [preselectedFolder, subdirs]);

  // When a folder is selected, fetch its files
  useEffect(() => {
    if (!selectedFolder) { setFolderFiles([]); setSelectedFiles(new Set()); setFileMode('batch'); return; }
    setLoadingFiles(true);
    fetchSubdirFiles(selectedFolder)
      .then((data: { documents?: DocFile[] }) => {
        const files = data.documents || [];
        setFolderFiles(files);
        // If a specific file was preselected (e.g. from single-file upload), auto-select it
        if (preselectedFile && selectedFolder === preselectedFolder) {
          const match = files.find(f => f.name === preselectedFile);
          if (match) {
            setFileMode('select');
            setSelectedFiles(new Set([match.relative_path]));
          } else {
            setSelectedFiles(new Set());
            setFileMode('batch');
          }
        } else {
          setSelectedFiles(new Set());
          setFileMode('batch');
        }
      })
      .catch(() => setFolderFiles([]))
      .finally(() => setLoadingFiles(false));
  }, [selectedFolder, preselectedFile, preselectedFolder]);

  // Filter folders to those matching the selected domain (same conventions as Documents page)
  const filteredSubdirs = subdirs.filter(s => resolveFolderDomain(s) === domain);

  const clearSource = () => {
    setSelectedFolder(null);
    setFolderFiles([]);
    setSelectedFiles(new Set());
    setFileMode('batch');
  };

  const toggleFileSelect = (relPath: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      if (next.has(relPath)) next.delete(relPath); else next.add(relPath);
      return next;
    });
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  // Check whether selected folder already has a running pipeline
  const folderAlreadyRunning = selectedFolder ? runningFolders.has(selectedFolder) : false;

  const handleStart = () => {
    if (folderAlreadyRunning) return; // blocked — warn shown in UI
    if (isStarting) return;
    const base = {
      provider, domain,
      target_rules: targetRules,
      workers,
      skip_optimize: skipOptimize,
      step: singleStep ? stepNum : undefined,
    };
    setIsStarting(true);
    const promise = (fileMode === 'select' && selectedFiles.size > 0 && selectedFolder)
      ? launch({ ...base, documents: [...selectedFiles].map(rel => `${selectedFolder}/${rel}`) })
      : (selectedFolder ? launch({ ...base, folder: selectedFolder }) : Promise.resolve());
    promise
      .catch(err => window.alert(`Failed to start: ${err?.message || err}`))
      .finally(() => setIsStarting(false));
  };

  // Form is no longer locked while runs are in flight — multiple concurrent
  // runs are supported. Same-folder collisions are still blocked below via
  // `folderAlreadyRunning` to avoid output-directory clobbering.
  const isRunning = false;
  const hasSource = fileMode === 'select' ? selectedFiles.size > 0 : !!selectedFolder;

  return (
    <div className="space-y-5">

      {/* ── 1. Domain & Provider ─────────────────────────────────── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Configuration</p>
        <div>
          <label className="text-xs text-gray-500 mb-1.5 block">Domain</label>
          <select
            title="Domain"
            value={domain}
            onChange={e => setDomain(e.target.value)}
            disabled={isRunning}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 disabled:opacity-50"
          >
            {DOMAINS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </div>
      </div>

      {/* ── 2. Source Documents ─────────────────────────────────── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Source Documents</p>
          <span className="text-[11px] text-blue-300 bg-blue-500/10 border border-blue-500/30 px-3 py-1 rounded-lg">
            Run on entire folder or select specific files
          </span>
        </div>

        <p className="text-xs text-gray-500 mb-3">
          Select a folder, then choose to process all files as a batch or pick individual files for extraction.
        </p>
        {filteredSubdirs.length === 0
          ? <div className="text-center py-8 space-y-2">
              <p className="text-sm text-gray-500">No <span className="text-gray-300">{DOMAINS.find(d => d.value === domain)?.label}</span> folders found.</p>
              <button type="button" onClick={() => nav('/documents')} className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2">
                Upload documents first →
              </button>
            </div>
          : <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {filteredSubdirs.map(s => {
                const isFolderRunning = runningFolders.has(s.name);
                return (
                <button key={s.name} type="button" disabled={isRunning}
                  onClick={() => setSelectedFolder(f => f === s.name ? null : s.name)}
                  className={`flex items-center gap-3 p-4 rounded-xl border transition-all text-left disabled:opacity-50 ${
                    selectedFolder === s.name
                      ? 'bg-blue-500/10 border-blue-500/40'
                      : isFolderRunning
                      ? 'bg-amber-500/5 border-amber-500/30'
                      : 'bg-gray-800/40 border-gray-700 hover:border-gray-600'
                  }`}
                >
                  <FolderOpen size={18} className={selectedFolder === s.name ? 'text-blue-400 shrink-0' : isFolderRunning ? 'text-amber-400 shrink-0' : 'text-amber-400 shrink-0'} />
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-medium truncate ${selectedFolder === s.name ? 'text-blue-300' : 'text-gray-200'}`}>{s.name}</p>
                    <p className="text-xs text-gray-500">{s.file_count} related files</p>
                    {isFolderRunning && (
                      <span className="inline-flex items-center gap-1 mt-1 text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
                        <Loader2 size={10} className="animate-spin" /> Pipeline running
                      </span>
                    )}
                  </div>
                  {selectedFolder === s.name && <CheckCircle size={15} className="text-blue-400 shrink-0" />}
                </button>
                );
              })}
            </div>
        }

        {/* File-level selection when a folder is selected */}
        {selectedFolder && (
          <div className="mt-4 space-y-3">
            {/* Mode toggle */}
            <div className="flex items-center gap-2">
              <div className="flex gap-1 p-0.5 bg-gray-800 rounded-lg">
                <button type="button" disabled={isRunning}
                  onClick={() => setFileMode('batch')}
                  className={`px-3 py-1 text-xs rounded-md transition-all ${
                    fileMode === 'batch'
                      ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                      : 'text-gray-400 hover:text-gray-200 border border-transparent'
                  }`}
                >
                  <FolderOpen size={11} className="inline mr-1.5 -mt-0.5" />All files
                </button>
                <button type="button" disabled={isRunning}
                  onClick={() => setFileMode('select')}
                  className={`px-3 py-1 text-xs rounded-md transition-all ${
                    fileMode === 'select'
                      ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                      : 'text-gray-400 hover:text-gray-200 border border-transparent'
                  }`}
                >
                  <FileText size={11} className="inline mr-1.5 -mt-0.5" />Select files
                </button>
              </div>
              {!isRunning && (
                <button type="button" onClick={clearSource} title="Clear selection" className="text-gray-500 hover:text-gray-300 ml-auto">
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Batch mode summary */}
            {fileMode === 'batch' && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg text-xs text-blue-300">
                <FolderOpen size={12} /> {selectedFolder} · {folderFiles.length} files · unified batch
              </div>
            )}

            {/* File selection list */}
            {fileMode === 'select' && (
              <div className="bg-gray-800/40 border border-gray-700 rounded-xl overflow-hidden">
                {loadingFiles ? (
                  <div className="flex items-center justify-center py-6">
                    <Loader2 size={16} className="animate-spin text-blue-400" />
                  </div>
                ) : folderFiles.length === 0 ? (
                  <p className="text-xs text-gray-500 px-4 py-4">No supported files in this folder.</p>
                ) : (
                  <>
                    <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700/50">
                      <span className="text-[11px] text-gray-500 uppercase tracking-wider">
                        {selectedFiles.size} of {folderFiles.length} selected
                      </span>
                      <button type="button" disabled={isRunning}
                        onClick={() => {
                          if (selectedFiles.size === folderFiles.length) setSelectedFiles(new Set());
                          else setSelectedFiles(new Set(folderFiles.map(f => f.relative_path)));
                        }}
                        className="text-[11px] text-blue-400 hover:text-blue-300"
                      >
                        {selectedFiles.size === folderFiles.length ? 'Deselect all' : 'Select all'}
                      </button>
                    </div>
                    <div className="max-h-52 overflow-y-auto divide-y divide-gray-700/30">
                      {folderFiles.map(f => (
                        <label key={f.relative_path}
                          className={`flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors ${
                            selectedFiles.has(f.relative_path)
                              ? 'bg-blue-500/5'
                              : 'hover:bg-gray-800/60'
                          }`}
                        >
                          <input type="checkbox" disabled={isRunning}
                            checked={selectedFiles.has(f.relative_path)}
                            onChange={() => toggleFileSelect(f.relative_path)}
                            className="accent-blue-500 shrink-0"
                          />
                          <FileText size={14} className={selectedFiles.has(f.relative_path) ? 'text-blue-400 shrink-0' : 'text-gray-500 shrink-0'} />
                          <span className={`text-sm truncate flex-1 ${
                            selectedFiles.has(f.relative_path) ? 'text-gray-200' : 'text-gray-400'
                          }`}>{f.name}</span>
                          <span className="text-[11px] text-gray-600 shrink-0">{formatFileSize(f.size)}</span>
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 3. Advanced Options (collapsible) ───────────────────── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <button type="button" onClick={() => setShowAdvanced(o => !o)}
          className="w-full flex items-center justify-between px-5 py-3"
        >
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Advanced Options</span>
          {showAdvanced ? <ChevronUp size={15} className="text-gray-500" /> : <ChevronDown size={15} className="text-gray-500" />}
        </button>
        {showAdvanced && (
          <div className="px-5 pb-5 border-t border-gray-800 space-y-4 pt-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Target Rules: {targetRules}</label>
                <input type="range" min={50} max={500} step={10} value={targetRules}
                  onChange={e => setTargetRules(Number(e.target.value))} title="Target rules" aria-label="Target rules" className="w-full accent-blue-500" disabled={isRunning} />
                <div className="flex justify-between text-[10px] text-gray-600 mt-0.5"><span>50</span><span>500</span></div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-gray-500">Workers</label>
                  <input type="number" min={1} max={40} value={workers}
                    onChange={e => setWorkers(Math.max(1, Math.min(40, Number(e.target.value))))}
                    disabled={isRunning} title="Workers" aria-label="Workers"
                    className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs text-gray-200 text-center focus:outline-none focus:border-blue-500 disabled:opacity-50"
                  />
                </div>
                <input type="range" min={1} max={40} value={workers}
                  onChange={e => setWorkers(Number(e.target.value))} title="Extraction workers" aria-label="Extraction workers" className="w-full accent-blue-500" disabled={isRunning} />
                <div className="flex justify-between text-[10px] text-gray-600 mt-0.5"><span>1</span><span className="text-amber-600">40 (max)</span></div>
              </div>
            </div>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input type="checkbox" checked={skipOptimize} onChange={e => setSkipOptimize(e.target.checked)} className="accent-blue-500" disabled={isRunning} />
                Skip Optimization (Step 5)
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input type="checkbox" checked={singleStep} onChange={e => setSingleStep(e.target.checked)} className="accent-blue-500" disabled={isRunning} />
                Single Step Only
              </label>
              {singleStep && (
                <select title="Step" value={stepNum} onChange={e => setStepNum(Number(e.target.value))}
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500" disabled={isRunning}
                >
                  {[1,2,3,4,5,6].map(n => <option key={n} value={n}>Step {n} — {STEP_LABELS[n]}</option>)}
                </select>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── 4. Start ─────────────────────────────────────────────── */}
      {folderAlreadyRunning && (
        <div className="flex items-center gap-2 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-sm text-amber-300">
          <AlertTriangle size={16} className="shrink-0" />
          <span>
            A pipeline is already running for <strong>{selectedFolder}</strong>. Wait for it to finish or select a different folder.
          </span>
        </div>
      )}
      <div ref={startRef} className={`flex items-center gap-4 ${
        hasSource && !folderAlreadyRunning && preselectedFolder === selectedFolder
          ? 'bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 -mx-1'
          : ''
      }`}>
        <button type="button" onClick={handleStart} disabled={!hasSource || folderAlreadyRunning || isStarting}
          className={`flex items-center gap-2 px-6 py-2.5 text-white font-medium rounded-lg transition-all active:scale-[0.97] ${
            isStarting
              ? 'bg-blue-700 cursor-wait'
              : hasSource && !folderAlreadyRunning
              ? 'bg-blue-600 hover:bg-blue-500 shadow-lg shadow-blue-600/20'
              : 'bg-gray-700 text-gray-500'
          }`}
        >
          {isStarting ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
          {isStarting ? 'Starting…' : 'Start Pipeline'}
        </button>
        {hasSource && !folderAlreadyRunning && (
          <div className="flex flex-col">
            <span className="text-sm text-gray-300">
              Ready to run on <strong className="text-blue-300">
                {fileMode === 'select'
                  ? `${selectedFiles.size} file${selectedFiles.size === 1 ? '' : 's'}`
                  : selectedFolder}
              </strong>
            </span>
            <span className="text-xs text-gray-500">
              {domain} · {fileMode === 'select'
                ? `${selectedFiles.size} selected from ${selectedFolder}`
                : `${filteredSubdirs.find(s => s.name === selectedFolder)?.file_count ?? '?'} files · batch extraction`}
            </span>
          </div>
        )}
        {runs.length > 0 && (
          <span className="ml-auto text-xs text-gray-500">
            {runs.length} run{runs.length === 1 ? '' : 's'} tracked
          </span>
        )}
      </div>

      {/* ── 4b. Recent Runs (history) ──────────────────────────── */}
      <HistoryPanel
        type="extraction"
        trackedRunIds={runs.map(r => r.id)}
        onRestart={handleRestart}
        refreshKey={historyRefresh}
      />

      {/* ── 5. Run tabs + per-run panel ─────────────────────────── */}
      {runs.length > 0 && activeRun && (
        <div className="space-y-4">
          <RunTabs runs={runs} activeRunId={activeRunId} setActiveRunId={setActiveRunId} dismiss={dismiss} />

          {activeRun.status === 'completed' && activeRun.config?.folder && (
            <div className="flex items-center justify-between gap-4 px-5 py-4 bg-green-500/10 border border-green-500/30 rounded-xl">
              <div className="flex items-center gap-3">
                <CheckCircle size={20} className="text-green-400 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-green-300">
                    Knowledge graph generated for <span className="text-green-200">{activeRun.config.folder}</span>
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    View the interactive visualization, browse rules, or publish to Graph DB.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => nav(`/explorer?graph=${encodeURIComponent(activeRun.config.folder)}&provider=${provider}`)}
                className="flex items-center gap-2 px-5 py-2.5 bg-green-600 hover:bg-green-500 text-white font-medium rounded-lg transition-colors shrink-0"
              >
                <Network size={16} /> View Knowledge Graph
              </button>
            </div>
          )}

          <div className="flex items-center gap-3">
            {(activeRun.status === 'running' || activeRun.status === 'cancelling') && (
              <button type="button" onClick={() => handleCancel(activeRun.id)} disabled={activeRun.isCancelling}
                className={`flex items-center gap-2 px-5 py-2 text-white font-medium rounded-lg transition-colors ${
                  activeRun.isCancelling ? 'bg-gray-600 cursor-not-allowed' : 'bg-red-600 hover:bg-red-500'
                }`}
              >
                {activeRun.isCancelling ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
                {activeRun.isCancelling ? 'Cancelling...' : 'Cancel This Run'}
              </button>
            )}
            {(activeRun.status === 'completed' || activeRun.status === 'failed' || activeRun.status === 'cancelled') && (
              <>
                <button type="button" onClick={() => handleRestart(activeRun)} disabled={!activeRun.config}
                  title={activeRun.config ? 'Re-run with the same configuration (creates a new tab)' : 'Original configuration is unavailable'}
                  className={`flex items-center gap-2 px-4 py-2 text-white font-medium rounded-lg text-sm transition-colors ${
                    activeRun.config ? 'bg-blue-600 hover:bg-blue-500' : 'bg-gray-700 text-gray-500 cursor-not-allowed'
                  }`}
                >
                  <RotateCcw size={14} /> Restart from Scratch
                </button>
                <button type="button" onClick={() => dismiss(activeRun.id)}
                  className="flex items-center gap-2 px-4 py-2 text-gray-300 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm transition-colors"
                >
                  <X size={14} /> Dismiss
                </button>
              </>
            )}
            <StatusBanner status={activeRun.status} />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <WorkflowDiagram steps={activeRun.steps} pipelineType="extraction" />
          </div>
          <CostBanner cost={activeRun.cost} isRunning={activeRun.status === 'running'} />
          <LogSection status={activeRun.status} logs={activeRun.logs} />
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  KG Joining Pipeline (Steps 7-10)                                   */
/* ================================================================== */

function JoiningPipeline({ provider }: { provider: string }) {
  const { runs, activeRunId, setActiveRunId, launch, cancel, dismiss } = usePipeline('comparison');
  const activeRun = runs.find(r => r.id === activeRunId) || null;
  const nav = useEmbeddedNavigate();

  const handleCancel = (id: string) => {
    if (window.confirm('Are you sure you want to cancel the running pipeline? This cannot be undone.')) {
      cancel(id);
    }
  };

  const handleRestart = (run: { id: string; config?: any }) => {
    if (!run.config || Object.keys(run.config).length === 0) {
      window.alert('Cannot restart \u2014 original configuration is no longer available for this run.');
      return;
    }
    if (!window.confirm('Restart this joining pipeline from scratch with the same configuration? A new run tab will be created.')) return;
    setIsStarting(true);
    launch(run.config)
      .then(() => setHistoryRefresh(k => k + 1))
      .catch(err => window.alert(`Failed to start: ${err?.message || err}`))
      .finally(() => setIsStarting(false));
  };
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [isStarting, setIsStarting] = useState(false);
  const [graphs, setGraphs] = useState<GraphInfo[]>([]);
  const [g1, setG1] = useState('');
  const [g2, setG2] = useState('');
  const [workers, setWorkers] = useState(15);
  const [batchSize, setBatchSize] = useState(10);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchGraphs(provider)
      .then((data: { graphs?: GraphInfo[] }) => {
        const g = data.graphs || [];
        setGraphs(g);
        if (g.length >= 2) { setG1(g[0].name); setG2(g[1].name); }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [provider]);

  const handleStart = () => {
    if (isStarting) return;
    setIsStarting(true);
    launch({ g1, g2, provider, workers, batch_size: batchSize })
      .catch(err => window.alert(`Failed to start: ${err?.message || err}`))
      .finally(() => setIsStarting(false));
  };

  // Form is no longer locked while runs are in flight — multiple concurrent
  // joins are supported.
  const isRunning = false;

  return (
    <div className="space-y-6">
      {/* Configuration */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-gray-500 text-sm">Loading available graphs...</div>
        ) : graphs.length < 2 ? (
          <div className="text-center py-8">
            <GitCompareArrows size={32} className="mx-auto text-gray-600 mb-3" />
            <p className="text-gray-400 text-sm mb-1">At least 2 knowledge graphs required</p>
            <p className="text-gray-600 text-xs">Run the Creation Pipeline first to generate knowledge graphs, then come back here to compare them.</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="text-xs text-gray-500 mb-1.5 block">Graph 1 (G1)</label>
                <div className="space-y-1.5">
                  {graphs.map(g => (
                    <button
                      key={g.name}
                      type="button"
                      onClick={() => setG1(g.name)}
                      disabled={isRunning}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all ${
                        g1 === g.name
                          ? 'bg-blue-500/15 border border-blue-500/40 text-blue-300'
                          : g2 === g.name
                          ? 'bg-gray-800/50 border border-gray-700/50 text-gray-500 opacity-50 cursor-not-allowed'
                          : 'bg-gray-800 border border-gray-700 text-gray-300 hover:border-gray-600'
                      } disabled:opacity-50`}
                      title={`Select ${g.name} as G1`}
                    >
                      <span className="flex items-center gap-2">
                        <Network size={14} className={g1 === g.name ? 'text-blue-400' : 'text-gray-500'} />
                        <span className="truncate">{g.name}</span>
                      </span>
                      {g.rules != null && <span className="text-[10px] text-gray-500 flex-shrink-0">{g.rules} rules</span>}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1.5 block">Graph 2 (G2)</label>
                <div className="space-y-1.5">
                  {graphs.map(g => (
                    <button
                      key={g.name}
                      type="button"
                      onClick={() => setG2(g.name)}
                      disabled={isRunning}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all ${
                        g2 === g.name
                          ? 'bg-purple-500/15 border border-purple-500/40 text-purple-300'
                          : g1 === g.name
                          ? 'bg-gray-800/50 border border-gray-700/50 text-gray-500 opacity-50 cursor-not-allowed'
                          : 'bg-gray-800 border border-gray-700 text-gray-300 hover:border-gray-600'
                      } disabled:opacity-50`}
                      title={`Select ${g.name} as G2`}
                    >
                      <span className="flex items-center gap-2">
                        <Network size={14} className={g2 === g.name ? 'text-purple-400' : 'text-gray-500'} />
                        <span className="truncate">{g.name}</span>
                      </span>
                      {g.rules != null && <span className="text-[10px] text-gray-500 flex-shrink-0">{g.rules} rules</span>}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-gray-500">Parallelism (Workers)</label>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={workers}
                    onChange={(e) => setWorkers(Math.max(1, Math.min(30, Number(e.target.value))))}
                    disabled={isRunning}
                    title="Number of parallel workers (1–30)"
                    aria-label="Workers"
                    className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs text-gray-200 text-center focus:outline-none focus:border-purple-500 disabled:opacity-50"
                  />
                </div>
                <input type="range" min={1} max={30} value={workers} onChange={(e) => setWorkers(Number(e.target.value))} title="Joining workers" aria-label="Joining workers" className="w-full accent-purple-500" disabled={isRunning} />
                <div className="flex justify-between text-[10px] text-gray-600 mt-0.5"><span>1</span><span>30</span></div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-gray-500">Batch Size</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={batchSize}
                    onChange={(e) => setBatchSize(Math.max(1, Math.min(20, Number(e.target.value))))}
                    disabled={isRunning}
                    title="Rules processed per batch (1–20)"
                    aria-label="Batch size"
                    className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs text-gray-200 text-center focus:outline-none focus:border-purple-500 disabled:opacity-50"
                  />
                </div>
                <input type="range" min={1} max={20} value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} title="Joining batch size" aria-label="Joining batch size" className="w-full accent-purple-500" disabled={isRunning} />
                <div className="flex justify-between text-[10px] text-gray-600 mt-0.5"><span>1</span><span>20</span></div>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <button
                onClick={handleStart}
                disabled={!g1 || !g2 || g1 === g2 || isStarting}
                className={`flex items-center gap-2 px-6 py-2.5 text-white font-medium rounded-lg transition-all active:scale-[0.97] ${
                  isStarting ? 'bg-purple-700 cursor-wait' : 'bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500'
                }`}
              >
                {isStarting ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}
                {isStarting ? 'Starting…' : 'Start Joining Pipeline'}
              </button>
              {g1 && g2 && g1 !== g2 && (
                <span className="text-xs text-gray-500">
                  {g1} <span className="text-gray-600">vs</span> {g2}
                </span>
              )}
              {runs.length > 0 && (
                <span className="ml-auto text-xs text-gray-500">
                  {runs.length} run{runs.length === 1 ? '' : 's'} tracked
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {/* Recent Runs (history) */}
      <HistoryPanel
        type="comparison"
        trackedRunIds={runs.map(r => r.id)}
        onRestart={handleRestart}
        refreshKey={historyRefresh}
      />

      {/* Completion banner with View Results */}
      {activeRun?.status === 'completed' && (
        <div className="flex items-center justify-between gap-4 px-5 py-4 bg-green-500/10 border border-green-500/30 rounded-xl">
          <div className="flex items-center gap-3">
            <CheckCircle size={20} className="text-green-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-green-300">
                Joined knowledge graph generated
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                View the combined graph in the Knowledge Graph Explorer.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => nav(`/explorer?provider=${provider}`)}
            className="flex items-center gap-2 px-5 py-2.5 bg-green-600 hover:bg-green-500 text-white font-medium rounded-lg transition-colors shrink-0"
          >
            <Network size={16} /> View Knowledge Graph
          </button>
        </div>
      )}

      {/* Run tabs + per-run panel */}
      {runs.length > 0 && activeRun && (
        <div className="space-y-4">
          <RunTabs runs={runs} activeRunId={activeRunId} setActiveRunId={setActiveRunId} dismiss={dismiss} />

          <div className="flex items-center gap-3">
            {(activeRun.status === 'running' || activeRun.status === 'cancelling') && (
              <button type="button" onClick={() => handleCancel(activeRun.id)} disabled={activeRun.isCancelling}
                className={`flex items-center gap-2 px-5 py-2 text-white font-medium rounded-lg transition-colors ${
                  activeRun.isCancelling ? 'bg-gray-600 cursor-not-allowed' : 'bg-red-600 hover:bg-red-500'
                }`}
              >
                {activeRun.isCancelling ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
                {activeRun.isCancelling ? 'Cancelling...' : 'Cancel This Run'}
              </button>
            )}
            {(activeRun.status === 'completed' || activeRun.status === 'failed' || activeRun.status === 'cancelled') && (
              <>
                <button type="button" onClick={() => handleRestart(activeRun)} disabled={!activeRun.config}
                  title={activeRun.config ? 'Re-run with the same configuration (creates a new tab)' : 'Original configuration is unavailable'}
                  className={`flex items-center gap-2 px-4 py-2 text-white font-medium rounded-lg text-sm transition-colors ${
                    activeRun.config ? 'bg-purple-600 hover:bg-purple-500' : 'bg-gray-700 text-gray-500 cursor-not-allowed'
                  }`}
                >
                  <RotateCcw size={14} /> Restart from Scratch
                </button>
                <button type="button" onClick={() => dismiss(activeRun.id)}
                  className="flex items-center gap-2 px-4 py-2 text-gray-300 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm transition-colors"
                >
                  <X size={14} /> Dismiss
                </button>
              </>
            )}
            <StatusBanner status={activeRun.status} />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <WorkflowDiagram steps={activeRun.steps} pipelineType="comparison" />
          </div>
          <CostBanner cost={activeRun.cost} isRunning={activeRun.status === 'running'} />
          <LogSection status={activeRun.status} logs={activeRun.logs} />
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Main Pipeline Page                                                 */
/* ================================================================== */

export default function Pipeline() {
  const location = useLocation();
  const navigationState = (location.state as {
    preselectedFolder?: string;
    preselectedDomain?: string;
    preselectedFile?: string;
    pipelineTab?: 'creation' | 'joining';
  } | null) ?? null;
  const [domain, setDomain] = useState('mortgage');
  const provider = 'openai';
  const [activeTab, setActiveTab] = useState<'creation' | 'joining'>('creation');
  const [runningPipelines, setRunningPipelines] = useState<any[]>([]);
  const runCountPollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (navigationState?.preselectedDomain) setDomain(navigationState.preselectedDomain);
    if (navigationState?.pipelineTab) setActiveTab(navigationState.pipelineTab);
  }, [navigationState]);

  useEffect(() => {
    const poll = () => {
      fetchRunningPipelines()
        .then((data: { runs?: any[] }) => setRunningPipelines(data.runs || []))
        .catch(() => {});
    };
    poll();
    runCountPollRef.current = setInterval(poll, 5000);
    return () => clearInterval(runCountPollRef.current);
  }, []);

  const runningCount = runningPipelines.length;

  return (
    <div>
      {/* Tab header */}
      <div className="flex items-center gap-4 mb-6">
        <h2 className="text-2xl font-bold">Knowledge Extraction Pipeline</h2>
        {runningCount > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 px-3 py-1.5 rounded-lg">
            <Loader2 size={12} className="animate-spin" />
            {runningCount} pipeline{runningCount > 1 ? 's' : ''} running
          </span>
        )}
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 p-1 bg-gray-900 border border-gray-800 rounded-xl mb-6 w-fit">
        <button
          onClick={() => setActiveTab('creation')}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'creation'
              ? 'bg-blue-500/15 text-blue-400 shadow-sm shadow-blue-500/10 border border-blue-500/30'
              : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 border border-transparent'
          }`}
        >
          <Network size={16} />
          KG Creation
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            activeTab === 'creation' ? 'bg-blue-500/20 text-blue-300' : 'bg-gray-800 text-gray-500'
          }`}>
            Steps 1–6
          </span>
        </button>
        <button
          onClick={() => setActiveTab('joining')}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'joining'
              ? 'bg-purple-500/15 text-purple-400 shadow-sm shadow-purple-500/10 border border-purple-500/30'
              : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 border border-transparent'
          }`}
        >
          <GitCompareArrows size={16} />
          KG Joining
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            activeTab === 'joining' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800 text-gray-500'
          }`}>
            Steps 7–10
          </span>
        </button>
      </div>

      {/* Active pipelines panel */}
      {runningCount > 0 && (
        <div className="bg-gray-900 border border-amber-500/30 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Loader2 size={14} className="text-amber-400 animate-spin" />
            <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
              Active Pipelines ({runningCount})
            </span>
          </div>
          <div className="space-y-2">
            {runningPipelines.map(run => {
              const elapsed = run.started_at
                ? (() => {
                    const sec = Math.round((Date.now() - new Date(run.started_at).getTime()) / 1000);
                    if (sec < 60) return `${sec}s`;
                    if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
                    return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
                  })()
                : null;
              const folder = run.config?.folder;
              const runDomain = run.domain || run.config?.domain || '';
              const isExtraction = run.type === 'extraction';
              return (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-4 py-3 bg-gray-800/60 rounded-lg border border-gray-700/50"
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full animate-pulse ${isExtraction ? 'bg-blue-400' : 'bg-purple-400'}`} />
                    <div>
                      <div className="flex items-center gap-2 text-sm text-gray-200">
                        <span className="font-medium">
                          {isExtraction ? 'KG Creation' : 'KG Joining'}
                        </span>
                        {folder && (
                          <>
                            <span className="text-gray-600">·</span>
                            <span className="text-gray-400">{folder}</span>
                          </>
                        )}
                        {!isExtraction && run.config?.g1 && run.config?.g2 && (
                          <>
                            <span className="text-gray-600">·</span>
                            <span className="text-gray-400">{run.config.g1} vs {run.config.g2}</span>
                          </>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-[11px] text-gray-500">
                        {runDomain && <span className="capitalize">{runDomain}</span>}
                        {elapsed && (
                          <span className="flex items-center gap-1">
                            <Clock size={10} /> {elapsed}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <span className="text-[10px] text-gray-500 font-mono">{run.id}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pipeline content */}
      {activeTab === 'creation' ? (
        <CreationPipeline
          domain={domain}
          setDomain={setDomain}
          provider={provider}
          preselectedFolder={navigationState?.preselectedFolder ?? null}
          preselectedFile={navigationState?.preselectedFile ?? null}
        />
      ) : (
        <JoiningPipeline provider={provider} />
      )}
    </div>
  );
}
