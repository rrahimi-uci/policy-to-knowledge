import { useEffect, useState, useRef } from 'react';
import { fetchGraphs, fetchRuns, deleteGraph } from '../api';
import { useEmbeddedNavigate } from '../hooks/useEmbeddedNavigate';
import {
  Network, FileText, Users, Play, CheckCircle, Loader2, XCircle,
  Clock, Upload, ArrowRight, BarChart3, Sparkles, Trash2,
} from 'lucide-react';

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

function timeAgo(dateStr?: string): string {
  if (!dateStr) return '';
  const sec = Math.round((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (sec < 60) return 'just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

const DOMAINS = [
  { value: 'mortgage',           label: 'Mortgage',           color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/30',   accent: 'border-l-blue-500',   pill: 'bg-blue-500/15 text-blue-400'   },
  { value: 'aml',                label: 'AML',                color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30',    accent: 'border-l-red-500',    pill: 'bg-red-500/15 text-red-400'    },
  { value: 'healthcare',         label: 'Healthcare',         color: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/30',  accent: 'border-l-green-500',  pill: 'bg-green-500/15 text-green-400'  },
  { value: 'commercial_lending', label: 'Commercial Lending', color: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/30', accent: 'border-l-purple-500', pill: 'bg-purple-500/15 text-purple-400' },
];

/** Map a graph's output folder name to a domain value. */
function graphDomain(name: string): string {
  const l = name.toLowerCase();
  // Mortgage: p2k-*, fannie mae, freddie mac, fnma, fhlmc
  if (l.startsWith('p2k') || l.includes('fannie') || l.includes('freddie') || l.includes('fnma') || l.includes('fhlmc')) return 'mortgage';
  // AML
  if (l.startsWith('aml') || l.includes('anti_money') || l.includes('anti-money')) return 'aml';
  // Healthcare: healthcare, cms (Centers for Medicare & Medicaid), hipaa, medicare, medicaid
  if (l.startsWith('healthcare') || l.startsWith('cms') || l.includes('hipaa') || l.includes('medicare') || l.includes('medicaid')) return 'healthcare';
  // Commercial Lending
  if (l.includes('lending') || l.includes('commercial') || l.includes('comercial')) return 'commercial_lending';
  return '';
}

export default function Dashboard() {
  const [graphs, setGraphs]   = useState<any[]>([]);
  const [runs, setRuns]       = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState<string>('all');
  const nav = useEmbeddedNavigate();
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const loadData = () =>
    Promise.all([
      fetchGraphs().catch(() => ({ graphs: [] })),
      fetchRuns().catch(()   => ({ runs: []   })),
    ]).then(([g, r]) => {
      setGraphs(g.graphs || []);
      setRuns(r.runs     || []);
    });

  useEffect(() => {
    setLoading(true);
    loadData().finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const hasRunning = runs.some((r: any) => r.status === 'running');
    if (hasRunning) pollRef.current = setInterval(loadData, 5000);
    return () => clearInterval(pollRef.current);
  }, [runs]);

  // Enrich every graph with its detected domain
  const enriched = graphs.map((g: any) => ({ ...g, domain: graphDomain(g.name) }));

  // Domain summary stats
  const domainStats = DOMAINS.map(d => {
    const gs = enriched.filter(g => g.domain === d.value);
    return {
      ...d,
      count:    gs.length,
      rules:    gs.reduce((s: number, g: any) => s + (g.rules    || 0), 0),
      entities: gs.reduce((s: number, g: any) => s + (g.entities || 0), 0),
    };
  });

  const unclassified    = enriched.filter(g => !g.domain);
  const totalRules      = enriched.reduce((s: number, g: any) => s + (g.rules    || 0), 0);
  const totalEntities   = enriched.reduce((s: number, g: any) => s + (g.entities || 0), 0);
  const completedRuns   = runs.filter((r: any) => r.status === 'completed').length;
  const runningRuns     = runs.filter((r: any) => r.status === 'running').length;

  // Filter pills — only domains that have graphs, plus "All"
  const activeDomains = DOMAINS.filter(d => enriched.some(g => g.domain === d.value));

  // KG cards shown in grid (filtered)
  const visibleGraphs = activeFilter === 'all'
    ? enriched
    : enriched.filter(g => g.domain === activeFilter || (!g.domain && activeFilter === 'unclassified'));

  const handleDeleteGraph = async (name: string, provider: string) => {
    if (!window.confirm(`Delete knowledge graph "${name}"? This cannot be undone.`)) return;
    await deleteGraph(name, provider).catch(() => {});
    setGraphs(prev => prev.filter(g => !(g.name === name && g.provider === provider)));
  };

  const domainFor = (d: string) => DOMAINS.find(x => x.value === d);

  const statusIcon = (s: string) => {
    if (s === 'completed') return <CheckCircle size={16} className="text-green-400" />;
    if (s === 'running')   return <Loader2     size={16} className="text-blue-400 animate-spin" />;
    if (s === 'failed')    return <XCircle     size={16} className="text-red-400" />;
    return <Clock size={16} className="text-gray-500" />;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-blue-400" size={32} />
      </div>
    );
  }

  const isEmpty = graphs.length === 0 && runs.length === 0;

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold">Dashboard</h2>

      {/* ── Onboarding CTA ─────────────────────────────────────── */}
      {isEmpty && (
        <div className="bg-gradient-to-br from-blue-500/10 via-purple-500/5 to-transparent border border-blue-500/20 rounded-2xl p-8">
          <h3 className="text-xl font-bold text-gray-100 mb-1 text-center">Welcome to Policy to Knowledge</h3>
          <p className="text-gray-400 text-sm text-center mb-8">
            Transform your compliance documents into structured, queryable knowledge graphs in three steps.
          </p>
          <div className="grid grid-cols-3 gap-6">
            {[
              { label: 'Upload Documents', sub: 'Add compliance files by domain', step: 'Step 1', color: 'blue', icon: Upload,   path: '/documents' },
              { label: 'Run Pipeline',     sub: 'Extract rules & entities',       step: 'Step 2', color: 'green', icon: Play,    path: '/pipeline'  },
              { label: 'Explore Graph',    sub: 'Query & visualize results',      step: 'Step 3', color: 'purple', icon: Network, path: '/explorer' },
            ].map(({ label, sub, step, color, icon: Icon, path }, i) => (
              <button
                key={label}
                type="button"
                onClick={() => nav(path)}
                className={`relative flex flex-col items-center text-center px-5 py-6 bg-gray-800/60 border border-gray-700/60 rounded-2xl hover:border-${color}-500/40 hover:bg-gray-800/80 transition-all group`}
              >
                <div className={`w-12 h-12 rounded-xl bg-${color}-500/15 flex items-center justify-center mb-4 group-hover:bg-${color}-500/25 transition-colors`}>
                  <Icon size={22} className={`text-${color}-400`} />
                </div>
                <span className={`text-xs font-semibold text-${color}-400 tracking-wider uppercase mb-1`}>{step}</span>
                <p className="text-sm font-semibold text-gray-100 mb-1">{label}</p>
                <p className="text-xs text-gray-500">{sub}</p>
                {i < 2 && <ArrowRight size={14} className="absolute top-1/2 -right-4 -translate-y-1/2 text-gray-600 hidden lg:block" />}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Global stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Knowledge Graphs', value: graphs.length,    icon: Network,   color: 'text-blue-400',   bg: 'bg-blue-500/10',   sub: `${activeDomains.length} domain${activeDomains.length !== 1 ? 's' : ''}` },
          { label: 'Total Rules',      value: totalRules,        icon: FileText,  color: 'text-green-400',  bg: 'bg-green-500/10',  sub: graphs.length > 0 ? `Across ${graphs.length} graph${graphs.length !== 1 ? 's' : ''}` : 'Run pipeline to extract' },
          { label: 'Total Entities',   value: totalEntities,     icon: Users,     color: 'text-purple-400', bg: 'bg-purple-500/10', sub: totalEntities > 0 ? `~${Math.round(totalRules / Math.max(totalEntities, 1))} rules / entity` : 'Run pipeline to extract' },
          { label: 'Pipeline Runs',    value: runs.length,       icon: BarChart3, color: 'text-amber-400',  bg: 'bg-amber-500/10',  sub: runningRuns > 0 ? `${runningRuns} running now` : completedRuns > 0 ? `${completedRuns} completed` : 'No runs yet' },
        ].map(({ label, value, icon: Icon, color, bg, sub }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs uppercase tracking-wider text-gray-500">{label}</span>
              <div className={`w-9 h-9 rounded-lg ${bg} flex items-center justify-center`}>
                <Icon size={18} className={color} />
              </div>
            </div>
            <p className="text-3xl font-bold text-gray-100">{value.toLocaleString()}</p>
            <p className="text-xs text-gray-500 mt-1">{sub}</p>
          </div>
        ))}
      </div>

      {/* ── Domain overview ────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500 mb-3">Domains</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {domainStats.map(d => (
            <div
              key={d.value}
              className={`rounded-xl border p-4 transition-colors ${
                d.count > 0
                  ? `bg-gray-900 ${d.border} cursor-pointer hover:bg-gray-800/60`
                  : 'bg-gray-900/50 border-gray-800/50'
              }`}
              onClick={() => d.count > 0 ? setActiveFilter(d.value) : undefined}
            >
              <div className="flex items-center gap-2 mb-3">
                <div className={`w-7 h-7 rounded-lg ${d.bg} flex items-center justify-center`}>
                  <Network size={14} className={d.count > 0 ? d.color : 'text-gray-700'} />
                </div>
                <span className={`text-sm font-semibold ${d.count > 0 ? 'text-gray-200' : 'text-gray-600'}`}>
                  {d.label}
                </span>
              </div>
              {d.count > 0 ? (
                <>
                  <p className={`text-2xl font-bold mb-1 ${d.color}`}>{d.count}</p>
                  <p className="text-xs text-gray-500">
                    {d.rules.toLocaleString()} rules · {d.entities.toLocaleString()} entities
                  </p>
                </>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-gray-700">No knowledge graphs yet</p>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); nav('/pipeline'); }}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors"
                  >
                    <Play size={10} /> Run pipeline
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Knowledge Graphs ───────────────────────────────────── */}
      {graphs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Knowledge Graphs</h3>
            <button
              type="button"
              onClick={() => nav('/explorer')}
              className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
            >
              Open Explorer
            </button>
          </div>

          {/* Filter pills */}
          <div className="flex flex-wrap gap-2 mb-4">
            <button
              type="button"
              onClick={() => setActiveFilter('all')}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeFilter === 'all'
                  ? 'bg-gray-700 text-gray-200'
                  : 'bg-gray-900 text-gray-500 hover:text-gray-300 border border-gray-800'
              }`}
            >
              All <span className="ml-1 opacity-60">{enriched.length}</span>
            </button>
            {activeDomains.map(d => (
              <button
                key={d.value}
                type="button"
                onClick={() => setActiveFilter(d.value)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeFilter === d.value
                    ? `${d.pill} border ${d.border}`
                    : 'bg-gray-900 text-gray-500 hover:text-gray-300 border border-gray-800'
                }`}
              >
                {d.label}
                <span className="ml-1 opacity-60">{enriched.filter(g => g.domain === d.value).length}</span>
              </button>
            ))}
            {unclassified.length > 0 && (
              <button
                type="button"
                onClick={() => setActiveFilter('unclassified')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  activeFilter === 'unclassified'
                    ? 'bg-gray-700 text-gray-300 border border-gray-600'
                    : 'bg-gray-900 text-gray-500 hover:text-gray-300 border border-gray-800'
                }`}
              >
                Unclassified <span className="ml-1 opacity-60">{unclassified.length}</span>
              </button>
            )}
          </div>

          {/* Graph cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {visibleGraphs.map((g: any) => {
              const d = domainFor(g.domain);
              return (
                <div
                  key={`${g.provider}-${g.name}`}
                  className={`bg-gray-900 border border-gray-800 border-l-2 ${d?.accent ?? 'border-l-gray-600'} rounded-xl p-5 hover:bg-gray-800/40 transition-colors flex flex-col gap-3`}
                >
                  {/* Card header */}
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-sm font-semibold text-gray-200 leading-snug break-all">{g.name}</h4>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleDeleteGraph(g.name, g.provider)}
                        className="p-1 rounded hover:bg-red-500/20 text-gray-600 hover:text-red-400 transition-colors"
                        title="Delete graph"
                      >
                        <Trash2 size={13} />
                      </button>
                      {d ? (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${d.pill}`}>{d.label}</span>
                      ) : (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 text-gray-500">Unclassified</span>
                      )}
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="flex gap-4 text-xs text-gray-500">
                    <span className="flex items-center gap-1.5">
                      <FileText size={12} className="text-gray-600" />
                      {(g.rules || 0).toLocaleString()} rules
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Users size={12} className="text-gray-600" />
                      {(g.entities || 0).toLocaleString()} entities
                    </span>
                    {g.has_optimized && (
                      <span className="text-amber-500/60 ml-auto">✦ optimized</span>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2 mt-auto">
                    <button
                      type="button"
                      onClick={() => nav(`/explorer?graph=${encodeURIComponent(g.name)}&provider=${g.provider}`)}
                      className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${d ? `${d.bg} ${d.color} hover:opacity-80` : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
                    >
                      Explore
                    </button>
                    <button
                      type="button"
                      onClick={() => nav('/pipeline')}
                      className="px-4 py-1.5 rounded-lg text-xs bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300 transition-colors"
                    >
                      Join
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Recent Runs ────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Recent Runs</h3>
          <button type="button" onClick={() => nav('/runs')} className="text-sm text-blue-400 hover:text-blue-300">
            View all
          </button>
        </div>
        {runs.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-600">
            No pipeline runs yet.{' '}
            <button type="button" onClick={() => nav('/pipeline')} className="text-blue-400 hover:underline">
              Go to Pipeline
            </button>{' '}
            to start one.
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-800 rounded-xl divide-y divide-gray-800">
            {runs.slice(0, 5).map((r: any) => (
              <div
                key={r.id}
                className="flex items-center gap-3 px-5 py-3 hover:bg-gray-800/40 cursor-pointer transition-colors"
                onClick={() => nav('/runs')}
              >
                {statusIcon(r.status)}
                <span className="text-sm text-gray-300 flex-1 truncate">
                  {r.type === 'comparison'
                    ? <><Sparkles size={13} className="inline text-purple-400 mr-1" />KG Joining</>
                    : <><Network  size={13} className="inline text-blue-400   mr-1" />KG Creation</>
                  }
                  {r.domain && <span className="text-gray-500 ml-1">— {r.domain}</span>}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  r.status === 'completed'  ? 'bg-green-500/10 text-green-400'  :
                  r.status === 'failed'     ? 'bg-red-500/10 text-red-400'      :
                  r.status === 'running'    ? 'bg-blue-500/10 text-blue-400'    :
                  r.status === 'cancelled'  ? 'bg-orange-500/10 text-orange-400':
                  'bg-gray-800 text-gray-500'
                }`}>{r.status}</span>
                <span className="text-xs text-gray-500 w-16 text-right font-mono">{formatDuration(r.started_at, r.finished_at)}</span>
                <span className="text-xs text-gray-600 w-20 text-right">{timeAgo(r.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
