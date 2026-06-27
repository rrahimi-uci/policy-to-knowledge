import { useEffect, useState, useMemo } from 'react';
import { apiUrl } from '@/config';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3,
  Network,
  Shield,
  AlertTriangle,
  ArrowRight,
  Loader2,
  TrendingUp,
  GitBranch,
  Target,
} from 'lucide-react';

/* ─── types ──────────────────────────────────────────────────── */

interface GraphSummary {
  name: string;
  provider: string;
  rules: number;
  entities: number;
  has_optimized: boolean;
}

interface Rule {
  rule_id: string;
  rule_name: string;
  rule_type: string;
  confidence_score: number;
  risk_level: string;
  mandatory: boolean;
  entity_type: string;
  entity_or_relationship: string;
  dependencies: Array<{ depends_on_rule: string; dependency_type: string; strength?: number }>;
  dependent_rules: Array<{ dependent_rule: string; dependency_type: string }>;
}

interface OptimizedGraph {
  metadata: {
    original_rule_count: number;
    optimized_rule_count: number;
    rules_removed_count: number;
    dependencies_added_count: number;
  };
  business_rules: Rule[];
  dependency_details: {
    dependencies: Array<{ source_rule_id: string; target_rule_id: string; dependency_type: string; strength?: number }>;
    conflicts: Array<{ rule_1?: string; rule_2?: string; description?: string; [key: string]: unknown }>;
  };
  entity_types: Record<string, unknown>;
  relationships: Record<string, unknown>;
}

/* ─── chart colors ───────────────────────────────────────────── */

const TYPE_COLORS: Record<string, string> = {
  constraint: '#6366f1',
  process: '#8b5cf6',
  eligibility: '#06b6d4',
  validation: '#14b8a6',
  documentation: '#f59e0b',
  prohibition: '#ef4444',
  calculation: '#3b82f6',
  exception: '#f97316',
  compliance: '#22c55e',
  definition: '#64748b',
};

const RISK_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#f59e0b',
  low: '#22c55e',
};

const DEP_COLORS: Record<string, string> = {
  prerequisite: '#6366f1',
  complementary: '#8b5cf6',
  sequential: '#06b6d4',
  conditional: '#f59e0b',
  override: '#ef4444',
  validation: '#14b8a6',
  contradictory: '#f43f5e',
};

function getColor(map: Record<string, string>, key: string): string {
  return map[key.toLowerCase()] ?? '#64748b';
}

/* ─── page ───────────────────────────────────────────────────── */

export default function Analytics() {
  const navigate = useNavigate();
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<OptimizedGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  /* Fetch graph list */
  useEffect(() => {
    const ac = new AbortController();
    fetch(apiUrl('kg/graphs'), { signal: ac.signal })
      .then((r) => r.json())
      .then((d) => {
        const g: GraphSummary[] = d.graphs ?? [];
        setGraphs(g);
        const optimized = g.filter((x) => x.has_optimized);
        if (optimized.length > 0) setSelectedGraph(optimized[0].name);
        setLoading(false);
      })
      .catch(() => setLoading(false));
    return () => ac.abort();
  }, []);

  /* Fetch full graph when selection changes */
  useEffect(() => {
    if (!selectedGraph) return;
    const ac = new AbortController();
    setDetailLoading(true);
    const graph = graphs.find((g) => g.name === selectedGraph);
    const provider = graph?.provider ?? 'openai';
    fetch(apiUrl(`kg/graphs/${selectedGraph}?provider=${provider}`), { signal: ac.signal })
      .then((r) => r.json())
      .then((d) => { setGraphData(d); setDetailLoading(false); })
      .catch(() => setDetailLoading(false));
    return () => ac.abort();
  }, [selectedGraph, graphs]);

  /* Derived analytics */
  const analytics = useMemo(() => {
    if (!graphData?.business_rules) return null;
    const rules = graphData.business_rules;
    const deps = graphData.dependency_details?.dependencies ?? [];
    const conflicts = graphData.dependency_details?.conflicts ?? [];

    // rule type distribution
    const typeCounts: Record<string, number> = {};
    rules.forEach((r) => {
      const t = (r.rule_type ?? 'unknown').toLowerCase();
      typeCounts[t] = (typeCounts[t] ?? 0) + 1;
    });

    // risk level distribution
    const riskCounts: Record<string, number> = {};
    rules.forEach((r) => {
      const rl = (r.risk_level ?? 'unknown').toLowerCase();
      riskCounts[rl] = (riskCounts[rl] ?? 0) + 1;
    });

    // dependency type distribution
    const depTypeCounts: Record<string, number> = {};
    deps.forEach((d) => {
      const dt = (d.dependency_type ?? 'unknown').toLowerCase();
      depTypeCounts[dt] = (depTypeCounts[dt] ?? 0) + 1;
    });

    // confidence histogram (buckets of 5)
    const confBuckets: Record<string, number> = {};
    rules.forEach((r) => {
      const score = r.confidence_score ?? 0;
      const bucket = Math.floor(score / 5) * 5;
      const label = `${bucket}-${bucket + 5}`;
      confBuckets[label] = (confBuckets[label] ?? 0) + 1;
    });

    // entity coverage — use the actual entity/relationship name, not the generic classifier
    const entityCoverage: Record<string, number> = {};
    rules.forEach((r) => {
      const et = r.entity_or_relationship || r.entity_type || 'Unknown';
      entityCoverage[et] = (entityCoverage[et] ?? 0) + 1;
    });

    // connectivity: rules with most dependencies
    const connectivity: Array<{ name: string; deps: number }> = rules
      .map((r) => ({
        name: r.rule_name ?? r.rule_id,
        deps: (r.dependencies?.length ?? 0) + (r.dependent_rules?.length ?? 0),
      }))
      .sort((a, b) => b.deps - a.deps)
      .slice(0, 10);

    const scores = rules.map((r) => r.confidence_score ?? 0).filter((s) => s != null);
    const avgConf = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;

    return {
      totalRules: rules.length,
      totalDeps: deps.length,
      totalConflicts: conflicts.length,
      totalEntities: Object.keys(graphData.entity_types ?? {}).length,
      totalRelationships: Object.keys(graphData.relationships ?? {}).length,
      avgConfidence: avgConf,
      minConfidence: scores.length > 0 ? Math.min(...scores) : 0,
      maxConfidence: scores.length > 0 ? Math.max(...scores) : 0,
      optimized: graphData.metadata,
      typeCounts,
      riskCounts,
      depTypeCounts,
      confBuckets,
      entityCoverage,
      connectivity,
      conflicts,
    };
  }, [graphData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
      </div>
    );
  }

  const optimizedGraphs = graphs.filter((g) => g.has_optimized);

  if (optimizedGraphs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-center">
        <BarChart3 className="w-12 h-12 text-gray-700 mb-4" />
        <h2 className="text-lg font-semibold text-gray-300 mb-2">No Analytics Available</h2>
        <p className="text-sm text-gray-500 mb-4 max-w-md">
          Run the extraction pipeline with optimization enabled to generate analytics data.
        </p>
        <button
          type="button"
          onClick={() => navigate('/extraction/pipeline')}
          className="text-sm text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
        >
          Go to Pipeline <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="page-enter max-w-7xl mx-auto space-y-6">
      {/* Header + graph selector */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Graph Analytics</h1>
          <p className="text-sm text-gray-500 mt-1">
            Rule distributions, dependency density, and knowledge graph health
          </p>
        </div>
        <select
          aria-label="Select knowledge graph"
          value={selectedGraph ?? ''}
          onChange={(e) => setSelectedGraph(e.target.value)}
          className="appearance-none bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 cursor-pointer"
        >
          {optimizedGraphs.map((g) => (
            <option key={g.name} value={g.name}>
              {g.name.replace(/_/g, ' ')} ({g.provider})
            </option>
          ))}
        </select>
      </div>

      {detailLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : analytics ? (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <MiniStat icon={Network} label="Business Rules" value={analytics.totalRules} color="text-indigo-400" />
            <MiniStat icon={GitBranch} label="Dependencies" value={analytics.totalDeps} color="text-cyan-400" />
            <MiniStat icon={AlertTriangle} label="Conflicts" value={analytics.totalConflicts} color="text-rose-400" />
            <MiniStat icon={Target} label="Avg Confidence" value={`${analytics.avgConfidence.toFixed(1)}%`} color="text-emerald-400" />
            <MiniStat icon={Shield} label="Entity Types" value={analytics.totalEntities} color="text-violet-400" />
          </div>

          {/* Optimization summary */}
          {analytics.optimized && (
            <div className="rounded-xl border border-gray-800 bg-gray-900/60 px-5 py-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-gray-200">Optimization Summary</h3>
              </div>
              <div className="flex gap-6 text-xs text-gray-400">
                <span>Original: <strong className="text-gray-200">{analytics.optimized.original_rule_count}</strong> rules</span>
                <span>Optimized: <strong className="text-emerald-400">{analytics.optimized.optimized_rule_count}</strong> rules</span>
                <span>Removed: <strong className="text-rose-400">{analytics.optimized.rules_removed_count}</strong> duplicates</span>
                <span>Dependencies added: <strong className="text-cyan-400">{analytics.optimized.dependencies_added_count}</strong></span>
              </div>
            </div>
          )}

          {/* Charts row 1 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <DonutChart
              title="Rule Type Distribution"
              data={analytics.typeCounts}
              colorMap={TYPE_COLORS}
            />
            <HBarChart
              title="Risk Level Breakdown"
              data={analytics.riskCounts}
              colorMap={RISK_COLORS}
              total={analytics.totalRules}
            />
          </div>

          {/* Charts row 2 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <HBarChart
              title="Dependency Types"
              data={analytics.depTypeCounts}
              colorMap={DEP_COLORS}
              total={analytics.totalDeps}
            />
            <HistogramChart
              title="Confidence Score Distribution"
              data={analytics.confBuckets}
            />
          </div>

          {/* Charts row 3 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <BarChartV
              title="Entity Coverage (rules per entity / relationship)"
              data={analytics.entityCoverage}
            />
            <ConnectivityList
              title="Most Connected Rules"
              items={analytics.connectivity}
            />
          </div>

          {/* Conflicts */}
          {analytics.conflicts.length > 0 && (
            <div className="rounded-xl border border-rose-800/40 bg-rose-950/20 p-5">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-rose-400" />
                <h3 className="text-sm font-semibold text-rose-300">
                  Contradiction Hotspots ({analytics.conflicts.length})
                </h3>
              </div>
              <div className="space-y-2">
                {analytics.conflicts.slice(0, 10).map((c, i) => (
                  <div key={i} className="flex gap-3 text-xs text-gray-300">
                    <span className="text-rose-400 font-mono shrink-0">{c.rule_1}</span>
                    <span className="text-gray-600">↔</span>
                    <span className="text-rose-400 font-mono shrink-0">{c.rule_2}</span>
                    <span className="text-gray-500 truncate">{c.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

/* ═══ Chart Components (SVG-based, no external deps) ════════════ */

function MiniStat({
  icon: Icon, label, value, color,
}: {
  icon: typeof Network; label: string; value: string | number; color: string;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
      <Icon className={`w-4 h-4 ${color} mb-2`} />
      <div className="text-xl font-bold text-gray-100">{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  );
}

function DonutChart({
  title,
  data,
  colorMap,
}: {
  title: string;
  data: Record<string, number>;
  colorMap: Record<string, string>;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (total === 0) return null;

  const size = 160;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = 70;
  const innerR = 45;

  let cumAngle = -Math.PI / 2;
  const arcs = entries.map(([key, val]) => {
    const angle = (val / total) * Math.PI * 2;
    const startAngle = cumAngle;
    const endAngle = cumAngle + angle;
    cumAngle = endAngle;

    const largeArc = angle > Math.PI ? 1 : 0;
    const x1 = cx + outerR * Math.cos(startAngle);
    const y1 = cy + outerR * Math.sin(startAngle);
    const x2 = cx + outerR * Math.cos(endAngle);
    const y2 = cy + outerR * Math.sin(endAngle);
    const x3 = cx + innerR * Math.cos(endAngle);
    const y3 = cy + innerR * Math.sin(endAngle);
    const x4 = cx + innerR * Math.cos(startAngle);
    const y4 = cy + innerR * Math.sin(startAngle);

    const d = [
      `M ${x1} ${y1}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
      `L ${x3} ${y3}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4}`,
      'Z',
    ].join(' ');

    return { key, val, d, color: getColor(colorMap, key) };
  });

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <div className="flex items-center gap-6">
        <svg viewBox={`0 0 ${size} ${size}`} className="w-40 h-40 shrink-0">
          {arcs.map((a) => (
            <path key={a.key} d={a.d} fill={a.color} opacity={0.85}>
              <title>{`${a.key}: ${a.val} (${((a.val / total) * 100).toFixed(1)}%)`}</title>
            </path>
          ))}
          <text x={cx} y={cy - 6} textAnchor="middle" className="fill-gray-200 text-lg font-bold" fontSize="18">
            {total}
          </text>
          <text x={cx} y={cy + 12} textAnchor="middle" className="fill-gray-500" fontSize="10">
            total
          </text>
        </svg>
        <div className="flex flex-col gap-1.5 flex-1 min-w-0">
          {entries.map(([key, val]) => (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ background: getColor(colorMap, key) }}
              />
              <span className="text-gray-400 capitalize truncate flex-1">{key}</span>
              <span className="text-gray-300 font-medium tabular-nums">{val}</span>
              <span className="text-gray-600 tabular-nums w-10 text-right">
                {((val / total) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function HBarChart({
  title,
  data,
  colorMap,
  total,
}: {
  title: string;
  data: Record<string, number>;
  colorMap: Record<string, string>;
  total: number;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const maxVal = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <div className="space-y-3">
        {entries.map(([key, val]) => (
          <div key={key}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-gray-400 capitalize">{key}</span>
              <span className="text-gray-300 tabular-nums">
                {val} <span className="text-gray-600">({((val / total) * 100).toFixed(0)}%)</span>
              </span>
            </div>
            <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${(val / maxVal) * 100}%`,
                  backgroundColor: getColor(colorMap, key),
                  opacity: 0.8,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HistogramChart({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data).sort((a, b) => {
    const aNum = parseInt(a[0]);
    const bNum = parseInt(b[0]);
    return aNum - bNum;
  });
  const maxVal = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <div className="h-40 flex items-end gap-1">
        {entries.map(([key, val]) => (
          <div
            key={key}
            className="flex flex-col items-center justify-end flex-1"
            style={{ height: '100%' }}
          >
            <span className="text-[10px] text-gray-400 mb-1 tabular-nums">{val}</span>
            <div
              className="w-full rounded-t transition-all duration-500"
              style={{
                height: `${(val / maxVal) * 100}%`,
                minHeight: val > 0 ? '4px' : '0',
                background: `linear-gradient(to top, #6366f1, #818cf8)`,
                opacity: 0.8,
              }}
            >
              <title>{`${key}: ${val} rules`}</title>
            </div>
            <span className="text-[9px] text-gray-600 mt-1 tabular-nums">{key}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BarChartV({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]).slice(0, 12);
  const maxVal = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <div className="space-y-2">
        {entries.map(([key, val]) => (
          <div key={key}>
            <div className="flex items-center justify-between text-xs mb-0.5">
              <span className="text-gray-400 truncate max-w-[60%]" title={key}>
                {key.replace(/_/g, ' ')}
              </span>
              <span className="text-gray-300 tabular-nums">{val}</span>
            </div>
            <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${(val / maxVal) * 100}%`,
                  background: 'linear-gradient(to right, #06b6d4, #8b5cf6)',
                  opacity: 0.7,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConnectivityList({
  title,
  items,
}: {
  title: string;
  items: Array<{ name: string; deps: number }>;
}) {
  const maxDeps = Math.max(...items.map((i) => i.deps), 1);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-3">
            <span className="text-xs text-gray-600 tabular-nums w-5 text-right">{i + 1}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs text-gray-300 truncate max-w-[70%]" title={item.name}>
                  {item.name}
                </span>
                <span className="text-xs text-gray-500 tabular-nums">{item.deps} connections</span>
              </div>
              <div className="h-1 rounded-full bg-gray-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${(item.deps / maxDeps) * 100}%`,
                    background: 'linear-gradient(to right, #22c55e, #06b6d4)',
                    opacity: 0.7,
                  }}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
