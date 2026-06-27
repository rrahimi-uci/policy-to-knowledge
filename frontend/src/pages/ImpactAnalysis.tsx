import { useEffect, useState, useCallback, useRef } from 'react';
import { apiUrl, wsUrl } from '@/config';
import {
  Upload, AlertTriangle, FileText, Download,
  Trash2, ChevronDown, ChevronRight, Shield, AlertCircle,
  CircleDot, CheckCircle2, XCircle, RefreshCw, Loader2,
  Brain, Zap, ToggleLeft, ToggleRight,
  FileSearch, GitCompare, Network, BarChart3, FileOutput,
} from 'lucide-react';

/* ─── Types ─────────────────────────────────────────────────── */

interface GraphSummary {
  name: string;
  provider: string;
  rules: number;
  entities: number;
}

interface AffectedRule {
  rule_id: string;
  rule_name: string;
  rule_type: string;
  risk_level: string;
  match_score: number;
  matching_terms: string[];
  relevance?: string;
  reasoning?: string;
}

interface ImpactItem {
  id: number;
  change_type: 'added' | 'removed' | 'modified';
  provision_text: string;
  severity: 'breaking' | 'material' | 'cosmetic';
  affected_rules: AffectedRule[];
  description: string;
  recommendation: string;
}

interface Stats {
  total_changes: number;
  added_count: number;
  removed_count: number;
  modified_count: number;
  total_rules_in_graph: number;
  affected_rules_count: number;
  severity_breaking: number;
  severity_material: number;
  severity_cosmetic: number;
  impact_percentage: number;
}

interface SummaryExtended {
  headline: string;
  executive_summary?: string;
  key_findings?: string[];
  recommendations?: Array<{ priority: string; action: string; owner: string; timeline: string }>;
  risk_assessment?: { overall_risk: string; requires_board_review?: boolean; regulatory_deadline_risk?: boolean };
  old_provision_count: number;
  new_provision_count: number;
}

interface Analysis {
  id: string;
  graph_name: string;
  provider: string;
  old_doc_name: string;
  new_doc_name: string;
  status: string;
  summary: SummaryExtended | null;
  stats: Stats | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  items: ImpactItem[];
  mode?: string;
}

interface StepProgress {
  step: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
  data?: Record<string, unknown>;
}

/* ─── Constants ──────────────────────────────────────────────── */

const SEV_CONFIG = {
  breaking: { color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20', icon: XCircle, label: 'Breaking' },
  material: { color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', icon: AlertCircle, label: 'Material' },
  cosmetic: { color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/20', icon: CircleDot, label: 'Cosmetic' },
};

const CHANGE_CONFIG = {
  added: { color: 'text-emerald-400', label: '+ Added' },
  removed: { color: 'text-red-400', label: '− Removed' },
  modified: { color: 'text-amber-400', label: '~ Modified' },
};

const WORKFLOW_STEPS = [
  { id: 'parse',     icon: FileSearch, label: 'Document Parsing',    desc: 'Structuring regulatory provisions' },
  { id: 'diff',      icon: GitCompare, label: 'Semantic Diff',       desc: 'Finding meaningful changes' },
  { id: 'map',       icon: Network,    label: 'Rule Impact Mapping', desc: 'Mapping changes to KG rules' },
  { id: 'score',     icon: BarChart3,  label: 'Severity Scoring',    desc: 'Assigning risk & severity' },
  { id: 'summarize', icon: FileOutput, label: 'Executive Summary',   desc: 'Generating recommendations' },
];

/* ─── Component ──────────────────────────────────────────────── */

export default function ImpactAnalysis() {
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [selectedGraph, setSelectedGraph] = useState('');
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [showValidation, setShowValidation] = useState(false);
  const [loading, setLoading] = useState(false);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [activeAnalysis, setActiveAnalysis] = useState<Analysis | null>(null);
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [mode, setMode] = useState<'agentic' | 'basic'>('agentic');
  const [stepProgress, setStepProgress] = useState<Record<string, StepProgress>>({});
  const [_wsConnected, setWsConnected] = useState(false);
  const oldRef = useRef<HTMLInputElement>(null);
  const newRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<number | null>(null);

  // Load graphs
  useEffect(() => {
    fetch(apiUrl('kg/graphs'))
      .then(r => r.json())
      .then(d => setGraphs(d.graphs ?? []))
      .catch(() => {});
  }, []);

  // Load history
  const loadHistory = useCallback(() => {
    fetch(apiUrl('kg/impact/analyses'))
      .then(r => r.json())
      .then(d => setAnalyses(d.analyses ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const missingRequirements = [
    !selectedGraph ? 'Select a target knowledge graph' : null,
    !oldFile ? 'Upload the old regulatory document' : null,
    !newFile ? 'Upload the new regulatory document' : null,
  ].filter((value): value is string => Boolean(value));

  const canRunAnalysis = missingRequirements.length === 0;

  useEffect(() => {
    if (canRunAnalysis) setShowValidation(false);
  }, [canRunAnalysis]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  // Connect WebSocket for agentic progress
  const connectWs = useCallback((analysisId: string) => {
    if (wsRef.current) wsRef.current.close();

    // Initialize all steps as pending
    const initial: Record<string, StepProgress> = {};
    WORKFLOW_STEPS.forEach(s => {
      initial[s.id] = { step: s.id, status: 'pending', message: '' };
    });
    setStepProgress(initial);

    const ws = new WebSocket(wsUrl(`kg/impact/${analysisId}`));
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      const stepId = msg.step;

      if (stepId === 'done' || stepId === 'error') {
        // Analysis finished — load complete result
        setLoading(false);
        loadAnalysis(analysisId);
        loadHistory();
        ws.close();
        return;
      }

      if (stepId === 'init') return; // Skip init messages

      setStepProgress(prev => ({
        ...prev,
        [stepId]: {
          step: stepId,
          status: msg.status ?? 'running',
          message: msg.message ?? '',
          data: msg.data,
        },
      }));
    };
    ws.onerror = () => {
      setWsConnected(false);
      // Fallback: poll for completion
      pollingRef.current = window.setInterval(async () => {
        const res = await fetch(apiUrl(`kg/impact/analyses/${analysisId}`));
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'completed' || data.status === 'failed') {
            setLoading(false);
            setActiveAnalysis({ ...data, items: data.items ?? [] });
            loadHistory();
            if (pollingRef.current) clearInterval(pollingRef.current);
          }
        }
      }, 3000);
    };
  }, [loadHistory]);

  // Run analysis
  const runAnalysis = useCallback(async () => {
    if (!selectedGraph || !oldFile || !newFile) {
      setShowValidation(true);
      return;
    }
    setShowValidation(false);
    setLoading(true);
    setActiveAnalysis(null);
    setStepProgress({});

    try {
      const form = new FormData();
      form.append('old_doc', oldFile);
      form.append('new_doc', newFile);
      form.append('graph_name', selectedGraph);
      form.append('provider', 'openai');
      form.append('mode', mode);

      const res = await fetch(apiUrl('kg/impact/analyze'), { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      if (mode === 'agentic') {
        // Connect WebSocket for live progress
        setActiveAnalysis({ ...data, items: [], stats: null, summary: null });
        connectWs(data.id);
      } else {
        // Basic mode — result is immediate
        setActiveAnalysis(data);
        setExpandedItems(new Set());
        setFilterSeverity('all');
        setLoading(false);
        loadHistory();
      }
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  }, [selectedGraph, oldFile, newFile, mode, loadHistory, connectWs]);

  // Load existing analysis
  const loadAnalysis = useCallback(async (id: string) => {
    const res = await fetch(apiUrl(`kg/impact/analyses/${id}`));
    if (res.ok) {
      const data: Analysis = await res.json();
      setActiveAnalysis(data);
      setExpandedItems(new Set());
      setFilterSeverity('all');
      setStepProgress({});
    }
  }, []);

  // Delete analysis
  const deleteAnalysis = useCallback(async (id: string) => {
    await fetch(apiUrl(`kg/impact/analyses/${id}`), { method: 'DELETE' });
    if (activeAnalysis?.id === id) setActiveAnalysis(null);
    loadHistory();
  }, [activeAnalysis, loadHistory]);

  // Toggle item expansion
  const toggleItem = (itemId: number) => {
    setExpandedItems(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

  const filteredItems = activeAnalysis?.items?.filter(
    i => filterSeverity === 'all' || i.severity === filterSeverity
  ) ?? [];

  const isRunning = loading && mode === 'agentic' && Object.keys(stepProgress).length > 0;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
            <Shield className="h-6 w-6 text-blue-400" />
            Regulatory Change Impact Analysis
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Upload old and new regulatory documents to identify affected rules, severity, and recommended actions
          </p>
        </div>
        {/* Mode Toggle */}
        <button
          type="button"
          onClick={() => setMode(m => m === 'agentic' ? 'basic' : 'agentic')}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 hover:border-gray-600 transition-colors"
        >
          {mode === 'agentic' ? (
            <>
              <Brain className="h-4 w-4 text-violet-400" />
              <span className="text-xs text-violet-300 font-medium">Agentic Mode</span>
              <ToggleRight className="h-4 w-4 text-violet-400" />
            </>
          ) : (
            <>
              <Zap className="h-4 w-4 text-amber-400" />
              <span className="text-xs text-amber-300 font-medium">Basic Mode</span>
              <ToggleLeft className="h-4 w-4 text-gray-500" />
            </>
          )}
        </button>
      </div>

      {/* Upload Form */}
      <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-6">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">New Analysis</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">Target Knowledge Graph</label>
            <select
              title="Target Knowledge Graph"
              value={selectedGraph}
              onChange={e => {
                setSelectedGraph(e.target.value);
                if (e.target.value) setShowValidation(false);
              }}
              className={`w-full rounded-lg bg-gray-800 border text-sm text-gray-200 px-3 py-2 focus:outline-none ${
                showValidation && !selectedGraph
                  ? 'border-red-500/60 focus:border-red-500'
                  : 'border-gray-700 focus:border-blue-500'
              }`}
            >
              <option value="">Select a graph...</option>
              {graphs.map(g => (
                <option key={`${g.name}-${g.provider}`} value={g.name}>
                  {g.name.replace(/_/g, ' ')} ({g.rules} rules)
                </option>
              ))}
            </select>
            {selectedGraph && (
              <p className="mt-2 text-xs text-blue-300">
                Graph selected. Next, upload both the old and new regulatory documents to run analysis.
              </p>
            )}
          </div>
          <FileDropZone
            label="Old Regulatory Document"
            file={oldFile}
            onFile={setOldFile}
            inputRef={oldRef}
            invalid={showValidation && !oldFile}
          />
          <FileDropZone
            label="New Regulatory Document"
            file={newFile}
            onFile={setNewFile}
            inputRef={newRef}
            invalid={showValidation && !newFile}
          />
        </div>
        {showValidation && missingRequirements.length > 0 && (
          <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-300">Complete These Steps First</p>
            <ul className="mt-2 space-y-1 text-sm text-amber-100">
              {missingRequirements.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-300" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <button
          type="button"
          onClick={runAnalysis}
          disabled={loading}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : mode === 'agentic' ? <Brain className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
          {loading
            ? 'Analyzing...'
            : !selectedGraph
              ? 'Select a Graph to Continue'
              : !oldFile || !newFile
                ? 'Upload Both Documents to Continue'
                : mode === 'agentic'
                  ? 'Run Agentic Analysis'
                  : 'Run Basic Analysis'}
        </button>
      </div>

      {/* ═══ AGENTIC PROCESS FLOW DIAGRAM ═══ */}
      {isRunning && <WorkflowDiagram stepProgress={stepProgress} />}

      {/* Two columns: History + Active Report */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* History */}
        <section className="rounded-xl border border-gray-800 bg-gray-900/60 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
            <h2 className="text-sm font-semibold text-gray-200">History</h2>
            <button type="button" onClick={loadHistory} title="Refresh analysis history" className="text-gray-500 hover:text-gray-300">
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
          {analyses.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-gray-600">No analyses yet</p>
          ) : (
            <div className="divide-y divide-gray-800 max-h-[500px] overflow-y-auto">
              {analyses.map(a => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => loadAnalysis(a.id)}
                  className={`flex items-center gap-3 w-full px-4 py-3 text-left hover:bg-gray-800/50 transition-colors ${
                    activeAnalysis?.id === a.id ? 'bg-blue-500/10 border-r-2 border-blue-400' : ''
                  }`}
                >
                  <StatusIcon status={a.status} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-gray-300 truncate">
                      {a.graph_name.replace(/_/g, ' ')}
                    </div>
                    <div className="text-[10px] text-gray-600 truncate">
                      {a.new_doc_name}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); deleteAnalysis(a.id); }}
                    title={`Delete analysis ${a.id}`}
                    className="text-gray-700 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Active Report */}
        <section className="lg:col-span-3 space-y-4">
          {!activeAnalysis ? (
            <div className="rounded-xl border border-gray-800 bg-gray-900/60 py-16 text-center">
              <Shield className="h-10 w-10 text-gray-700 mx-auto mb-3" />
              <p className="text-sm text-gray-500">Upload documents or select an analysis from history</p>
            </div>
          ) : activeAnalysis.status === 'running' && !isRunning ? (
            <div className="rounded-xl border border-blue-900/40 bg-blue-950/20 p-6 text-center">
              <Loader2 className="h-8 w-8 text-blue-400 mx-auto mb-3 animate-spin" />
              <p className="text-sm text-blue-300">Analysis in progress...</p>
            </div>
          ) : activeAnalysis.status === 'failed' ? (
            <div className="rounded-xl border border-red-900/40 bg-red-950/20 p-6">
              <h3 className="text-sm font-semibold text-red-400 mb-2">Analysis Failed</h3>
              <p className="text-xs text-red-300/70">{activeAnalysis.error}</p>
            </div>
          ) : activeAnalysis.status === 'completed' ? (
            <>
              {/* Executive Summary (agentic mode) */}
              {activeAnalysis.summary?.executive_summary && (
                <ExecutiveSummary summary={activeAnalysis.summary} />
              )}

              {/* Summary Banner */}
              {activeAnalysis.summary && (
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
                  <p className="text-sm text-gray-200 font-medium">{activeAnalysis.summary.headline}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    Old: {activeAnalysis.old_doc_name} ({activeAnalysis.summary.old_provision_count} provisions)
                    {' → '}
                    New: {activeAnalysis.new_doc_name} ({activeAnalysis.summary.new_provision_count} provisions)
                  </p>
                </div>
              )}

              {/* Stats Grid */}
              {activeAnalysis.stats && <StatsGrid stats={activeAnalysis.stats} />}

              {/* Severity Bars */}
              {activeAnalysis.stats && <SeverityBars stats={activeAnalysis.stats} />}

              {/* Key Findings (agentic) */}
              {activeAnalysis.summary?.key_findings && activeAnalysis.summary.key_findings.length > 0 && (
                <KeyFindings findings={activeAnalysis.summary.key_findings} />
              )}

              {/* Recommendations (agentic) */}
              {activeAnalysis.summary?.recommendations && activeAnalysis.summary.recommendations.length > 0 && (
                <RecommendationsPanel recommendations={activeAnalysis.summary.recommendations} />
              )}

              {/* Filter + Export */}
              <div className="flex items-center justify-between">
                <div className="flex gap-2">
                  {['all', 'breaking', 'material', 'cosmetic'].map(s => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setFilterSeverity(s)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        filterSeverity === s
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-800 text-gray-400 hover:text-gray-200'
                      }`}
                    >
                      {s === 'all' ? 'All Changes' : s.charAt(0).toUpperCase() + s.slice(1)}
                      {s !== 'all' && activeAnalysis.stats && (
                        <span className="ml-1 opacity-60">
                          ({activeAnalysis.stats[`severity_${s}` as keyof Stats]})
                        </span>
                      )}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <a
                    href={`/api/kg/impact/analyses/${activeAnalysis.id}/export/csv`}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
                  >
                    <Download className="h-3 w-3" /> CSV
                  </a>
                  <a
                    href={`/api/kg/impact/analyses/${activeAnalysis.id}/export/json`}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
                  >
                    <Download className="h-3 w-3" /> JSON
                  </a>
                </div>
              </div>

              {/* Change Items */}
              <div className="space-y-2">
                {filteredItems.map(item => (
                  <ImpactItemCard
                    key={item.id}
                    item={item}
                    expanded={expandedItems.has(item.id)}
                    onToggle={() => toggleItem(item.id)}
                  />
                ))}
                {filteredItems.length === 0 && (
                  <p className="text-center text-xs text-gray-600 py-8">
                    No changes match the selected filter
                  </p>
                )}
              </div>
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}

/* ═══ WORKFLOW PROCESS FLOW DIAGRAM ═════════════════════════════ */

function WorkflowDiagram({ stepProgress }: { stepProgress: Record<string, StepProgress> }) {
  return (
    <div className="rounded-xl border border-violet-900/30 bg-gradient-to-br from-violet-950/20 to-gray-900/60 p-6">
      <div className="flex items-center gap-2 mb-5">
        <Brain className="h-5 w-5 text-violet-400" />
        <h2 className="text-sm font-semibold text-violet-200">Agentic Analysis Pipeline</h2>
        <Loader2 className="h-3.5 w-3.5 text-violet-400 animate-spin ml-auto" />
        <span className="text-[10px] text-violet-400">Processing...</span>
      </div>

      {/* Flow Diagram */}
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {WORKFLOW_STEPS.map((step, idx) => {
          const progress = stepProgress[step.id];
          const status = progress?.status ?? 'pending';
          const Icon = step.icon;

          return (
            <div key={step.id} className="flex items-start shrink-0">
              {/* Step Node */}
              <div className="flex flex-col items-center w-36">
                {/* Circle */}
                <div className={`
                  relative w-12 h-12 rounded-full flex items-center justify-center border-2 transition-all duration-500
                  ${status === 'completed' ? 'border-emerald-400 bg-emerald-500/20 shadow-lg shadow-emerald-500/20' :
                    status === 'running' ? 'border-violet-400 bg-violet-500/20 shadow-lg shadow-violet-500/20 animate-pulse' :
                    status === 'failed' ? 'border-red-400 bg-red-500/20' :
                    'border-gray-700 bg-gray-800/50'}
                `}>
                  {status === 'running' ? (
                    <Loader2 className="h-5 w-5 text-violet-400 animate-spin" />
                  ) : status === 'completed' ? (
                    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                  ) : status === 'failed' ? (
                    <XCircle className="h-5 w-5 text-red-400" />
                  ) : (
                    <Icon className="h-5 w-5 text-gray-500" />
                  )}
                  {/* Step number badge */}
                  <span className={`absolute -top-1 -right-1 text-[9px] w-4 h-4 rounded-full flex items-center justify-center font-bold
                    ${status === 'completed' ? 'bg-emerald-500 text-white' :
                      status === 'running' ? 'bg-violet-500 text-white' :
                      'bg-gray-700 text-gray-400'}
                  `}>{idx + 1}</span>
                </div>

                {/* Label */}
                <span className={`text-[11px] font-medium mt-2 text-center leading-tight
                  ${status === 'completed' ? 'text-emerald-300' :
                    status === 'running' ? 'text-violet-300' :
                    status === 'failed' ? 'text-red-300' :
                    'text-gray-500'}
                `}>{step.label}</span>

                {/* Description / Progress message */}
                <span className="text-[9px] text-gray-500 mt-0.5 text-center max-w-[140px] leading-tight">
                  {progress?.message || step.desc}
                </span>
              </div>

              {/* Connector Arrow */}
              {idx < WORKFLOW_STEPS.length - 1 && (
                <div className="flex items-center mt-5 px-1">
                  <div className={`h-0.5 w-6 transition-colors duration-500
                    ${status === 'completed' ? 'bg-emerald-500' :
                      status === 'running' ? 'bg-violet-500' : 'bg-gray-700'}
                  `} />
                  <div className={`
                    w-0 h-0 border-t-[4px] border-t-transparent border-b-[4px] border-b-transparent border-l-[6px] transition-colors duration-500
                    ${status === 'completed' ? 'border-l-emerald-500' :
                      status === 'running' ? 'border-l-violet-500' : 'border-l-gray-700'}
                  `} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══ EXECUTIVE SUMMARY (agentic result) ═══════════════════════ */

function ExecutiveSummary({ summary }: { summary: SummaryExtended }) {
  const risk = summary.risk_assessment;
  const riskColors: Record<string, string> = {
    critical: 'text-red-400 bg-red-500/10 border-red-500/20',
    high: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
    low: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  };
  const riskClass = riskColors[risk?.overall_risk ?? ''] ?? riskColors.medium;

  return (
    <div className="rounded-xl border border-violet-900/30 bg-gradient-to-br from-violet-950/10 to-gray-900/60 p-6 space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <Brain className="h-5 w-5 text-violet-400" />
        <h2 className="text-sm font-semibold text-violet-200">AI-Generated Executive Summary</h2>
        {risk && (
          <span className={`ml-auto text-[10px] px-2.5 py-1 rounded-full border font-semibold uppercase ${riskClass}`}>
            {risk.overall_risk} risk
          </span>
        )}
      </div>

      <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
        {summary.executive_summary}
      </p>

      {/* Risk flags */}
      {risk && (risk.requires_board_review || risk.regulatory_deadline_risk) && (
        <div className="flex gap-3">
          {risk.requires_board_review && (
            <span className="text-[10px] px-2 py-1 rounded bg-red-500/10 text-red-400 border border-red-500/20">
              ⚠ Requires Board Review
            </span>
          )}
          {risk.regulatory_deadline_risk && (
            <span className="text-[10px] px-2 py-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
              ⚠ Regulatory Deadline Risk
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/* ═══ KEY FINDINGS ═══════════════════════════════════════════════ */

function KeyFindings({ findings }: { findings: string[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <AlertCircle className="h-3.5 w-3.5" /> Key Findings
      </h3>
      <ul className="space-y-2">
        {findings.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-gray-300">
            <span className="text-violet-400 font-bold mt-0.5 shrink-0">•</span>
            {f}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ═══ RECOMMENDATIONS PANEL ═════════════════════════════════════ */

function RecommendationsPanel({ recommendations }: {
  recommendations: Array<{ priority: string; action: string; owner: string; timeline: string }>;
}) {
  const prioColors: Record<string, string> = {
    P1: 'text-red-400 bg-red-500/10 border-red-500/20',
    P2: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    P3: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <CheckCircle2 className="h-3.5 w-3.5" /> Recommended Actions
      </h3>
      <div className="space-y-2">
        {recommendations.map((rec, i) => {
          const pClass = prioColors[rec.priority] ?? prioColors.P3;
          return (
            <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-gray-800/40">
              <span className={`text-[10px] px-2 py-0.5 rounded-full border font-bold shrink-0 mt-0.5 ${pClass}`}>
                {rec.priority}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-gray-200">{rec.action}</p>
                <div className="flex gap-3 mt-1">
                  <span className="text-[10px] text-gray-500">Owner: {rec.owner}</span>
                  <span className="text-[10px] text-gray-500">Timeline: {rec.timeline}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══ Original Sub-components ═══════════════════════════════════ */

function FileDropZone({ label, file, onFile, inputRef, invalid = false }: {
  label: string;
  file: File | null;
  onFile: (f: File | null) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  invalid?: boolean;
}) {
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  };

  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1.5">{label}</label>
      <div
        onDragOver={e => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 cursor-pointer transition-colors ${
          file
            ? 'border-emerald-500/30 bg-emerald-950/20'
            : invalid
              ? 'border-red-500/60 bg-red-950/20 hover:border-red-400'
            : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
        }`}
      >
        {file ? (
          <>
            <FileText className="h-4 w-4 text-emerald-400 shrink-0" />
            <span className="text-xs text-emerald-300 truncate">{file.name}</span>
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onFile(null); }}
              title={`Remove ${label}`}
              className="ml-auto text-gray-500 hover:text-red-400"
            >
              <XCircle className="h-3.5 w-3.5" />
            </button>
          </>
        ) : (
          <>
            <Upload className="h-4 w-4 text-gray-600" />
            <span className="text-xs text-gray-500">Drop or click to upload</span>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          title={label}
          accept=".txt,.md,.pdf,.docx"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }}
        />
      </div>
    </div>
  );
}

function StatsGrid({ stats }: { stats: Stats }) {
  const cells = [
    { label: 'Total Changes', value: stats.total_changes, color: 'text-white' },
    { label: 'Added', value: stats.added_count, color: 'text-emerald-400' },
    { label: 'Removed', value: stats.removed_count, color: 'text-red-400' },
    { label: 'Modified', value: stats.modified_count, color: 'text-amber-400' },
    { label: 'Affected Rules', value: stats.affected_rules_count, color: 'text-blue-400' },
    { label: 'Impact %', value: `${stats.impact_percentage}%`, color: 'text-violet-400' },
  ];
  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
      {cells.map(c => (
        <div key={c.label} className="rounded-xl border border-gray-800 bg-gray-900/60 px-4 py-3 text-center">
          <div className={`text-xl font-bold ${c.color}`}>{c.value}</div>
          <div className="text-[10px] text-gray-500 mt-1">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function SeverityBars({ stats }: { stats: Stats }) {
  const total = stats.total_changes || 1;
  const items = [
    { key: 'breaking', count: stats.severity_breaking, color: 'bg-red-500' },
    { key: 'material', count: stats.severity_material, color: 'bg-amber-500' },
    { key: 'cosmetic', count: stats.severity_cosmetic, color: 'bg-blue-500' },
  ];
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Severity Distribution</h3>
      <div className="flex rounded-full overflow-hidden h-3 bg-gray-800">
        {items.map(it => (
          it.count > 0 && (
            <div
              key={it.key}
              className={`${it.color} transition-all`}
              style={{ width: `${(it.count / total) * 100}%` }}
              title={`${it.key}: ${it.count}`}
            />
          )
        ))}
      </div>
      <div className="flex gap-4 mt-2">
        {items.map(it => (
          <span key={it.key} className="text-xs text-gray-500">
            <span className={`inline-block h-2 w-2 rounded-full ${it.color} mr-1`} />
            {it.key.charAt(0).toUpperCase() + it.key.slice(1)}: {it.count}
          </span>
        ))}
      </div>
    </div>
  );
}

function ImpactItemCard({ item, expanded, onToggle }: {
  item: ImpactItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const sev = SEV_CONFIG[item.severity];
  const change = CHANGE_CONFIG[item.change_type];
  const SevIcon = sev.icon;

  return (
    <div className={`rounded-xl border ${sev.border} ${sev.bg} overflow-hidden`}>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-3 w-full px-5 py-3.5 text-left"
      >
        {expanded ? <ChevronDown className="h-4 w-4 text-gray-500 shrink-0" /> : <ChevronRight className="h-4 w-4 text-gray-500 shrink-0" />}
        <SevIcon className={`h-4 w-4 ${sev.color} shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-[10px] px-2 py-0.5 rounded-full ${sev.bg} ${sev.color} border ${sev.border} font-medium`}>
              {sev.label}
            </span>
            <span className={`text-[10px] ${change.color} font-medium`}>{change.label}</span>
          </div>
          <p className="text-xs text-gray-300 mt-1 line-clamp-2">{item.description || item.provision_text}</p>
        </div>
        <span className="text-xs text-gray-500 shrink-0">
          {item.affected_rules.length} rule{item.affected_rules.length !== 1 ? 's' : ''}
        </span>
      </button>

      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800/50">
          {/* Recommendation */}
          <div className="mt-3 mb-3 p-3 rounded-lg bg-gray-800/50">
            <p className="text-xs text-gray-400">
              <span className="font-semibold text-gray-300">Recommendation: </span>
              {item.recommendation}
            </p>
          </div>

          {/* Full provision text */}
          <details className="mb-3">
            <summary className="text-[10px] text-gray-500 cursor-pointer hover:text-gray-300">
              Full provision text
            </summary>
            <p className="text-xs text-gray-400 mt-2 whitespace-pre-wrap">{item.provision_text}</p>
          </details>

          {/* Affected Rules */}
          {item.affected_rules.length > 0 && (
            <div>
              <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Affected Rules
              </h4>
              <div className="space-y-1.5">
                {item.affected_rules.map(r => (
                  <div
                    key={r.rule_id}
                    className="flex items-start gap-3 px-3 py-2 rounded-lg bg-gray-800/30"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-gray-300 truncate">{r.rule_name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-gray-600">{r.rule_type}</span>
                        <span className="text-[10px] text-gray-700">·</span>
                        <RiskBadge level={r.risk_level} />
                        {r.relevance && (
                          <>
                            <span className="text-[10px] text-gray-700">·</span>
                            <span className={`text-[10px] font-medium ${
                              r.relevance === 'high' ? 'text-red-400' :
                              r.relevance === 'medium' ? 'text-amber-400' : 'text-gray-500'
                            }`}>{r.relevance} relevance</span>
                          </>
                        )}
                      </div>
                      {r.reasoning && (
                        <p className="text-[10px] text-gray-500 mt-1 italic">{r.reasoning}</p>
                      )}
                    </div>
                    {r.matching_terms && r.matching_terms.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {r.matching_terms.slice(0, 4).map(t => (
                          <span key={t} className="text-[9px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const cfg: Record<string, string> = {
    critical: 'text-red-400',
    high: 'text-amber-400',
    medium: 'text-yellow-400',
    low: 'text-emerald-400',
  };
  return <span className={`text-[10px] font-medium ${cfg[level] ?? 'text-gray-500'}`}>{level}</span>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />;
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin shrink-0" />;
  if (status === 'failed') return <AlertTriangle className="h-3.5 w-3.5 text-red-400 shrink-0" />;
  return <CircleDot className="h-3.5 w-3.5 text-gray-500 shrink-0" />;
}
