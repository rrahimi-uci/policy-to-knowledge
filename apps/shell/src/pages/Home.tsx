import { useEffect, useState } from 'react';
import { apiUrl } from '@/config';
import {
  Network,
  FileText,
  MessageSquare,
  Activity,
  GitCompareArrows,
  ArrowRight,
  Play,
  FolderOpen,
  CheckCircle2,
  Clock,
  Layers,
  Sparkles,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

/* ─── data types ─────────────────────────────────────────────── */

interface Graph {
  name: string;
  provider: string;
  rules: number;
  entities: number;
  has_optimized: boolean;
  has_visualization: boolean;
}

interface DocDir {
  name: string;
  file_count: number;
}

interface Run {
  id: string;
  type: string;
  status: string;
  domain: string;
  provider: string;
  started_at: string;
  finished_at: string | null;
  documents: string[];
}

/* ─── helpers ────────────────────────────────────────────────── */

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function duration(start: string, end: string | null): string {
  if (!end) return '—';
  const s = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}m ${sec}s`;
}

/* ─── page component ─────────────────────────────────────────── */

export default function Home() {
  const navigate = useNavigate();
  const [graphs, setGraphs] = useState<Graph[]>([]);
  const [docDirs, setDocDirs] = useState<DocDir[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [kgOk, setKgOk] = useState(false);
  const [caOk, setCaOk] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    const s = ac.signal;

    fetch(apiUrl('kg/graphs'), { signal: s })
      .then((r) => r.json())
      .then((d) => { setGraphs(d.graphs ?? []); setKgOk(true); })
      .catch(() => {});

    fetch(apiUrl('kg/documents'), { signal: s })
      .then((r) => r.json())
      .then((d) => setDocDirs(d.subdirectories ?? []))
      .catch(() => {});

    fetch(apiUrl('kg/runs'), { signal: s })
      .then((r) => r.json())
      .then((d) => setRuns((d.runs ?? []).slice(0, 5)))
      .catch(() => {});

    fetch(apiUrl('ca/'), { signal: s })
      .then((r) => { if (r.ok) setCaOk(true); })
      .catch(() => {});

    return () => ac.abort();
  }, []);

  const totalRules = graphs.reduce((n, g) => n + g.rules, 0);
  const totalEntities = graphs.reduce((n, g) => n + g.entities, 0);
  const totalDocs = docDirs.reduce((n, d) => n + d.file_count, 0);

  return (
    <div className="page-enter max-w-6xl mx-auto space-y-8">
      {/* ── Hero ─────────────────────────────────────── */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">
            Compliance Knowledge Extraction, Exploration, Editing &amp; Versioning
          </p>
        </div>
        <div className="flex gap-2">
          <ServicePill name="KG Extraction" ok={kgOk} />
          <ServicePill name="Assistant" ok={caOk} />
        </div>
      </div>

      {/* ── Stat cards ───────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Network}
          label="Knowledge Graphs"
          value={graphs.length}
          sub={`${totalRules.toLocaleString()} rules · ${totalEntities} entities`}
          color="bg-indigo-500"
          onClick={() => navigate('/extraction/explorer')}
        />
        <StatCard
          icon={FileText}
          label="Source Documents"
          value={totalDocs}
          sub={`across ${docDirs.length} collection${docDirs.length !== 1 ? 's' : ''}`}
          color="bg-cyan-500"
          onClick={() => navigate('/extraction/documents')}
        />
        <StatCard
          icon={Activity}
          label="Pipeline Runs"
          value={runs.length > 0 ? runs.length + '+' : '—'}
          sub={runs[0] ? `latest: ${runs[0].status}` : 'no runs yet'}
          color="bg-emerald-500"
          onClick={() => navigate('/extraction/runs')}
        />
        <StatCard
          icon={MessageSquare}
          label="Assistant"
          value={caOk ? 'Online' : 'Offline'}
          sub={caOk ? 'Chat & Explore ready' : 'Service unavailable'}
          color="bg-violet-500"
          onClick={() => navigate('/assistant/chat')}
        />
      </div>

      {/* ── Two-column: Graphs + Recent Runs ─────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Knowledge Graphs */}
        <section className="lg:col-span-3 rounded-xl border border-gray-800 bg-gray-900/60 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
            <h2 className="text-sm font-semibold text-gray-200">Knowledge Graphs</h2>
            <button
              type="button"
              onClick={() => navigate('/extraction/explorer')}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              View all
            </button>
          </div>
          {graphs.length === 0 ? (
            <EmptyState
              icon={Network}
              message="No knowledge graphs yet"
              action="Run Extraction Pipeline"
              onClick={() => navigate('/extraction/pipeline')}
            />
          ) : (
            <div className="divide-y divide-gray-800">
              {graphs.slice(0, 5).map((g) => (
                <button
                  key={g.name}
                  type="button"
                  onClick={() => navigate('/extraction/explorer')}
                  className="flex items-center gap-4 w-full px-5 py-3.5 text-left hover:bg-gray-800/50 transition-colors group"
                >
                  <div className="flex items-center justify-center h-9 w-9 rounded-lg bg-indigo-500/10 shrink-0">
                    <Network className="h-4 w-4 text-indigo-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-200 truncate group-hover:text-white transition-colors">
                      {g.name.replace(/_/g, ' ')}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {g.provider} · {g.rules} rules · {g.entities} entities
                    </div>
                  </div>
                  {g.has_optimized && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      optimized
                    </span>
                  )}
                  <ArrowRight className="h-3.5 w-3.5 text-gray-700 group-hover:text-gray-400 transition-colors" />
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Recent Runs */}
        <section className="lg:col-span-2 rounded-xl border border-gray-800 bg-gray-900/60 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
            <h2 className="text-sm font-semibold text-gray-200">Recent Runs</h2>
            <button
              type="button"
              onClick={() => navigate('/extraction/runs')}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              View all
            </button>
          </div>
          {runs.length === 0 ? (
            <EmptyState
              icon={Activity}
              message="No pipeline runs yet"
              action="Start a Run"
              onClick={() => navigate('/extraction/pipeline')}
            />
          ) : (
            <div className="divide-y divide-gray-800">
              {runs.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => navigate('/extraction/runs')}
                  className="flex items-center gap-3 w-full px-5 py-3 text-left hover:bg-gray-800/50 transition-colors"
                >
                  <RunStatusIcon status={r.status} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-gray-300 truncate">
                      {r.documents?.[0]?.split('/').pop() ?? r.domain}
                    </div>
                    <div className="text-xs text-gray-600 mt-0.5 flex items-center gap-2">
                      <span>{r.domain}</span>
                      <span>·</span>
                      <span className="font-mono">{duration(r.started_at, r.finished_at)}</span>
                    </div>
                  </div>
                  <span className="text-xs text-gray-600 shrink-0">{timeAgo(r.started_at)}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ── Quick Actions ────────────────────────────── */}
      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <QuickAction
            icon={Play}
            label="Run Extraction"
            description="Upload docs & build a knowledge graph"
            onClick={() => navigate('/extraction/pipeline')}
          />
          <QuickAction
            icon={Sparkles}
            label="Chat & Explore"
            description="AI-powered knowledge graph exploration"
            onClick={() => navigate('/assistant/chat')}
          />
          <QuickAction
            icon={GitCompareArrows}
            label="Compare Knowledge Graphs"
            description="Diff, union & intersect knowledge graph versions"
            onClick={() => navigate('/extraction/compare')}
          />
          <QuickAction
            icon={FolderOpen}
            label="Manage Documents"
            description="View and organize source documents"
            onClick={() => navigate('/extraction/documents')}
          />
        </div>
      </div>
    </div>
  );
}

/* ═══ Sub-components ═════════════════════════════════════════════ */

function StatCard({
  icon: Icon, label, value, sub, color, onClick,
}: {
  icon: typeof Network;
  label: string;
  value: string | number;
  sub: string;
  color: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-3 rounded-xl border border-gray-800 bg-gray-900/60 p-5 text-left transition-all hover:border-gray-700 hover:bg-gray-900/80 group"
    >
      <div className={`flex items-center justify-center h-9 w-9 rounded-lg ${color}/10`}>
        <Icon className={`h-4 w-4 ${color.replace('bg-', 'text-').replace('500', '400')}`} />
      </div>
      <div>
        <div className="text-2xl font-bold text-gray-100 leading-none">{value}</div>
        <div className="text-xs text-gray-400 mt-1.5 font-medium">{label}</div>
        <div className="text-[10px] text-gray-600 mt-0.5">{sub}</div>
      </div>
    </button>
  );
}

function ServicePill({ name, ok }: { name: string; ok: boolean }) {
  return (
    <div className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs border ${
      ok
        ? 'border-emerald-800 bg-emerald-950/50 text-emerald-400'
        : 'border-gray-800 bg-gray-900/50 text-gray-500'
    }`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
      {name}
    </div>
  );
}

function RunStatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />;
  if (status === 'running') return <Layers className="h-4 w-4 text-blue-400 animate-spin shrink-0" />;
  if (status === 'failed') return <Activity className="h-4 w-4 text-red-400 shrink-0" />;
  return <Clock className="h-4 w-4 text-gray-500 shrink-0" />;
}

function QuickAction({
  icon: Icon, label, description, onClick,
}: {
  icon: typeof Play; label: string; description: string; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-3 rounded-xl border border-gray-800 bg-gray-900/60 px-4 py-3.5 text-left transition-all hover:border-gray-700 hover:bg-gray-900/80 group"
    >
      <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-gray-800 group-hover:bg-gray-700 transition-colors shrink-0">
        <Icon className="h-4 w-4 text-gray-400 group-hover:text-blue-400 transition-colors" />
      </div>
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-200 group-hover:text-white transition-colors flex items-center gap-1">
          {label}
          <ArrowRight className="h-3 w-3 text-gray-700 group-hover:text-blue-400 transition-colors" />
        </div>
        <div className="text-xs text-gray-500 leading-snug">{description}</div>
      </div>
    </button>
  );
}

function EmptyState({
  icon: Icon, message, action, onClick,
}: {
  icon: typeof Network; message: string; action: string; onClick: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-10 px-5 text-center">
      <Icon className="h-8 w-8 text-gray-700 mb-3" />
      <p className="text-sm text-gray-500">{message}</p>
      <button
        type="button"
        onClick={onClick}
        className="mt-3 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        {action} &rarr;
      </button>
    </div>
  );
}
