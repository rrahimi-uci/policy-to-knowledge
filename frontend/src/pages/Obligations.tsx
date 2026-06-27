import { useEffect, useState, useCallback } from 'react';
import { apiUrl } from '@/config';
import {
  Shield, CheckCircle2, AlertCircle, XCircle, MinusCircle,
  ChevronDown, ChevronRight, Plus, Trash2, Download, Sparkles,
  RefreshCw, Loader2, ClipboardList, FileText, Scale, Calendar,
  MapPin, BookOpen, AlertTriangle, Info,
} from 'lucide-react';

/* ─── Types ─────────────────────────────────────────────────── */

interface GraphSummary {
  name: string;
  provider: string;
  rules: number;
  entities: number;
}

interface Control {
  id: number;
  obligation_id: number;
  control_name: string;
  control_type: string;
  description: string;
  evidence_url: string;
  owner: string;
  created_at: string;
}

interface SourceReference {
  chunk_path?: string;
  section_id?: string;
  source_text?: string;
}

interface ApplicabilityScope {
  loan_types?: string[];
  occupancy_types?: string[];
  transaction_types?: string[];
}

interface Obligation {
  id: number;
  graph_name: string;
  provider: string;
  rule_id: string;
  rule_name: string;
  rule_type: string;
  risk_level: string;
  status: string;
  notes: string;
  controls: Control[];
  updated_at: string;
  description?: string;
  source_reference?: string | SourceReference;
  jurisdiction?: string;
  mandatory?: number;
  effective_date?: string;
  conditions?: string | string[];
  consequences?: string | string[];
  exceptions?: string | string[];
  applicability_scope?: string | ApplicabilityScope;
  audit_frequency?: string;
  enforcement_action?: string;
}

interface ObligationDetail extends Obligation {
  source_reference?: SourceReference;
  conditions?: string[];
  consequences?: string[];
  exceptions?: string[];
  applicability_scope?: ApplicabilityScope;
}

interface Heatmap {
  total_obligations: number;
  by_status: Record<string, number>;
  by_rule_type: Record<string, Record<string, number>>;
  by_risk_level: Record<string, Record<string, number>>;
  compliance_score: number;
}

interface Suggestion {
  control_name: string;
  control_type: string;
  description: string;
}

interface ObligationStats {
  total: number;
  mandatory_count: number;
  optional_count: number;
  with_effective_date: number;
  jurisdictions: Record<string, number>;
  by_audit_frequency: Record<string, number>;
}

/* ─── Constants ──────────────────────────────────────────────── */

const STATUS_CONFIG: Record<string, { color: string; bg: string; border: string; icon: typeof CheckCircle2; label: string }> = {
  mapped: { color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', icon: CheckCircle2, label: 'Mapped' },
  'partially-mapped': { color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', icon: AlertCircle, label: 'Partial' },
  unmapped: { color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20', icon: XCircle, label: 'Unmapped' },
  exempted: { color: 'text-gray-400', bg: 'bg-gray-500/10', border: 'border-gray-500/20', icon: MinusCircle, label: 'Exempt' },
};

const STATUSES = ['unmapped', 'partially-mapped', 'mapped', 'exempted'];
const CONTROL_TYPES = ['policy', 'procedure', 'technical-control', 'manual-control', 'audit', 'training'];
const RISK_COLORS: Record<string, string> = { critical: 'text-red-400', high: 'text-amber-400', medium: 'text-yellow-400' };

/* ─── Component ──────────────────────────────────────────────── */

export default function Obligations() {
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [selectedGraph, setSelectedGraph] = useState('');
  const [obligations, setObligations] = useState<Obligation[]>([]);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterRisk, setFilterRisk] = useState('all');
  const [filterType, setFilterType] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [seeding, setSeeding] = useState(false);
  const [suggestions, setSuggestions] = useState<Record<string, Suggestion[]>>({});
  const [addingControl, setAddingControl] = useState<string | null>(null);
  const [controlForm, setControlForm] = useState({ control_name: '', control_type: 'policy', description: '', owner: '' });
  const [obligationDetails, setObligationDetails] = useState<Record<string, ObligationDetail>>({});
  const [stats, setStats] = useState<ObligationStats | null>(null);
  const [filterJurisdiction, setFilterJurisdiction] = useState('all');
  const [filterMandatory, setFilterMandatory] = useState('all');

  // Load graphs
  useEffect(() => {
    fetch(apiUrl('kg/graphs'))
      .then(r => r.json())
      .then(d => setGraphs(d.graphs ?? []))
      .catch(() => {});
  }, []);

  // Load obligations when graph selected
  const loadObligations = useCallback(async () => {
    if (!selectedGraph) return;
    const res = await fetch(apiUrl(`kg/obligations/${selectedGraph}?provider=openai`));
    if (res.ok) {
      const d = await res.json();
      setObligations(d.obligations ?? []);
      setHeatmap(d.heatmap ?? null);
    }
  }, [selectedGraph]);

  useEffect(() => { loadObligations(); }, [loadObligations]);

  // Load stats when obligations change
  useEffect(() => {
    if (!selectedGraph || obligations.length === 0) { setStats(null); return; }
    fetch(apiUrl(`kg/obligations/${selectedGraph}/stats?provider=openai`))
      .then(r => r.ok ? r.json() : null)
      .then(d => setStats(d))
      .catch(() => {});
  }, [selectedGraph, obligations]);

  // Load obligation detail when expanded
  const loadDetail = useCallback(async (ruleId: string) => {
    if (obligationDetails[ruleId]) return;
    const res = await fetch(apiUrl(`kg/obligations/${selectedGraph}/${ruleId}/detail?provider=openai`));
    if (res.ok) {
      const d = await res.json();
      setObligationDetails(prev => ({ ...prev, [ruleId]: d }));
    }
  }, [selectedGraph, obligationDetails]);

  // Seed obligations
  const seedObligations = useCallback(async () => {
    if (!selectedGraph) return;
    setSeeding(true);
    try {
      const res = await fetch(apiUrl(`kg/obligations/${selectedGraph}/seed?provider=openai`), { method: 'POST' });
      if (res.ok) await loadObligations();
    } finally {
      setSeeding(false);
    }
  }, [selectedGraph, loadObligations]);

  // Update status
  const updateStatus = useCallback(async (ruleId: string, status: string, notes?: string) => {
    const body: Record<string, string> = { status };
    if (notes !== undefined) body.notes = notes;
    await fetch(apiUrl(`kg/obligations/${selectedGraph}/${ruleId}?provider=openai`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await loadObligations();
  }, [selectedGraph, loadObligations]);

  // Add control
  const addControl = useCallback(async (ruleId: string) => {
    if (!controlForm.control_name.trim()) return;
    await fetch(apiUrl(`kg/obligations/${selectedGraph}/${ruleId}/controls?provider=openai`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(controlForm),
    });
    setAddingControl(null);
    setControlForm({ control_name: '', control_type: 'policy', description: '', owner: '' });
    await loadObligations();
  }, [selectedGraph, controlForm, loadObligations]);

  // Delete control
  const deleteControl = useCallback(async (controlId: number) => {
    await fetch(apiUrl(`kg/obligations/controls/${controlId}`), { method: 'DELETE' });
    await loadObligations();
  }, [loadObligations]);

  // Get suggestions
  const loadSuggestions = useCallback(async (ruleId: string) => {
    const res = await fetch(apiUrl(`kg/obligations/${selectedGraph}/${ruleId}/suggest?provider=openai`));
    if (res.ok) {
      const d = await res.json();
      setSuggestions(prev => ({ ...prev, [ruleId]: d.suggestions ?? [] }));
    }
  }, [selectedGraph]);

  // Apply suggestion
  const applySuggestion = useCallback(async (ruleId: string, s: Suggestion) => {
    await fetch(apiUrl(`kg/obligations/${selectedGraph}/${ruleId}/controls?provider=openai`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(s),
    });
    await loadObligations();
  }, [selectedGraph, loadObligations]);

  // Filtering
  const filtered = obligations.filter(ob => {
    if (filterStatus !== 'all' && ob.status !== filterStatus) return false;
    if (filterRisk !== 'all' && ob.risk_level !== filterRisk) return false;
    if (filterType !== 'all' && ob.rule_type !== filterType) return false;
    if (filterJurisdiction !== 'all' && (ob.jurisdiction || '') !== filterJurisdiction) return false;
    if (filterMandatory !== 'all') {
      const isMand = ob.mandatory !== 0;
      if (filterMandatory === 'mandatory' && !isMand) return false;
      if (filterMandatory === 'optional' && isMand) return false;
    }
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      if (!ob.rule_name.toLowerCase().includes(q) && !ob.rule_id.toLowerCase().includes(q)
        && !(ob.description || '').toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const ruleTypes = [...new Set(obligations.map(o => o.rule_type).filter(Boolean))];
  const riskLevels = [...new Set(obligations.map(o => o.risk_level).filter(Boolean))];
  const jurisdictions = [...new Set(obligations.map(o => o.jurisdiction).filter((j): j is string => Boolean(j)))];

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
            <ClipboardList className="h-6 w-6 text-emerald-400" />
            Obligation Register &amp; Gap Analysis
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Track compliance obligations, map internal controls, and identify coverage gaps
          </p>
        </div>
      </div>

      {/* Graph Selector + Seed */}
      <div className="flex items-end gap-4">
        <div className="flex-1 max-w-xs">
          <label className="block text-xs text-gray-500 mb-1.5">Knowledge Graph</label>
          <select
            value={selectedGraph}
            onChange={e => { setSelectedGraph(e.target.value); setExpandedId(null); }}
            className="w-full rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 px-3 py-2 focus:border-blue-500 focus:outline-none"
            title="Select knowledge graph"
          >
            <option value="">Select a graph...</option>
            {graphs.map(g => (
              <option key={`${g.name}-${g.provider}`} value={g.name}>
                {g.name.replace(/_/g, ' ')} ({g.rules} rules)
              </option>
            ))}
          </select>
        </div>
        {selectedGraph && (
          <button
            type="button"
            onClick={seedObligations}
            disabled={seeding}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-50"
            title="Initialize obligations from graph rules"
          >
            {seeding ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {seeding ? 'Seeding...' : obligations.length > 0 ? 'Resync Rules' : 'Initialize Obligations'}
          </button>
        )}
        {selectedGraph && obligations.length > 0 && (
          <div className="flex gap-2">
            <a
              href={`/api/kg/obligations/${selectedGraph}/export/csv?provider=openai`}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
              title="Export CSV (GRC-compatible)"
            >
              <Download className="h-3.5 w-3.5" /> CSV
            </a>
            <a
              href={`/api/kg/obligations/${selectedGraph}/export/json?provider=openai`}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
              title="Export JSON"
            >
              <Download className="h-3.5 w-3.5" /> JSON
            </a>
          </div>
        )}
      </div>

      {!selectedGraph ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 py-16 text-center">
          <ClipboardList className="h-10 w-10 text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-500">Select a knowledge graph to view its obligation register</p>
        </div>
      ) : obligations.length === 0 ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 py-16 text-center">
          <Shield className="h-10 w-10 text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-500 mb-3">No obligations seeded yet</p>
          <button
            type="button"
            onClick={seedObligations}
            disabled={seeding}
            className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            Initialize from graph rules &rarr;
          </button>
        </div>
      ) : (
        <>
          {/* Compliance Heatmap */}
          {heatmap && <ComplianceHeatmap heatmap={heatmap} />}

          {/* Stats Panel */}
          {stats && stats.total > 0 && <StatsPanel stats={stats} />}

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="text"
              placeholder="Search rules..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 px-3 py-1.5 w-48 focus:border-blue-500 focus:outline-none"
            />
            <FilterPills
              label="Status"
              options={['all', ...STATUSES]}
              value={filterStatus}
              onChange={setFilterStatus}
              counts={heatmap?.by_status}
            />
            <FilterPills
              label="Risk"
              options={['all', ...riskLevels]}
              value={filterRisk}
              onChange={setFilterRisk}
            />
            <FilterPills
              label="Type"
              options={['all', ...ruleTypes]}
              value={filterType}
              onChange={setFilterType}
            />
            {jurisdictions.length > 0 && (
              <FilterPills
                label="Jurisdiction"
                options={['all', ...jurisdictions]}
                value={filterJurisdiction}
                onChange={setFilterJurisdiction}
              />
            )}
            <FilterPills
              label="Mandatory"
              options={['all', 'mandatory', 'optional']}
              value={filterMandatory}
              onChange={setFilterMandatory}
            />
            <span className="text-xs text-gray-600 ml-auto">{filtered.length} of {obligations.length}</span>
          </div>

          {/* Obligation List */}
          <div className="space-y-2">
            {filtered.map(ob => (
              <ObligationCard
                key={ob.rule_id}
                ob={ob}
                detail={obligationDetails[ob.rule_id]}
                expanded={expandedId === ob.rule_id}
                onToggle={() => {
                  const opening = expandedId !== ob.rule_id;
                  setExpandedId(opening ? ob.rule_id : null);
                  if (opening) loadDetail(ob.rule_id);
                }}
                onStatusChange={(s) => updateStatus(ob.rule_id, s)}
                onNotesChange={(n) => updateStatus(ob.rule_id, ob.status, n)}
                suggestions={suggestions[ob.rule_id]}
                onLoadSuggestions={() => loadSuggestions(ob.rule_id)}
                onApplySuggestion={(s) => applySuggestion(ob.rule_id, s)}
                addingControl={addingControl === ob.rule_id}
                onToggleAddControl={() => setAddingControl(addingControl === ob.rule_id ? null : ob.rule_id)}
                controlForm={controlForm}
                onControlFormChange={setControlForm}
                onAddControl={() => addControl(ob.rule_id)}
                onDeleteControl={deleteControl}
              />
            ))}
            {filtered.length === 0 && (
              <p className="text-center text-xs text-gray-600 py-8">No obligations match the filters</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ═══ Sub-components ═════════════════════════════════════════════ */

function ComplianceHeatmap({ heatmap }: { heatmap: Heatmap }) {
  const total = heatmap.total_obligations || 1;
  const mapped = heatmap.by_status.mapped ?? 0;
  const partial = heatmap.by_status['partially-mapped'] ?? 0;
  const unmapped = heatmap.by_status.unmapped ?? 0;
  const exempted = heatmap.by_status.exempted ?? 0;

  const scoreColor = heatmap.compliance_score >= 80 ? 'text-emerald-400'
    : heatmap.compliance_score >= 50 ? 'text-amber-400' : 'text-red-400';

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <div className="flex items-start justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-200">Compliance Heatmap</h2>
        <div className="text-right">
          <div className={`text-3xl font-bold ${scoreColor}`}>{heatmap.compliance_score}%</div>
          <div className="text-[10px] text-gray-500">Compliance Score</div>
        </div>
      </div>

      {/* Status bar */}
      <div className="flex rounded-full overflow-hidden h-5 bg-gray-800 mb-3">
        {mapped > 0 && (
          <div className="bg-emerald-500 flex items-center justify-center text-[9px] text-white font-medium"
            style={{ width: `${(mapped / total) * 100}%` }}>{mapped}</div>
        )}
        {partial > 0 && (
          <div className="bg-amber-500 flex items-center justify-center text-[9px] text-white font-medium"
            style={{ width: `${(partial / total) * 100}%` }}>{partial}</div>
        )}
        {unmapped > 0 && (
          <div className="bg-red-500 flex items-center justify-center text-[9px] text-white font-medium"
            style={{ width: `${(unmapped / total) * 100}%` }}>{unmapped}</div>
        )}
        {exempted > 0 && (
          <div className="bg-gray-500 flex items-center justify-center text-[9px] text-white font-medium"
            style={{ width: `${(exempted / total) * 100}%` }}>{exempted}</div>
        )}
      </div>
      <div className="flex gap-4">
        <span className="text-xs text-gray-500"><span className="inline-block h-2 w-2 rounded-full bg-emerald-500 mr-1" />Mapped: {mapped}</span>
        <span className="text-xs text-gray-500"><span className="inline-block h-2 w-2 rounded-full bg-amber-500 mr-1" />Partial: {partial}</span>
        <span className="text-xs text-gray-500"><span className="inline-block h-2 w-2 rounded-full bg-red-500 mr-1" />Unmapped: {unmapped}</span>
        <span className="text-xs text-gray-500"><span className="inline-block h-2 w-2 rounded-full bg-gray-500 mr-1" />Exempt: {exempted}</span>
      </div>

      {/* Risk-level breakdown */}
      {Object.keys(heatmap.by_risk_level).length > 0 && (
        <div className="mt-4 grid grid-cols-3 gap-3">
          {Object.entries(heatmap.by_risk_level).map(([risk, statuses]) => {
            const rTotal = Object.values(statuses).reduce((a, b) => a + b, 0);
            const rMapped = (statuses.mapped ?? 0) + (statuses['partially-mapped'] ?? 0) * 0.5;
            const pct = Math.round((rMapped / Math.max(rTotal, 1)) * 100);
            return (
              <div key={risk} className="rounded-lg border border-gray-800 bg-gray-800/30 px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className={`text-xs font-medium ${RISK_COLORS[risk] ?? 'text-gray-400'}`}>
                    {risk.charAt(0).toUpperCase() + risk.slice(1)}
                  </span>
                  <span className="text-xs text-gray-500">{rTotal}</span>
                </div>
                <div className="flex rounded-full overflow-hidden h-1.5 bg-gray-800 mt-1.5">
                  <div className="bg-emerald-500" style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[10px] text-gray-600 mt-1">{pct}% covered</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function FilterPills({ label, options, value, onChange, counts }: {
  label: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
  counts?: Record<string, number>;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-gray-600 mr-1">{label}:</span>
      {options.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
            value === opt ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'
          }`}
        >
          {opt === 'all' ? 'All' : opt.replace(/-/g, ' ')}
          {counts && opt !== 'all' && counts[opt] !== undefined && (
            <span className="ml-0.5 opacity-60">({counts[opt]})</span>
          )}
        </button>
      ))}
    </div>
  );
}

function ObligationCard({
  ob, detail, expanded, onToggle, onStatusChange, onNotesChange,
  suggestions, onLoadSuggestions, onApplySuggestion,
  addingControl, onToggleAddControl, controlForm, onControlFormChange,
  onAddControl, onDeleteControl,
}: {
  ob: Obligation;
  detail?: ObligationDetail;
  expanded: boolean;
  onToggle: () => void;
  onStatusChange: (s: string) => void;
  onNotesChange: (n: string) => void;
  suggestions?: Suggestion[];
  onLoadSuggestions: () => void;
  onApplySuggestion: (s: Suggestion) => void;
  addingControl: boolean;
  onToggleAddControl: () => void;
  controlForm: { control_name: string; control_type: string; description: string; owner: string };
  onControlFormChange: (f: typeof controlForm) => void;
  onAddControl: () => void;
  onDeleteControl: (id: number) => void;
}) {
  const st = STATUS_CONFIG[ob.status] ?? STATUS_CONFIG.unmapped;
  const StIcon = st.icon;

  return (
    <div className={`rounded-xl border ${st.border} ${st.bg} overflow-hidden`}>
      {/* Header row */}
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-3 w-full px-5 py-3 text-left"
      >
        {expanded
          ? <ChevronDown className="h-4 w-4 text-gray-500 shrink-0" />
          : <ChevronRight className="h-4 w-4 text-gray-500 shrink-0" />
        }
        <StIcon className={`h-4 w-4 ${st.color} shrink-0`} />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-200 truncate">{ob.rule_name || ob.rule_id}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-gray-600">{ob.rule_type}</span>
            <span className="text-[10px] text-gray-700">·</span>
            <span className={`text-[10px] font-medium ${RISK_COLORS[ob.risk_level] ?? 'text-gray-500'}`}>
              {ob.risk_level}
            </span>
            {ob.jurisdiction && (
              <>
                <span className="text-[10px] text-gray-700">·</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  {ob.jurisdiction}
                </span>
              </>
            )}
            {ob.mandatory === 0 && (
              <>
                <span className="text-[10px] text-gray-700">·</span>
                <span className="text-[10px] text-gray-500 italic">optional</span>
              </>
            )}
            {ob.effective_date && (
              <>
                <span className="text-[10px] text-gray-700">·</span>
                <span className="text-[10px] text-gray-500 flex items-center gap-0.5">
                  <Calendar className="h-2.5 w-2.5" />{ob.effective_date}
                </span>
              </>
            )}
          </div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full ${st.bg} ${st.color} border ${st.border} font-medium`}>
          {st.label}
        </span>
        {ob.controls.length > 0 && (
          <span className="text-[10px] text-gray-500">{ob.controls.length} control{ob.controls.length !== 1 ? 's' : ''}</span>
        )}
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="px-5 pb-4 border-t border-gray-800/50 space-y-4">
          {/* Enriched detail section */}
          {detail && <ObligationDetailPanel detail={detail} />}

          {/* Status selector */}
          <div className="flex items-center gap-3 mt-3">
            <span className="text-xs text-gray-500">Status:</span>
            {STATUSES.map(s => {
              const cfg = STATUS_CONFIG[s];
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => onStatusChange(s)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                    ob.status === s
                      ? `${cfg.bg} ${cfg.color} border ${cfg.border}`
                      : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {cfg.label}
                </button>
              );
            })}
          </div>

          {/* Notes */}
          <div>
            <label className="block text-[10px] text-gray-500 mb-1">Notes</label>
            <textarea
              value={ob.notes}
              onChange={e => onNotesChange(e.target.value)}
              rows={2}
              placeholder="Add compliance notes..."
              className="w-full rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none resize-none"
            />
          </div>

          {/* Controls */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                Linked Controls ({ob.controls.length})
              </h4>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onLoadSuggestions}
                  className="flex items-center gap-1 text-[10px] text-violet-400 hover:text-violet-300 transition-colors"
                  title="Get AI-suggested controls"
                >
                  <Sparkles className="h-3 w-3" /> Suggest
                </button>
                <button
                  type="button"
                  onClick={onToggleAddControl}
                  className="flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                  title="Add control mapping"
                >
                  <Plus className="h-3 w-3" /> Add
                </button>
              </div>
            </div>

            {/* Existing controls */}
            {ob.controls.length > 0 && (
              <div className="space-y-1.5 mb-3">
                {ob.controls.map(c => (
                  <div key={c.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/30">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-gray-300">{c.control_name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">{c.control_type}</span>
                        {c.owner && <span className="text-[10px] text-gray-600">{c.owner}</span>}
                        {c.description && <span className="text-[10px] text-gray-600 truncate">{c.description}</span>}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onDeleteControl(c.id)}
                      className="text-gray-700 hover:text-red-400 transition-colors"
                      title="Remove control"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* AI suggestions */}
            {suggestions && suggestions.length > 0 && (
              <div className="mb-3">
                <p className="text-[10px] text-violet-400 font-medium mb-1.5">AI Suggestions:</p>
                <div className="space-y-1">
                  {suggestions.map((s, i) => (
                    <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-violet-950/20 border border-violet-500/10">
                      <Sparkles className="h-3 w-3 text-violet-400 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-gray-300">{s.control_name}</p>
                        <p className="text-[10px] text-gray-500">{s.description}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onApplySuggestion(s)}
                        className="text-[10px] text-violet-400 hover:text-violet-300 font-medium"
                        title="Apply this suggestion"
                      >
                        Apply
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Add control form */}
            {addingControl && (
              <div className="rounded-lg border border-blue-500/20 bg-blue-950/10 p-3 space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="text"
                    placeholder="Control name"
                    value={controlForm.control_name}
                    onChange={e => onControlFormChange({ ...controlForm, control_name: e.target.value })}
                    className="rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-200 px-3 py-1.5 focus:border-blue-500 focus:outline-none"
                  />
                  <select
                    value={controlForm.control_type}
                    onChange={e => onControlFormChange({ ...controlForm, control_type: e.target.value })}
                    className="rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-200 px-3 py-1.5 focus:border-blue-500 focus:outline-none"
                    title="Select control type"
                  >
                    {CONTROL_TYPES.map(t => (
                      <option key={t} value={t}>{t.replace(/-/g, ' ')}</option>
                    ))}
                  </select>
                </div>
                <input
                  type="text"
                  placeholder="Description"
                  value={controlForm.description}
                  onChange={e => onControlFormChange({ ...controlForm, description: e.target.value })}
                  className="w-full rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-200 px-3 py-1.5 focus:border-blue-500 focus:outline-none"
                />
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Owner"
                    value={controlForm.owner}
                    onChange={e => onControlFormChange({ ...controlForm, owner: e.target.value })}
                    className="flex-1 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-200 px-3 py-1.5 focus:border-blue-500 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={onAddControl}
                    className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white font-medium transition-colors"
                  >
                    Add
                  </button>
                  <button
                    type="button"
                    onClick={onToggleAddControl}
                    className="px-3 py-1.5 rounded-lg bg-gray-800 text-xs text-gray-400 hover:text-white transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══ Stats Panel ════════════════════════════════════════════════ */

function StatsPanel({ stats }: { stats: ObligationStats }) {
  const topJurisdictions = Object.entries(stats.jurisdictions)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const topFreqs = Object.entries(stats.by_audit_frequency)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
        <Info className="h-4 w-4 text-blue-400" />
        Register Insights
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg bg-gray-800/40 px-3 py-2 text-center">
          <div className="text-lg font-bold text-blue-400">{stats.mandatory_count}</div>
          <div className="text-[10px] text-gray-500">Mandatory</div>
        </div>
        <div className="rounded-lg bg-gray-800/40 px-3 py-2 text-center">
          <div className="text-lg font-bold text-gray-400">{stats.optional_count}</div>
          <div className="text-[10px] text-gray-500">Optional</div>
        </div>
        <div className="rounded-lg bg-gray-800/40 px-3 py-2 text-center">
          <div className="text-lg font-bold text-emerald-400">{stats.with_effective_date}</div>
          <div className="text-[10px] text-gray-500">With Dates</div>
        </div>
        <div className="rounded-lg bg-gray-800/40 px-3 py-2 text-center">
          <div className="text-lg font-bold text-violet-400">{Object.keys(stats.jurisdictions).length}</div>
          <div className="text-[10px] text-gray-500">Jurisdictions</div>
        </div>
      </div>

      {(topJurisdictions.length > 0 || topFreqs.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
          {topJurisdictions.length > 0 && (
            <div>
              <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                <MapPin className="h-3 w-3 inline mr-1" />Jurisdictions
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {topJurisdictions.map(([j, c]) => (
                  <span key={j} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                    {j} <span className="opacity-60">({c})</span>
                  </span>
                ))}
              </div>
            </div>
          )}
          {topFreqs.length > 0 && (
            <div>
              <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                <Calendar className="h-3 w-3 inline mr-1" />Audit Frequency
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {topFreqs.map(([f, c]) => (
                  <span key={f} className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 text-gray-400">
                    {f} <span className="opacity-60">({c})</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ═══ Obligation Detail Panel ════════════════════════════════════ */

function ObligationDetailPanel({ detail }: { detail: ObligationDetail }) {
  const hasDescription = !!detail.description;
  const srcRef = detail.source_reference;
  const hasSrcRef = srcRef && typeof srcRef === 'object' && (srcRef.source_text || srcRef.section_id);
  const conditions = Array.isArray(detail.conditions) ? detail.conditions : [];
  const consequences = Array.isArray(detail.consequences) ? detail.consequences : [];
  const exceptions = Array.isArray(detail.exceptions) ? detail.exceptions : [];
  const scope = detail.applicability_scope;
  const hasScope = scope && typeof scope === 'object' && (
    (scope.loan_types?.length ?? 0) > 0 || (scope.occupancy_types?.length ?? 0) > 0 || (scope.transaction_types?.length ?? 0) > 0
  );

  if (!hasDescription && !hasSrcRef && conditions.length === 0 && consequences.length === 0
    && exceptions.length === 0 && !hasScope && !detail.enforcement_action && !detail.audit_frequency) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gray-800/60 bg-gray-800/20 p-4 space-y-3 mt-3">
      {/* Description */}
      {hasDescription && (
        <div>
          <h5 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1 flex items-center gap-1">
            <BookOpen className="h-3 w-3" /> Description
          </h5>
          <p className="text-xs text-gray-300 leading-relaxed">{detail.description}</p>
        </div>
      )}

      {/* Conditions / Consequences / Exceptions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {conditions.length > 0 && (
          <div>
            <h5 className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider mb-1 flex items-center gap-1">
              <Scale className="h-3 w-3" /> Conditions
            </h5>
            <ul className="space-y-0.5">
              {conditions.map((c, i) => (
                <li key={i} className="text-[10px] text-gray-400 pl-2 border-l border-blue-500/30">{c}</li>
              ))}
            </ul>
          </div>
        )}
        {consequences.length > 0 && (
          <div>
            <h5 className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider mb-1 flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> Consequences
            </h5>
            <ul className="space-y-0.5">
              {consequences.map((c, i) => (
                <li key={i} className="text-[10px] text-gray-400 pl-2 border-l border-amber-500/30">{c}</li>
              ))}
            </ul>
          </div>
        )}
        {exceptions.length > 0 && (
          <div>
            <h5 className="text-[10px] font-semibold text-violet-400 uppercase tracking-wider mb-1 flex items-center gap-1">
              <Info className="h-3 w-3" /> Exceptions
            </h5>
            <ul className="space-y-0.5">
              {exceptions.map((c, i) => (
                <li key={i} className="text-[10px] text-gray-400 pl-2 border-l border-violet-500/30">{c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Applicability Scope */}
      {hasScope && scope && typeof scope === 'object' && (
        <div>
          <h5 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Applicability Scope</h5>
          <div className="flex flex-wrap gap-1.5">
            {scope.loan_types?.map(t => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{t}</span>
            ))}
            {scope.occupancy_types?.map(t => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">{t}</span>
            ))}
            {scope.transaction_types?.map(t => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* Enforcement & Audit */}
      {(detail.enforcement_action || detail.audit_frequency) && (
        <div className="flex gap-4">
          {detail.enforcement_action && (
            <div>
              <h5 className="text-[10px] font-semibold text-red-400 uppercase tracking-wider mb-0.5">Enforcement</h5>
              <p className="text-[10px] text-gray-400">{detail.enforcement_action}</p>
            </div>
          )}
          {detail.audit_frequency && (
            <div>
              <h5 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-0.5">Audit Frequency</h5>
              <p className="text-[10px] text-gray-400">{detail.audit_frequency}</p>
            </div>
          )}
        </div>
      )}

      {/* Source Reference */}
      {hasSrcRef && srcRef && typeof srcRef === 'object' && (
        <div className="rounded-lg bg-gray-900/50 border border-gray-800 p-3">
          <h5 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1 flex items-center gap-1">
            <FileText className="h-3 w-3" /> Source Reference
          </h5>
          {srcRef.section_id && (
            <p className="text-[10px] text-gray-500 mb-1">Section: <span className="text-gray-400">{srcRef.section_id}</span></p>
          )}
          {srcRef.source_text && (
            <p className="text-[10px] text-gray-400 leading-relaxed italic border-l-2 border-gray-700 pl-2">
              &ldquo;{srcRef.source_text}&rdquo;
            </p>
          )}
          {srcRef.chunk_path && (
            <p className="text-[10px] text-gray-600 mt-1 truncate">Source: {srcRef.chunk_path}</p>
          )}
        </div>
      )}
    </div>
  );
}
