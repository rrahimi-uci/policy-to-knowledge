import { useEffect, useState, useRef, useCallback } from 'react';
import { fetchRuns, fetchRunDetail, cancelPipeline, deleteRun, deleteAllRuns } from '../api';
import WorkflowDiagram from '../components/WorkflowDiagram';
import LogViewer from '../components/LogViewer';
import type { PipelineStep } from '../hooks/usePipeline';
import type { WsMessage } from '../hooks/useWebSocket';
import {
  CheckCircle, XCircle, Loader2, Clock, ChevronDown, ChevronRight, Square,
  Terminal, Network, GitCompareArrows, Filter, Trash2, ArrowUpDown, ArrowUp, ArrowDown, AlertTriangle,
  Database,
} from 'lucide-react';

type SortField = 'created_at' | 'status' | 'type' | 'domain' | 'duration';
type SortDir = 'asc' | 'desc';

function extractionSourceLabel(run: any): string {
  const config = run.config || {};
  if (config.batch_name) return `${config.batch_name} · batch`;
  if (config.folder) return `${config.folder} · batch`;
  if (Array.isArray(run.documents) && run.documents.length > 0) {
    if (run.documents.length === 1) return run.documents[0];
    return `${run.documents.length} files`;
  }
  return '—';
}

function formatDuration(start?: string, end?: string): string {
  if (!start) return '—';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.round((e - s) / 1000);
  if (sec < 1) return '<1s';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

export default function RunHistory() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Refs so the poll callback always reads latest values without re-creating the interval
  const runsRef = useRef(runs);
  runsRef.current = runs;
  const expandedRef = useRef(expandedRun);
  expandedRef.current = expandedRun;

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterType, setFilterType] = useState<string>('all');

  // Sorting
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir(field === 'created_at' ? 'desc' : 'asc');
    }
  };

  const sortIcon = (field: SortField) => {
    if (sortField !== field) return <ArrowUpDown size={12} className="text-gray-600" />;
    return sortDir === 'asc'
      ? <ArrowUp size={12} className="text-blue-400" />
      : <ArrowDown size={12} className="text-blue-400" />;
  };

  const loadRuns = useCallback(() =>
    fetchRuns().then(res => setRuns(res.runs || [])).catch(() => {}), []);

  useEffect(() => {
    loadRuns().finally(() => setLoading(false));
  }, [loadRuns]);

  // Auto-refresh list while any run is running.
  // Uses refs instead of state in the dependency array to avoid
  // clearing/re-creating the interval on every poll cycle (which
  // caused re-render cascades that hijacked scroll position).
  useEffect(() => {
    pollRef.current = setInterval(() => {
      if (!runsRef.current.some(r => r.status === 'running')) return;
      loadRuns();
      const exp = expandedRef.current;
      if (exp) fetchRunDetail(exp).then(setDetail).catch(() => {});
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadRuns]);

  const toggleExpand = async (runId: string) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      setDetail(null);
      return;
    }
    setExpandedRun(runId);
    try {
      const data = await fetchRunDetail(runId);
      setDetail(data);
    } catch { setDetail(null); }
  };

  const handleCancel = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    setCancelError(null);
    try {
      await cancelPipeline(runId);
      setRuns(prev => prev.map(r => r.id === runId ? { ...r, status: 'cancelled' } : r));
      if (expandedRun === runId && detail) {
        setDetail({ ...detail, steps: detail.steps?.map((s: any) =>
          s.status === 'pending' || s.status === 'running' ? { ...s, status: 'skipped' } : s
        )});
      }
    } catch {
      setCancelError(`Failed to cancel run ${runId}. The process may have already finished.`);
      loadRuns();
    }
  };

  const statusIcon = (s: string) => {
    if (s === 'completed') return <CheckCircle size={16} className="text-green-400" />;
    if (s === 'running') return <Loader2 size={16} className="text-blue-400 animate-spin" />;
    if (s === 'failed') return <XCircle size={16} className="text-red-400" />;
    if (s === 'cancelled') return <XCircle size={16} className="text-orange-400" />;
    if (s === 'interrupted') return <AlertTriangle size={16} className="text-yellow-400" />;
    return <Clock size={16} className="text-gray-500" />;
  };

  const pipelineType = (r: any): 'extraction' | 'comparison' | 'publish' =>
    r.type === 'comparison' ? 'comparison' : r.type === 'publish' ? 'publish' : 'extraction';

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-blue-400" size={32} /></div>;
  }

  const handleDeleteRun = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    if (!window.confirm('Delete this run? This cannot be undone.')) return;
    try {
      await deleteRun(runId);
      setRuns(prev => prev.filter(r => r.id !== runId));
      if (expandedRun === runId) {
        setExpandedRun(null);
        setDetail(null);
      }
    } catch { /* ignore */ }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Delete all run history? This cannot be undone.')) return;
    try {
      await deleteAllRuns();
      setRuns([]);
      setExpandedRun(null);
      setDetail(null);
    } catch { /* ignore */ }
  };

  const getDuration = (r: any): number => {
    const start = r.started_at || r.created_at;
    if (!start) return 0;
    const s = new Date(start).getTime();
    const e = r.finished_at ? new Date(r.finished_at).getTime() : Date.now();
    return e - s;
  };

  const statusOrder: Record<string, number> = { running: 0, failed: 1, interrupted: 2, cancelled: 3, completed: 4, pending: 5 };

  const filteredRuns = runs
    .filter(r => {
      if (filterStatus !== 'all' && r.status !== filterStatus) return false;
      if (filterType !== 'all') {
        if (filterType === 'creation' && (r.type === 'comparison' || r.type === 'publish')) return false;
        if (filterType === 'joining' && r.type !== 'comparison') return false;
        if (filterType === 'publish' && r.type !== 'publish') return false;
      }
      return true;
    })
    .sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'created_at': {
          cmp = new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
          break;
        }
        case 'status':
          cmp = (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9);
          break;
        case 'type':
          cmp = (a.type || '').localeCompare(b.type || '');
          break;
        case 'domain':
          cmp = (a.domain || '').localeCompare(b.domain || '');
          break;
        case 'duration':
          cmp = getDuration(a) - getDuration(b);
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Run History</h2>
        {runs.length > 0 && (
          <button
            onClick={handleClearAll}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30 rounded-lg transition-colors"
          >
            <Trash2 size={14} /> Clear All
          </button>
        )}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4">
        <Filter size={16} className="text-gray-500" />
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          title="Filter by status"
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Statuses</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
          <option value="interrupted">Interrupted</option>
        </select>
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          title="Filter by type"
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Types</option>
          <option value="creation">KG Creation</option>
          <option value="joining">KG Joining</option>
          <option value="publish">Publish to DB</option>
        </select>
        {(filterStatus !== 'all' || filterType !== 'all') && (
          <button
            onClick={() => { setFilterStatus('all'); setFilterType('all'); }}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-gray-500">
          {filteredRuns.length} of {runs.length} runs
        </span>
      </div>

      {cancelError && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400 flex items-center justify-between">
          <span>{cancelError}</span>
          <button onClick={() => setCancelError(null)} className="text-red-400 hover:text-red-300 ml-4">Dismiss</button>
        </div>
      )}

      {filteredRuns.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500">
          {runs.length === 0 ? 'No pipeline runs recorded yet.' : 'No runs match the current filters.'}
        </div>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl divide-y divide-gray-800">
          {/* Sortable column headers */}
          <div className="flex items-center gap-3 px-5 py-2 text-[11px] uppercase tracking-wider text-gray-500 border-b border-gray-800 select-none">
            <span className="w-8" />
            <button onClick={() => toggleSort('status')} className="flex items-center gap-1 hover:text-gray-300 transition-colors w-6">
              {sortIcon('status')}
            </button>
            <button onClick={() => toggleSort('type')} className="flex items-center gap-1 hover:text-gray-300 transition-colors flex-1 min-w-0">
              Type {sortIcon('type')}
            </button>
            <button onClick={() => toggleSort('domain')} className="flex items-center gap-1 hover:text-gray-300 transition-colors w-24">
              Domain {sortIcon('domain')}
            </button>
            <button onClick={() => toggleSort('duration')} className="flex items-center gap-1 hover:text-gray-300 transition-colors w-16 justify-end">
              Duration {sortIcon('duration')}
            </button>
            <span className="w-20" />
            <button onClick={() => toggleSort('created_at')} className="flex items-center gap-1 hover:text-gray-300 transition-colors w-32 justify-end">
              Time {sortIcon('created_at')}
            </button>
            <span className="w-10" />
          </div>
          {filteredRuns.map(r => (
            <div key={r.id}>
              {/* Row */}
              <div className="flex items-center gap-3 px-5 py-3.5 hover:bg-gray-800/40 transition-colors">
                <button
                  type="button"
                  onClick={() => toggleExpand(r.id)}
                  aria-label={`${r.type === 'comparison' ? 'KG Joining' : 'KG Creation'} ${r.domain || ''} ${r.status}`}
                  className="flex items-center gap-3 flex-1 min-w-0 text-left"
                >
                  {expandedRun === r.id ? <ChevronDown size={16} className="text-gray-500" /> : <ChevronRight size={16} className="text-gray-500" />}
                  {statusIcon(r.status)}
                  <span className="flex items-center gap-1.5 text-sm text-gray-300 flex-1 min-w-0">
                    {r.type === 'comparison'
                      ? <><GitCompareArrows size={14} className="text-purple-400" /> KG Joining</>
                      : r.type === 'publish'
                      ? <><Database size={14} className="text-emerald-400" /> Publish to DB</>
                      : <><Network size={14} className="text-blue-400" /> KG Creation</>
                    }
                    {r.domain && <span className="text-gray-500 ml-1">— {r.domain}</span>}
                  </span>
                <span className="text-xs text-gray-500 w-16 text-right font-mono">
                    {formatDuration(r.started_at || r.created_at, r.finished_at)}
                  </span>
                  {r.result?.total_cost > 0 && (
                    <span className="text-[11px] font-mono text-emerald-400/70 w-16 text-right" title="LLM cost">
                      {r.result.total_cost < 0.01 ? `$${r.result.total_cost.toFixed(4)}` : `$${r.result.total_cost.toFixed(2)}`}
                    </span>
                  )}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    r.status === 'completed' ? 'bg-green-500/10 text-green-400' :
                    r.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                    r.status === 'running' ? 'bg-blue-500/10 text-blue-400' :
                    r.status === 'cancelled' ? 'bg-orange-500/10 text-orange-400' :
                    r.status === 'interrupted' ? 'bg-yellow-500/10 text-yellow-400' :
                    'bg-gray-800 text-gray-500'
                  }`}>{r.status}</span>
                  <span className="text-xs text-gray-600 w-32 text-right">
                    {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                  </span>
                </button>
                {r.status === 'running' && (
                  <button
                    onClick={(e) => handleCancel(e, r.id)}
                    className="flex items-center gap-1 px-2.5 py-1 bg-red-600 hover:bg-red-500 text-white text-xs rounded-lg transition-colors"
                  >
                    <Square size={12} />
                    Stop
                  </button>
                )}
                {r.status !== 'running' && (
                  <button
                    onClick={(e) => handleDeleteRun(e, r.id)}
                    className="p-1.5 rounded hover:bg-red-500/10 text-gray-600 hover:text-red-400 transition-colors"
                    title="Delete run"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>

              {/* Expanded detail */}
              {expandedRun === r.id && detail && (
                <div className="px-6 py-5 bg-gray-800/20 border-t border-gray-800 space-y-4">
                  {/* Meta row */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-xs">
                    <div>
                      <span className="text-gray-500 block">Domain</span>
                      <span className="text-gray-300 capitalize">{r.domain || '—'}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Source</span>
                      <span className="text-gray-300">{r.type === 'comparison' ? 'Graph comparison' : r.type === 'publish' ? 'Publish to Graph DB' : extractionSourceLabel(r)}</span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Started</span>
                      <span className="text-gray-300">
                        {r.started_at ? new Date(r.started_at).toLocaleString() : '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500 block">Finished</span>
                      <span className="text-gray-300">
                        {r.finished_at ? new Date(r.finished_at).toLocaleString() : '—'}
                      </span>
                    </div>
                  </div>

                  {/* LLM Cost */}
                  {r.result && r.result.total_cost > 0 && (
                    <div className="flex items-center gap-4 px-4 py-2.5 bg-gray-900/60 border border-gray-800/60 rounded-xl text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className="text-gray-500">LLM Cost</span>
                        <span className="font-mono font-semibold text-emerald-400">
                          {r.result.total_cost < 0.01 ? `$${r.result.total_cost.toFixed(4)}` : `$${r.result.total_cost.toFixed(2)}`}
                        </span>
                      </div>
                      <span className="text-gray-700">|</span>
                      <div className="flex items-center gap-3 text-gray-400">
                        <span>{r.result.llm_calls} calls</span>
                        <span>{r.result.total_prompt_tokens >= 1000 ? `${(r.result.total_prompt_tokens / 1000).toFixed(1)}K` : r.result.total_prompt_tokens} prompt</span>
                        <span>{r.result.total_completion_tokens >= 1000 ? `${(r.result.total_completion_tokens / 1000).toFixed(1)}K` : r.result.total_completion_tokens} completion</span>
                        {r.result.total_cached_tokens > 0 && (
                          <span className="text-blue-400">
                            {r.result.total_cached_tokens >= 1000 ? `${(r.result.total_cached_tokens / 1000).toFixed(1)}K` : r.result.total_cached_tokens} cached
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Workflow Diagram */}
                  {detail.steps?.length > 0 && (
                    <div className="bg-gray-900/60 border border-gray-800/60 rounded-xl p-5">
                      <WorkflowDiagram
                        steps={detail.steps as PipelineStep[]}
                        pipelineType={pipelineType(r)}
                      />
                    </div>
                  )}

                  {/* Error */}
                  {r.error && (
                    <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
                      {r.error}
                    </div>
                  )}

                  {/* Logs */}
                  {detail.logs?.length > 0 && (
                    <details className="group bg-gray-900/60 border border-gray-800/60 rounded-xl">
                      <summary className="flex items-center justify-between cursor-pointer px-5 py-3 select-none">
                        <div className="flex items-center gap-2">
                          <Terminal size={14} className={detail.logs.some((l: any) => l.level === 'ERROR') ? 'text-red-400' : 'text-gray-500'} />
                          <span className="text-xs text-gray-500 uppercase tracking-wider">
                            Logs
                          </span>
                          <span className="text-[10px] bg-gray-800 text-gray-500 px-2 py-0.5 rounded-full">
                            {detail.logs.length}
                          </span>
                        </div>
                        <ChevronDown size={14} className="text-gray-600 group-open:hidden" />
                      </summary>
                      <div className="px-5 pb-4">
                        <LogViewer
                          logs={detail.logs.map((l: any) => ({
                            type: 'log' as const,
                            level: l.level,
                            message: l.message,
                          } satisfies WsMessage))}
                        />
                      </div>
                    </details>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
