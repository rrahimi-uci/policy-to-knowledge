import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import { apiUrl, wsUrl } from '@/config';
import {
  GitCompareArrows, Loader2, CheckCircle2, XCircle,
  ChevronDown, ChevronUp, Play, RefreshCw, Zap,
  AlertTriangle, GitMerge, ArrowRight, Network,
  FileText, Shield, TrendingUp, Square, Clock,
} from 'lucide-react';

/* ─── Types ──────────────────────────────────────────────────── */

interface GraphSummary {
  name: string;
  provider: string;
  rules: number;
  entities: number;
  has_optimized: boolean;
  /** Domain assigned to the source folder on the Documents page (e.g. 'mortgage'). */
  domain?: string | null;
}

interface ComparisonSummary {
  name: string;
  g1: string;
  g2: string;
  provider: string;
  contradictions_count?: number;
  intersection_count?: number;
  g1_minus_g2_count?: number;
  g2_minus_g1_count?: number;
}

interface ComparisonRule {
  rule_id: string;
  rule_name: string;
  rule_type: string;
  risk_level: string;
  confidence_score: number;
  mandatory: boolean;
  description?: string;
  provenance?: {
    operation: string;
    sources: string[];
    original_ids: Record<string, string>;
    reasoning?: string;
    confidence?: number;
    similarity_score?: number;
    match_type?: string;
    g1_rule?: { rule_id: string; rule_name: string; description?: string };
    g2_rule?: { rule_id: string; rule_name: string; description?: string };
  };
}

interface SemanticContradiction {
  contradiction_id: string;
  conflict_type: string;
  confidence: number;
  reasoning: string;
  g1_rule: { source: string; rule: { rule_id: string; rule_name: string; rule_type?: string; description?: string; conditions?: string; risk_level?: string } };
  g2_rule: { source: string; rule: { rule_id: string; rule_name: string; rule_type?: string; description?: string; conditions?: string; risk_level?: string } };
}

interface ComparisonData {
  intersection?:  { business_rules: ComparisonRule[]; metadata?: Record<string, unknown> };
  g1_minus_g2?:   { business_rules: ComparisonRule[]; metadata?: Record<string, unknown> };
  g2_minus_g1?:   { business_rules: ComparisonRule[]; metadata?: Record<string, unknown> };
  contradictions?: { contradictions: SemanticContradiction[]; metadata?: Record<string, unknown> };
  union?:          { business_rules: ComparisonRule[] };
}

interface StepState {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
}

/* ─── Constants ──────────────────────────────────────────────── */

const COMPARE_STEPS = [
  { id: '7',  label: 'Rule Clustering',   desc: 'Grouping by behaviour type' },
  { id: '8',  label: 'Semantic Matching', desc: 'LLM compares rule pairs' },
  { id: '9',  label: 'Set Operations',    desc: 'Intersection · Diff · Contradictions' },
  { id: '10', label: 'Visualisations',    desc: 'Generating reports' },
];

const TYPE_COLORS: Record<string, string> = {
  constraint: '#6366f1', process: '#8b5cf6', eligibility: '#06b6d4',
  validation: '#14b8a6', documentation: '#f59e0b', prohibition: '#ef4444',
  calculation: '#3b82f6', exception: '#f97316', compliance: '#22c55e', definition: '#64748b',
};

const RISK_BADGE: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high:     'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium:   'bg-amber-500/20 text-amber-400 border-amber-500/30',
  low:      'bg-green-500/20 text-green-400 border-green-500/30',
};

const CONFLICT_TYPE_LABEL: Record<string, string> = {
  OPPOSITE:          'Opposite Requirements',
  INCOMPATIBLE:      'Incompatible Rules',
  MUTUALLY_EXCLUSIVE:'Mutually Exclusive',
  UNKNOWN:           'Conflicting Logic',
};

/* ─── Helpers ────────────────────────────────────────────────── */

function typeColor(t: string) { return TYPE_COLORS[(t ?? '').toLowerCase().trim()] ?? '#64748b'; }
function riskBadge(r: string) { return RISK_BADGE[(r ?? '').toLowerCase()] ?? 'bg-gray-700 text-gray-400 border-gray-700'; }
function pct(n: number, d: number) { return d > 0 ? Math.round((n / d) * 100) : 0; }
function displayName(n: string) { return n.replace(/_/g, ' '); }

const DOMAIN_LABELS: Record<string, string> = {
  mortgage: 'Mortgage',
  aml: 'Anti-Money Laundering',
  commercial: 'Commercial Lending',
  commercial_lending: 'Commercial Lending',
  healthcare: 'Healthcare',
  other: 'Other',
};

/** Fixed display order for the dropdown groups — mirrors the tabs on the
 *  Documents page so users see the same taxonomy in both places. */
const DOMAIN_ORDER: string[] = ['mortgage', 'aml', 'commercial_lending', 'healthcare'];

/** Keyword fallback aligned with pipeline graph_service._DOMAIN_KEYWORDS
 *  so any graph whose folder wasn't explicitly classified still lands in the
 *  same bucket as on the Documents page. */
function inferDomain(name: string): string {
  const l = (name || '').toLowerCase();
  if (
    l.includes('sample_guidelines') ||
    l.includes('example_policies') ||
    l.includes('mortgage') ||
    l.includes('loan') ||
    l.includes('underwriting') ||
    l.includes('servicing') ||
    l.includes('lend')
  ) return 'mortgage';
  if (l.includes('anti') && l.includes('money')) return 'aml';
  if (l.includes('aml')) return 'aml';
  if (l.includes('comercial') || l.includes('commercial') || l.includes('lending')) return 'commercial_lending';
  if (l.includes('health') || l.includes('hipaa')) return 'healthcare';
  return 'other';
}

/** Resolve domain for a graph: trust the backend-assigned domain (which
 *  mirrors the Documents page categorization) and only fall back to keyword
 *  inference when the source folder hasn't been explicitly classified. */
function graphDomainFor(g: { name: string; domain?: string | null }): string {
  return (g.domain && String(g.domain).trim()) || inferDomain(g.name);
}

/* ─── Comparison Summary Bar ─────────────────────────────────── */

interface SummaryBarProps {
  aName: string; bName: string;
  aOnly: number; common: number; bOnly: number; conflicts: number;
}

function SummaryBar({ aName, bName, aOnly, common, bOnly, conflicts }: SummaryBarProps) {
  const total = aOnly + common + bOnly || 1;
  const aPct  = pct(aOnly, total);
  const cPct  = pct(common, total);
  const bPct  = pct(bOnly, total);
  const overlapTotal = aOnly + common + bOnly;
  const overlapPct = pct(common, overlapTotal);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      {/* graph names */}
      <div className="flex justify-between text-sm font-semibold mb-3">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-indigo-500" />
          <span className="text-indigo-300">{displayName(aName)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-violet-300">{displayName(bName)}</span>
          <span className="w-3 h-3 rounded-full bg-violet-500" />
        </div>
      </div>

      {/* proportional bar */}
      <div className="flex h-10 rounded-lg overflow-hidden mb-3 border border-gray-800">
        {aPct > 0 && (
          <div className="flex items-center justify-center bg-indigo-500/25 border-r border-indigo-500/30 text-indigo-300 text-xs font-bold transition-all"
               style={{ width: `${aPct}%` }}>
            {aOnly > 9 ? aOnly : ''}
          </div>
        )}
        {cPct > 0 && (
          <div className="flex items-center justify-center bg-cyan-500/30 text-cyan-300 text-xs font-bold transition-all"
               style={{ width: `${cPct}%` }}>
            {common > 9 ? common : ''}
          </div>
        )}
        {bPct > 0 && (
          <div className="flex items-center justify-center bg-violet-500/25 border-l border-violet-500/30 text-violet-300 text-xs font-bold transition-all"
               style={{ width: `${bPct}%` }}>
            {bOnly > 9 ? bOnly : ''}
          </div>
        )}
      </div>

      {/* legend */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-indigo-400">
          <span className="w-2 h-2 rounded-sm bg-indigo-500/40 border border-indigo-500/40" />
          {aOnly} only in A
        </div>
        <div className="flex items-center gap-1.5 text-cyan-400 font-semibold">
          <span className="w-2 h-2 rounded-sm bg-cyan-500/40 border border-cyan-500/40" />
          {common} shared · {overlapPct}% overlap
        </div>
        <div className="flex items-center gap-1.5 text-violet-400">
          {bOnly} only in B
          <span className="w-2 h-2 rounded-sm bg-violet-500/40 border border-violet-500/40" />
        </div>
      </div>

      {/* conflict badge */}
      {conflicts > 0 && (
        <div className="mt-3 flex items-center gap-2 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2">
          <AlertTriangle size={13} className="text-rose-400 flex-shrink-0" />
          <span className="text-xs text-rose-300 font-medium">
            {conflicts} semantic contradiction{conflicts !== 1 ? 's' : ''} detected — rules conflict across documents
          </span>
        </div>
      )}
    </div>
  );
}

/* ─── Metric Cards ───────────────────────────────────────────── */

interface MetricsProps {
  common: number; aOnly: number; bOnly: number; conflicts: number;
  aName: string; bName: string;
}

function Metrics({ common, aOnly, bOnly, conflicts, aName, bName }: MetricsProps) {
  const total = aOnly + common + bOnly;
  const hasConflicts = conflicts > 0;
  return (
    <div className="grid grid-cols-4 gap-3">
      {[
        { label: 'Common Rules',                       value: common,    sub: `${pct(common, total)}% overlap`,  color: 'text-cyan-400',   dot: '#22d3ee', Icon: GitMerge },
        { label: `Only in ${displayName(aName) || 'A'}`, value: aOnly,  sub: 'unique to A',                     color: 'text-indigo-400', dot: '#6366f1', Icon: FileText },
        { label: `Only in ${displayName(bName) || 'B'}`, value: bOnly,  sub: 'unique to B',                     color: 'text-violet-400', dot: '#8b5cf6', Icon: FileText },
        { label: 'Contradictions',                     value: conflicts, sub: hasConflicts ? 'need review' : 'none found', color: hasConflicts ? 'text-rose-400' : 'text-emerald-400', dot: hasConflicts ? '#f43f5e' : '#22c55e', Icon: hasConflicts ? AlertTriangle : CheckCircle2 },
      ].map(c => (
        <div key={c.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-start justify-between mb-2">
            <span className="w-2.5 h-2.5 rounded-full mt-1 flex-shrink-0" style={{ backgroundColor: c.dot }} />
            <c.Icon size={14} className={`${c.color} opacity-50`} />
          </div>
          <div className={`text-3xl font-bold tabular-nums ${c.color} mb-1`}>{c.value}</div>
          <div className="text-xs text-gray-400 font-medium leading-tight">{c.label}</div>
          <div className="text-[10px] text-gray-600 mt-0.5">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

/* ─── Contradiction Card ─────────────────────────────────────── */

function ContradictionCard({ item, aColor, bColor, index }: {
  item: SemanticContradiction; aColor: string; bColor: string; index: number;
}) {
  const [expanded, setExpanded] = useState(index < 3);
  const confPct = Math.round(item.confidence * 100);
  const label = CONFLICT_TYPE_LABEL[item.conflict_type] ?? item.conflict_type.replace(/_/g, ' ');

  return (
    <div className="border border-gray-800 rounded-xl overflow-hidden bg-gray-900/60">
      {/* card header */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-800/40 transition-colors text-left"
      >
        <div className="w-6 h-6 rounded-full bg-rose-500/15 border border-rose-500/25 flex items-center justify-center flex-shrink-0">
          <XCircle size={12} className="text-rose-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-rose-300">{label}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">
              {confPct}% confidence
            </span>
            <span className="text-[10px] text-gray-600 truncate hidden sm:block">
              {item.g1_rule.rule.rule_name.slice(0, 40)} ↔ {item.g2_rule.rule.rule_name.slice(0, 40)}
            </span>
          </div>
        </div>
        {/* confidence bar */}
        <div className="flex-shrink-0 flex items-center gap-2">
          <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden hidden sm:block">
            <div className="h-full bg-rose-500 rounded-full" style={{ width: `${confPct}%` }} />
          </div>
          {expanded ? <ChevronUp size={14} className="text-gray-500" /> : <ChevronDown size={14} className="text-gray-500" />}
        </div>
      </button>

      {/* expanded content */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-gray-800">
          {/* side-by-side rules */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { side: item.g1_rule, color: aColor, borderClass: 'border-indigo-500/25', bgClass: 'bg-indigo-500/5' },
              { side: item.g2_rule, color: bColor, borderClass: 'border-violet-500/25', bgClass: 'bg-violet-500/5' },
            ].map(({ side, borderClass, bgClass }) => (
              <div key={side.source} className={`${bgClass} border ${borderClass} rounded-lg p-3`}>
                <div className="flex items-center gap-1.5 mb-2">
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${borderClass} text-gray-300`}>
                    {displayName(side.source)}
                  </span>
                  {side.rule.rule_type && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: `${typeColor(side.rule.rule_type)}20`, color: typeColor(side.rule.rule_type) }}>
                      {side.rule.rule_type}
                    </span>
                  )}
                  {side.rule.risk_level && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${riskBadge(side.rule.risk_level)}`}>
                      {side.rule.risk_level}
                    </span>
                  )}
                </div>
                <div className="text-xs font-semibold text-gray-200 mb-1.5 leading-tight">
                  {side.rule.rule_name}
                </div>
                {side.rule.description && (
                  <div className="text-xs text-gray-500 leading-relaxed line-clamp-3">
                    {side.rule.description}
                  </div>
                )}
                {side.rule.conditions && (
                  <div className="mt-1.5 text-[10px] text-gray-600">
                    <span className="text-gray-500 font-medium">When: </span>{side.rule.conditions.slice(0, 100)}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* AI reasoning */}
          <div className="bg-amber-500/5 border border-amber-500/15 rounded-lg px-3 py-2.5">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Zap size={11} className="text-amber-400" />
              <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">AI Analysis</span>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed">{item.reasoning}</p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Collapsible Rule Section ───────────────────────────────── */

function RuleSection({
  title, subtitle, count, rules, colorClass, dotColor, defaultOpen = false, limit = 50,
}: {
  title: string; subtitle: string; count: number; rules: ComparisonRule[];
  colorClass: string; dotColor: string; defaultOpen?: boolean; limit?: number;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? rules : rules.slice(0, limit);

  if (count === 0) return null;

  return (
    <div className="border border-gray-800 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-5 py-4 bg-gray-900 hover:bg-gray-800/60 transition-colors text-left"
      >
        <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: dotColor }} />
        <div className="flex-1 min-w-0">
          <span className={`text-sm font-semibold ${colorClass}`}>{title}</span>
          <span className="ml-2 text-xs text-gray-500">{subtitle}</span>
        </div>
        <span className={`text-lg font-bold tabular-nums ${colorClass} mr-2`}>{count}</span>
        {open ? <ChevronUp size={15} className="text-gray-500 flex-shrink-0" /> : <ChevronDown size={15} className="text-gray-500 flex-shrink-0" />}
      </button>

      {open && (
        <div className="border-t border-gray-800">
          <table className="w-full">
            <thead className="bg-gray-900/80 border-b border-gray-800">
              <tr>
                <th className="px-5 py-2.5 text-left text-[10px] text-gray-600 font-semibold uppercase tracking-wider">Rule Name</th>
                {rules[0]?.provenance?.g1_rule && (
                  <>
                    <th className="px-4 py-2.5 text-left text-[10px] text-gray-600 font-semibold uppercase tracking-wider hidden lg:table-cell">Version A</th>
                    <th className="px-4 py-2.5 text-left text-[10px] text-gray-600 font-semibold uppercase tracking-wider hidden lg:table-cell">Version B</th>
                  </>
                )}
                <th className="px-4 py-2.5 text-left text-[10px] text-gray-600 font-semibold uppercase tracking-wider">Type</th>
                <th className="px-4 py-2.5 text-left text-[10px] text-gray-600 font-semibold uppercase tracking-wider">Risk</th>
                <th className="px-4 py-2.5 text-right text-[10px] text-gray-600 font-semibold uppercase tracking-wider">
                  {rules[0]?.provenance?.similarity_score != null ? 'Similarity' : 'Confidence'}
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => {
                const color   = typeColor(r.rule_type);
                const riskKey = (r.risk_level ?? '').toLowerCase();
                const simPct  = r.provenance?.similarity_score;
                const matchType = r.provenance?.match_type;
                return (
                  <tr key={r.rule_id ?? i} className="border-t border-gray-800/60 hover:bg-gray-800/20 transition-colors group">
                    <td className="px-5 py-3">
                      <div className="text-xs font-medium text-gray-300 leading-tight max-w-xs">{r.rule_name}</div>
                      {r.provenance?.reasoning && (
                        <div className="text-[10px] text-gray-600 mt-0.5 line-clamp-1 group-hover:text-gray-500 transition-colors">
                          {r.provenance.reasoning}
                        </div>
                      )}
                    </td>
                    {r.provenance?.g1_rule && (
                      <>
                        <td className="px-4 py-3 text-[11px] text-gray-500 max-w-[180px] hidden lg:table-cell">
                          <div className="truncate" title={r.provenance.g1_rule.rule_name}>{r.provenance.g1_rule.rule_name}</div>
                        </td>
                        <td className="px-4 py-3 text-[11px] text-gray-500 max-w-[180px] hidden lg:table-cell">
                          <div className="truncate" title={r.provenance?.g2_rule?.rule_name}>{r.provenance?.g2_rule?.rule_name ?? '—'}</div>
                        </td>
                      </>
                    )}
                    <td className="px-4 py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ backgroundColor: `${color}20`, color }}>
                        {r.rule_type ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] px-2 py-0.5 rounded-full border ${riskBadge(riskKey)}`}>
                        {r.risk_level ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {simPct != null ? (
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-14 h-1.5 bg-gray-800 rounded-full overflow-hidden hidden sm:block">
                            <div className="h-full bg-cyan-500 rounded-full" style={{ width: `${simPct}%` }} />
                          </div>
                          <span className="text-xs text-cyan-400 tabular-nums font-medium">{simPct}%</span>
                          {matchType && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-600 hidden xl:inline">
                              {matchType}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-gray-500 tabular-nums">
                          {r.confidence_score?.toFixed(0) ?? '—'}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rules.length > limit && !showAll && (
            <div className="px-5 py-3 border-t border-gray-800 bg-gray-900/60">
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
              >
                Show all {rules.length} rules <ArrowRight size={12} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Pipeline Progress ──────────────────────────────────────── */

function PipelineProgress({
  steps, graphA, graphB, startedAt, onCancel,
}: {
  steps: Record<string, StepState>;
  graphA: string; graphB: string;
  startedAt: number;
  onCancel?: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const completedCount = COMPARE_STEPS.filter(s => (steps[s.id] ?? { status: 'pending' }).status === 'completed').length;
  const pctDone = Math.round((completedCount / COMPARE_STEPS.length) * 100);
  const fmtTime = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;

  return (
    <div className="bg-gray-900 border border-blue-500/20 rounded-xl overflow-hidden">
      {/* overall progress bar */}
      <div className="h-1 bg-gray-800">
        <div className="h-full bg-blue-500 transition-all duration-700 ease-out" style={{ width: `${pctDone}%` }} />
      </div>

      <div className="p-5">
        {/* header row */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
              <GitCompareArrows size={20} className="text-blue-400" />
            </div>
            <div>
              <div className="text-sm font-semibold text-gray-200">Comparing Knowledge Graphs</div>
              <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                <span className="text-indigo-400">{displayName(graphA)}</span>
                <ArrowRight size={10} className="text-gray-600" />
                <span className="text-violet-400">{displayName(graphB)}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-gray-400 bg-gray-800 px-3 py-1.5 rounded-lg">
              <Clock size={12} />
              <span className="tabular-nums font-medium">{fmtTime}</span>
            </div>
            {onCancel && (
              <button type="button" onClick={onCancel}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/10 transition-colors">
                <Square size={11} /> Cancel
              </button>
            )}
          </div>
        </div>

        {/* horizontal pipeline steps */}
        <div className="flex items-start">
          {COMPARE_STEPS.map((s, i) => {
            const st = steps[s.id] ?? { status: 'pending' };
            const isDone    = st.status === 'completed';
            const isRunning = st.status === 'running';
            const isFailed  = st.status === 'failed';
            const borderClass = isDone ? 'border-emerald-500/40 bg-emerald-500/5'
              : isRunning ? 'border-blue-500/50 bg-blue-500/8 shadow-lg shadow-blue-500/10'
              : isFailed ? 'border-red-500/40 bg-red-500/5'
              : 'border-gray-800 bg-gray-800/20';
            return (
              <div key={s.id} className="flex items-start flex-1 min-w-0">
                <div className={`flex-1 rounded-xl border p-4 transition-all duration-500 ${borderClass}`}>
                  <div className="flex items-center gap-2 mb-2">
                    {isDone    && <CheckCircle2 size={14} className="text-emerald-400" />}
                    {isRunning && <Loader2 size={14} className="text-blue-400 animate-spin" />}
                    {isFailed  && <XCircle size={14} className="text-red-400" />}
                    {!isDone && !isRunning && !isFailed && (
                      <span className="w-3.5 h-3.5 rounded-full border-2 border-gray-700 flex-shrink-0" />
                    )}
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${
                      isDone ? 'text-emerald-400' : isRunning ? 'text-blue-400' : isFailed ? 'text-red-400' : 'text-gray-600'
                    }`}>Step {s.id}</span>
                  </div>
                  <div className={`text-xs font-semibold leading-tight ${
                    isDone ? 'text-gray-300' : isRunning ? 'text-gray-200' : 'text-gray-500'
                  }`}>{s.label}</div>
                  <div className="text-[10px] text-gray-600 mt-1 leading-snug">{s.desc}</div>
                  {isRunning && (
                    <div className="mt-2 h-1 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full w-2/3 bg-blue-500 rounded-full animate-pulse" />
                    </div>
                  )}
                </div>
                {i < COMPARE_STEPS.length - 1 && (
                  <div className="flex items-center justify-center self-center pt-4 px-1 flex-shrink-0">
                    <svg width="24" height="12" viewBox="0 0 24 12">
                      <line x1="0" y1="6" x2="16" y2="6"
                        className={isDone ? 'stroke-emerald-500' : 'stroke-gray-700'}
                        strokeWidth="2" strokeOpacity={isDone ? 0.7 : 0.4} />
                      <polygon points="16,2 24,6 16,10"
                        className={isDone ? 'fill-emerald-500' : 'fill-gray-700'}
                        fillOpacity={isDone ? 0.7 : 0.4} />
                    </svg>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* estimate hint */}
        <div className="mt-4 flex items-center justify-center gap-2 text-[11px] text-gray-600">
          <Zap size={10} className="text-blue-500" />
          <span>Typically completes in 1–3 minutes · Powered by LLM semantic analysis</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Graph Selector ─────────────────────────────────────────── */

interface SelectorProps {
  graphs: GraphSummary[]; value: string; onChange: (n: string) => void;
  label: string; accentColor: string; exclude: string; loading: boolean;
}

function GraphSelector({ graphs, value, onChange, label, accentColor, exclude, loading }: SelectorProps) {
  const available = graphs.filter(g => g.name !== exclude);
  // Group by domain (prefer the backend-provided value so a folder uploaded
  // under the Mortgage tab appears under Mortgage, not Other).
  const byDomain = available.reduce<Record<string, GraphSummary[]>>((acc, g) => {
    const d = graphDomainFor(g);
    (acc[d] ??= []).push(g);
    return acc;
  }, {});

  // Render every supported domain in a fixed order (mirrors the Documents
  // page tabs) so the user always sees the full taxonomy — even when a
  // domain has no graphs yet — followed by any "Other" bucket for graphs
  // whose folder hasn't been classified.
  const orderedDomains: string[] = [
    ...DOMAIN_ORDER,
    ...Object.keys(byDomain).filter(d => !DOMAIN_ORDER.includes(d)).sort(),
  ];

  const selected  = graphs.find(g => g.name === value);
  return (
    <div className="flex-1 min-w-0">
      <label className="block text-[10px] text-gray-500 mb-1.5 font-semibold uppercase tracking-widest">{label}</label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full pointer-events-none" style={{ backgroundColor: accentColor }} />
        <select
          title={`Select ${label}`}
          aria-label={`Select ${label}`}
          className="w-full bg-gray-800 border border-gray-700 rounded-xl pl-8 pr-10 py-3 text-sm text-gray-200
                     appearance-none cursor-pointer focus:outline-none focus:border-blue-500 transition-colors"
          value={value}
          onChange={e => onChange(e.target.value)}
        >
          <option value="">— Select knowledge graph —</option>
          {orderedDomains.map(domain => {
            const domGraphs = byDomain[domain] ?? [];
            const domLabel = DOMAIN_LABELS[domain] ?? domain;
            return (
              <optgroup key={domain} label={domLabel}>
                {domGraphs.length === 0 ? (
                  <option value="" disabled>— no graphs in {domLabel} —</option>
                ) : (
                  domGraphs.map(g => (
                    <option key={g.name} value={g.name}>{displayName(g.name)} ({g.rules} rules · {g.provider})</option>
                  ))
                )}
              </optgroup>
            );
          })}
        </select>
        <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
          {loading ? <Loader2 size={14} className="animate-spin text-gray-500" /> : <ChevronDown size={14} className="text-gray-500" />}
        </div>
      </div>
      {selected && (
        <div className="mt-1.5 grid grid-cols-3 gap-2">
          <div className="bg-gray-800/60 rounded-lg px-3 py-1.5 text-center">
            <div className="text-sm font-bold text-gray-200">{selected.rules}</div>
            <div className="text-[10px] text-gray-600">rules</div>
          </div>
          <div className="bg-gray-800/60 rounded-lg px-3 py-1.5 text-center">
            <div className="text-sm font-bold text-gray-200">{selected.entities}</div>
            <div className="text-[10px] text-gray-600">entities</div>
          </div>
          <div className="bg-gray-800/60 rounded-lg px-3 py-1.5 text-center">
            <div className="text-[10px] font-bold text-gray-400 truncate pt-1">{selected.provider}</div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Empty / CTA States ─────────────────────────────────────── */

function EmptyState({ bothSelected, bothLoaded, running, onRun, loadingCmp }:
  { bothSelected: boolean; bothLoaded: boolean; running: boolean; onRun: () => void; loadingCmp: boolean }) {

  if (!bothSelected) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 rounded-2xl bg-gray-800 border border-gray-700 flex items-center justify-center mb-4">
          <GitCompareArrows size={28} className="text-gray-600" />
        </div>
        <h2 className="text-base font-semibold text-gray-300 mb-2">Select two knowledge graphs to compare</h2>
        <p className="text-sm text-gray-600 max-w-sm">
          Choose a graph for A and B above. The comparison will reveal shared rules, unique provisions, and semantic contradictions between the two documents.
        </p>
        <div className="mt-6 grid grid-cols-3 gap-4 text-left max-w-md">
          {[
            { icon: GitMerge,     color: 'text-cyan-400',   bg: 'bg-cyan-500/10',   label: 'Common Rules',      desc: 'Rules that exist in both with similarity scores' },
            { icon: Network,      color: 'text-indigo-400', bg: 'bg-indigo-500/10', label: 'Unique Provisions',  desc: 'Rules exclusive to each document' },
            { icon: AlertTriangle,color: 'text-rose-400',   bg: 'bg-rose-500/10',   label: 'Contradictions',     desc: 'Conflicting rules with AI explanations' },
          ].map(item => (
            <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-xl p-3">
              <div className={`w-7 h-7 rounded-lg ${item.bg} flex items-center justify-center mb-2`}>
                <item.icon size={14} className={item.color} />
              </div>
              <div className="text-xs font-semibold text-gray-300 mb-0.5">{item.label}</div>
              <div className="text-[10px] text-gray-600 leading-snug">{item.desc}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (loadingCmp) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <Loader2 size={28} className="text-blue-400 animate-spin" />
        <p className="text-sm text-gray-500">Loading comparison results…</p>
      </div>
    );
  }

  if (bothLoaded && !running) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mb-4">
          <Zap size={28} className="text-blue-400" />
        </div>
        <h2 className="text-base font-semibold text-gray-300 mb-2">No comparison found for this pair</h2>
        <p className="text-sm text-gray-600 max-w-sm mb-6">
          Run the semantic comparison pipeline to find shared rules, unique provisions, and AI-detected contradictions between these two knowledge graphs.
        </p>
        <div className="mb-6 grid grid-cols-3 gap-3 text-left max-w-md text-xs text-gray-500">
          {COMPARE_STEPS.map(s => (
            <div key={s.id} className="flex items-start gap-2">
              <span className="w-4 h-4 rounded-full bg-gray-800 border border-gray-700 text-[9px] flex items-center justify-center text-gray-500 flex-shrink-0 mt-0.5">{s.id}</span>
              <div>
                <div className="text-gray-400 font-medium">{s.label}</div>
                <div className="text-gray-600 text-[10px]">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={onRun}
          className="flex items-center gap-2.5 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold rounded-xl transition-colors shadow-lg shadow-blue-500/20"
        >
          <Play size={15} />
          Run Semantic Comparison
        </button>
        <p className="mt-3 text-xs text-gray-600">Takes 1–3 minutes · Powered by LLM analysis</p>
      </div>
    );
  }

  return null;
}

/* ─── Main Page ──────────────────────────────────────────────── */

export default function GraphComparison() {
  const [graphs, setGraphs]         = useState<GraphSummary[]>([]);
  const [graphAName, setGraphAName] = useState('');
  const [graphBName, setGraphBName] = useState('');
  const [loadingA, setLoadingA]     = useState(false);
  const [loadingB, setLoadingB]     = useState(false);
  const [comparisons, setComparisons] = useState<ComparisonSummary[]>([]);
  const [comparisonData, setComparisonData] = useState<ComparisonData | null>(null);
  const [loadingCmp, setLoadingCmp] = useState(false);
  const [, setRunId]                = useState<string | null>(null);
  const [running, setRunning]       = useState(false);
  const [runStartedAt, setRunStartedAt] = useState(0);
  const [justFinished, setJustFinished] = useState(false);
  const [steps, setSteps]           = useState<Record<string, StepState>>({});
  const [graphALoaded, setGraphALoaded] = useState(false);
  const [graphBLoaded, setGraphBLoaded] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  // Mirror justFinished into a ref so the long-lived ws.onclose handler reads
  // the current value instead of the stale one captured when connectWs ran.
  const justFinishedRef = useRef(false);
  useEffect(() => { justFinishedRef.current = justFinished; }, [justFinished]);

  useEffect(() => {
    fetch(apiUrl('kg/graphs')).then(r => r.json()).then(d => setGraphs(d.graphs ?? [])).catch(() => {});
  }, []);

  const fetchComparisons = useCallback(() => {
    fetch(apiUrl('kg/compare?provider=openai')).then(r => r.json()).then(d => setComparisons(d.comparisons ?? [])).catch(() => {});
  }, []);
  useEffect(() => { fetchComparisons(); }, [fetchComparisons]);

  /* verify graph exists (we only need to know it's loadable, not the full data) */
  const verifyGraph = useCallback(async (name: string, provider: string, side: 'A' | 'B') => {
    const setLoading = side === 'A' ? setLoadingA : setLoadingB;
    const setLoaded  = side === 'A' ? setGraphALoaded : setGraphBLoaded;
    setLoading(true);
    setLoaded(false);
    try {
      const r = await fetch(apiUrl(`kg/graphs/${encodeURIComponent(name)}?provider=${encodeURIComponent(provider)}`));
      if (r.ok) setLoaded(true);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  const handleSelectA = useCallback((name: string) => {
    setGraphAName(name); setGraphALoaded(false); setComparisonData(null);
    // When domain changes, reset B to avoid cross-domain comparison
    if (name && graphBName) {
      const ga = graphs.find(x => x.name === name) ?? { name } as GraphSummary;
      const gb = graphs.find(x => x.name === graphBName) ?? { name: graphBName } as GraphSummary;
      if (graphDomainFor(ga) !== graphDomainFor(gb)) {
        setGraphBName(''); setGraphBLoaded(false);
      }
    }
    if (name) { const g = graphs.find(x => x.name === name); if (g) verifyGraph(name, g.provider, 'A'); }
  }, [graphs, graphBName, verifyGraph]);

  const handleSelectB = useCallback((name: string) => {
    setGraphBName(name); setGraphBLoaded(false); setComparisonData(null);
    if (name) { const g = graphs.find(x => x.name === name); if (g) verifyGraph(name, g.provider, 'B'); }
  }, [graphs, verifyGraph]);

  /* find existing comparison */
  const existingComparison = useMemo((): ComparisonSummary | null => {
    if (!graphAName || !graphBName) return null;
    return comparisons.find(c =>
      (c.g1 === graphAName && c.g2 === graphBName) || (c.g1 === graphBName && c.g2 === graphAName)
    ) ?? null;
  }, [comparisons, graphAName, graphBName]);

  /* auto-load comparison data */
  const loadComparisonData = useCallback(async (summary: ComparisonSummary) => {
    setLoadingCmp(true);
    setComparisonData(null);
    try {
      const r = await fetch(apiUrl(`kg/compare/${encodeURIComponent(summary.name)}/data?provider=${encodeURIComponent(summary.provider)}`));
      setComparisonData(await r.json());
    } catch { /* ignore */ } finally { setLoadingCmp(false); }
  }, []);

  useEffect(() => {
    if (existingComparison) loadComparisonData(existingComparison);
    else setComparisonData(null);
  }, [existingComparison, loadComparisonData]);

  /* WebSocket progress */
  const connectWs = useCallback((id: string) => {
    wsRef.current?.close();
    const init: Record<string, StepState> = {};
    COMPARE_STEPS.forEach(s => { init[s.id] = { status: 'pending' }; });
    setSteps(init);
    const ws = new WebSocket(wsUrl(`kg/pipeline/${id}`));
    wsRef.current = ws;
    ws.onmessage = evt => {
      try {
        const msg: { step: string; status: string } = JSON.parse(evt.data);
        if (msg.step === 'done' || msg.step === 'complete') {
          // Mark all steps completed for visual feedback
          setSteps(prev => {
            const next = { ...prev };
            COMPARE_STEPS.forEach(s => { next[s.id] = { status: 'completed' }; });
            return next;
          });
          // Brief "loading results" transition. Set the ref synchronously too,
          // so a server-initiated close arriving in the same tick (before the
          // state-sync effect flushes) still sees that we just finished.
          justFinishedRef.current = true;
          setJustFinished(true);
          setTimeout(() => {
            setRunning(false);
            setJustFinished(false);
          }, 1500);
          fetchComparisons();
          setTimeout(() => fetchComparisons(), 2000);
          return;
        }
        setSteps(prev => ({ ...prev, [msg.step]: { status: msg.status as StepState['status'] } }));
      } catch { /* ignore */ }
    };
    ws.onclose = () => {
      if (!justFinishedRef.current) setRunning(false);
      fetchComparisons();
    };
  }, [fetchComparisons]);

  useEffect(() => () => { wsRef.current?.close(); }, []);

  const runComparison = useCallback(async () => {
    if (!graphAName || !graphBName) return;
    const gA = graphs.find(g => g.name === graphAName);
    const provider = gA?.provider ?? 'openai';
    setRunning(true);
    setRunStartedAt(Date.now());
    setComparisonData(null);
    try {
      const r = await fetch(apiUrl('kg/compare'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ g1: graphAName, g2: graphBName, provider }),
      });
      const d = await r.json();
      setRunId(d.run_id);
      connectWs(d.run_id);
    } catch { setRunning(false); }
  }, [graphAName, graphBName, graphs, connectWs]);

  /* ── Derived data ── */
  const [sideA, sideB]: ['g1' | 'g2', 'g1' | 'g2'] = useMemo(() =>
    existingComparison?.g1 === graphAName ? ['g1', 'g2'] : ['g2', 'g1'],
    [existingComparison, graphAName],
  );

  const commonRules    = comparisonData?.intersection?.business_rules ?? [];
  const onlyARules     = (sideA === 'g1' ? comparisonData?.g1_minus_g2 : comparisonData?.g2_minus_g1)?.business_rules ?? [];
  const onlyBRules     = (sideB === 'g2' ? comparisonData?.g2_minus_g1 : comparisonData?.g1_minus_g2)?.business_rules ?? [];
  const contradictions = comparisonData?.contradictions?.contradictions ?? [];

  const hasSemantic  = comparisonData != null;
  const bothSelected = !!graphAName && !!graphBName;
  const bothLoaded   = graphALoaded && graphBLoaded;
  const showContent  = hasSemantic && !running;
  const showEmpty    = !showContent;

  const gA = graphs.find(g => g.name === graphAName);
  const gB = graphs.find(g => g.name === graphBName);

  return (
    <div className="min-h-screen bg-gray-950">

      {/* ── Sticky header ── */}
      <div className="sticky top-0 z-20 bg-gray-950/95 backdrop-blur border-b border-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center gap-3 mb-4">
            <GitCompareArrows size={18} className="text-blue-400 flex-shrink-0" />
            <h1 className="text-base font-bold text-white">Compare Knowledge Graphs</h1>

            {hasSemantic && !running && (
              <span className="flex items-center gap-1.5 text-[11px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full ml-1">
                <CheckCircle2 size={10} />
                Semantic results loaded
              </span>
            )}

            <div className="ml-auto flex items-center gap-2">
              {hasSemantic && !running && (
                <button type="button" onClick={runComparison}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 border border-gray-700 rounded-lg hover:bg-gray-800 transition-colors">
                  <RefreshCw size={11} />Re-run
                </button>
              )}
            </div>
          </div>

          <div className={`flex items-end gap-4 ${running ? 'opacity-50 pointer-events-none' : ''}`}>
            <GraphSelector graphs={graphs} value={graphAName} onChange={handleSelectA}
              label="Graph A" accentColor="#6366f1" exclude={graphBName} loading={loadingA} />
            <div className="pb-5 flex-shrink-0">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg border border-gray-700 bg-gray-800">
                <ArrowRight size={14} className="text-gray-500" />
              </div>
            </div>
            <GraphSelector graphs={graphAName ? graphs.filter(g => graphDomainFor(g) === graphDomainFor((graphs.find(x => x.name === graphAName) ?? { name: graphAName }) as GraphSummary)) : graphs} value={graphBName} onChange={handleSelectB}
              label="Graph B" accentColor="#8b5cf6" exclude={graphAName} loading={loadingB} />
          </div>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="px-6 py-6 max-w-7xl mx-auto space-y-5">

        {/* pipeline progress */}
        {running && (
          <PipelineProgress
            steps={steps}
            graphA={graphAName}
            graphB={graphBName}
            startedAt={runStartedAt}
            onCancel={() => {
              wsRef.current?.close();
              setRunning(false);
            }}
          />
        )}

        {/* transition: loading results after pipeline finishes */}
        {justFinished && !running && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
              <CheckCircle2 size={24} className="text-emerald-400" />
            </div>
            <p className="text-sm font-semibold text-emerald-400">Comparison complete!</p>
            <div className="flex items-center gap-2">
              <Loader2 size={14} className="text-gray-500 animate-spin" />
              <p className="text-xs text-gray-500">Loading results…</p>
            </div>
          </div>
        )}

        {/* overview — shown when results are loaded */}
        {showContent && (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              <div className="lg:col-span-3">
                <SummaryBar
                  aName={graphAName} bName={graphBName}
                  aOnly={onlyARules.length} common={commonRules.length}
                  bOnly={onlyBRules.length} conflicts={contradictions.length}
                />
              </div>
              <div className="lg:col-span-2">
                <Metrics
                  common={commonRules.length} aOnly={onlyARules.length}
                  bOnly={onlyBRules.length} conflicts={contradictions.length}
                  aName={graphAName} bName={graphBName}
                />
              </div>
            </div>

            {/* semantic badge */}
            <div className="flex items-center gap-2 text-xs text-blue-400 bg-blue-500/5 border border-blue-500/15 rounded-xl px-4 py-2.5">
              <Zap size={12} />
              <span>LLM-powered semantic comparison — results go beyond name-matching to detect conceptually equivalent and conflicting rules</span>
              <TrendingUp size={12} className="ml-auto text-blue-500" />
            </div>

            {/* contradictions section */}
            {contradictions.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <AlertTriangle size={15} className="text-rose-400" />
                  <h2 className="text-sm font-bold text-rose-300">
                    {contradictions.length} Contradiction{contradictions.length !== 1 ? 's' : ''} Requiring Review
                  </h2>
                  <span className="text-xs text-gray-600">— rules that conflict between the two documents</span>
                </div>
                <div className="space-y-2">
                  {contradictions.map((item, i) => (
                    <ContradictionCard key={item.contradiction_id ?? i} item={item} aColor="#6366f1" bColor="#8b5cf6" index={i} />
                  ))}
                </div>
              </div>
            )}

            {contradictions.length === 0 && (
              <div className="flex items-center gap-3 bg-emerald-500/5 border border-emerald-500/20 rounded-xl px-5 py-4">
                <CheckCircle2 size={18} className="text-emerald-400 flex-shrink-0" />
                <div>
                  <div className="text-sm font-semibold text-emerald-300">No contradictions detected</div>
                  <div className="text-xs text-gray-500 mt-0.5">The LLM analysis found no conflicting rules between these two knowledge graphs.</div>
                </div>
              </div>
            )}

            {/* common rules */}
            <RuleSection
              title="Common Rules"
              subtitle={`rules that appear semantically equivalent in both documents`}
              count={commonRules.length}
              rules={commonRules}
              colorClass="text-cyan-400"
              dotColor="#22d3ee"
              defaultOpen
            />

            {/* only A */}
            <RuleSection
              title={`Only in ${displayName(graphAName)}`}
              subtitle={`provisions not found in ${displayName(graphBName)}`}
              count={onlyARules.length}
              rules={onlyARules}
              colorClass="text-indigo-400"
              dotColor="#6366f1"
              defaultOpen={false}
            />

            {/* only B */}
            <RuleSection
              title={`Only in ${displayName(graphBName)}`}
              subtitle={`provisions not found in ${displayName(graphAName)}`}
              count={onlyBRules.length}
              rules={onlyBRules}
              colorClass="text-violet-400"
              dotColor="#8b5cf6"
              defaultOpen={false}
            />

            {/* document metadata */}
            {(gA || gB) && (
              <div className="grid grid-cols-2 gap-4">
                {[{ g: gA, name: graphAName, color: 'border-indigo-500/20 bg-indigo-500/5', label: 'Graph A', accentText: 'text-indigo-400' }, { g: gB, name: graphBName, color: 'border-violet-500/20 bg-violet-500/5', label: 'Graph B', accentText: 'text-violet-400' }].map(({ g, name, color, label, accentText }) => g && (
                  <div key={name} className={`border ${color} rounded-xl p-4`}>
                    <div className="flex items-center gap-2 mb-3">
                      <Shield size={13} className={accentText} />
                      <span className="text-xs font-semibold text-gray-400">{label}: {displayName(name)}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div><div className="text-lg font-bold text-gray-200">{g.rules}</div><div className="text-[10px] text-gray-600">rules</div></div>
                      <div><div className="text-lg font-bold text-gray-200">{g.entities}</div><div className="text-[10px] text-gray-600">entities</div></div>
                      <div><div className="text-xs font-medium text-gray-400 pt-1">{g.provider}</div><div className="text-[10px] text-gray-600">provider</div></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* empty / CTA state */}
        {showEmpty && !running && (
          <EmptyState
            bothSelected={bothSelected}
            bothLoaded={bothLoaded}
            running={running}
            onRun={runComparison}
            loadingCmp={loadingCmp}
          />
        )}
      </div>
    </div>
  );
}
