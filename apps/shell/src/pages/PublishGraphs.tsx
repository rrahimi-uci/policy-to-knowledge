import { useEffect, useState, useCallback } from 'react';
import { apiUrl } from '@/config';
import {
  Database,
  Upload,
  CheckCircle2,
  Loader2,
  AlertTriangle,
  RefreshCw,
  Sparkles,
  Layers,
  ArrowRight,
  CircleDot,
} from 'lucide-react';

/* ─── Types ──────────────────────────────────────────────────── */

interface AvailableGraph {
  source_name: string;
  provider: string;
  graph_key: string;
  display_name: string;
  rules: number;
  entities: number;
  is_optimized: boolean;
  is_published: boolean;
}

interface PublishedGraph {
  graph_key: string;
  display_name: string;
  traversal_source: string;
  has_data: boolean;
}

type ActionState = 'idle' | 'publishing' | 'activating' | 'done' | 'error';

interface GraphAction {
  state: ActionState;
  message: string;
}

/* ─── Component ──────────────────────────────────────────────── */

export default function PublishGraphs() {
  const [available, setAvailable] = useState<AvailableGraph[]>([]);
  const [published, setPublished] = useState<PublishedGraph[]>([]);
  const [loading, setLoading] = useState(true);
  const [actions, setActions] = useState<Record<string, GraphAction>>({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [avRes, pubRes] = await Promise.all([
        fetch(apiUrl('ca/graph/available')),
        fetch(apiUrl('ca/graph/published')),
      ]);
      if (avRes.ok) {
        const d = await avRes.json();
        setAvailable(d.available ?? []);
      }
      if (pubRes.ok) {
        const d = await pubRes.json();
        setPublished(d.graphs ?? []);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const publishedMap = new Map(published.map((g) => [g.graph_key, g]));

  const getStatus = (g: AvailableGraph): 'available' | 'published' | 'active' => {
    const pub = publishedMap.get(g.graph_key);
    if (!pub) return 'available';
    return pub.has_data ? 'active' : 'published';
  };

  const handlePublish = async (g: AvailableGraph) => {
    setActions((a) => ({ ...a, [g.graph_key]: { state: 'publishing', message: 'Publishing config…' } }));
    try {
      const res = await fetch(apiUrl('ca/graph/publish'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_name: g.source_name,
          provider: g.provider,
          display_name: g.display_name,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setActions((a) => ({ ...a, [g.graph_key]: { state: 'error', message: data.error ?? 'Publish failed' } }));
        return;
      }
      setActions((a) => ({
        ...a,
        [g.graph_key]: {
          state: 'done',
          message: `Published — ${data.rules} rules, ${data.entities} entities. Restart services to activate.`,
        },
      }));
      fetchData();
    } catch (err) {
      setActions((a) => ({ ...a, [g.graph_key]: { state: 'error', message: String(err) } }));
    }
  };

  const handleActivate = async (g: AvailableGraph) => {
    setActions((a) => ({ ...a, [g.graph_key]: { state: 'activating', message: 'Creating schema & loading data…' } }));
    try {
      const res = await fetch(apiUrl('ca/graph/activate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph_key: g.graph_key }),
      });
      const data = await res.json();
      if (!res.ok) {
        setActions((a) => ({ ...a, [g.graph_key]: { state: 'error', message: data.error ?? 'Activation failed' } }));
        return;
      }
      setActions((a) => ({
        ...a,
        [g.graph_key]: { state: 'done', message: data.status === 'already_loaded' ? 'Already active' : 'Activated successfully' },
      }));
      fetchData();
    } catch (err) {
      setActions((a) => ({ ...a, [g.graph_key]: { state: 'error', message: String(err) } }));
    }
  };

  const availableGraphs = available.filter((g) => getStatus(g) === 'available');
  const publishedGraphs = available.filter((g) => getStatus(g) === 'published');
  const activeGraphs = available.filter((g) => getStatus(g) === 'active');

  return (
    <div className="p-8 page-enter max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Publish to Graph DB</h1>
          <p className="text-sm text-gray-500 mt-1">
            Select pipeline-generated knowledge graphs and publish them to JanusGraph
          </p>
        </div>
        <button
          type="button"
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {loading && available.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        </div>
      ) : available.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          {/* Available for publishing */}
          {availableGraphs.length > 0 && (
            <Section title="Available Pipeline Outputs" count={availableGraphs.length} color="blue">
              {availableGraphs.map((g) => (
                <GraphCard
                  key={g.graph_key}
                  graph={g}
                  status="available"
                  action={actions[g.graph_key]}
                  onPublish={() => handlePublish(g)}
                  onActivate={() => handleActivate(g)}
                />
              ))}
            </Section>
          )}

          {/* Published but not loaded */}
          {publishedGraphs.length > 0 && (
            <Section title="Published — Awaiting Activation" count={publishedGraphs.length} color="amber">
              {publishedGraphs.map((g) => (
                <GraphCard
                  key={g.graph_key}
                  graph={g}
                  status="published"
                  action={actions[g.graph_key]}
                  onPublish={() => handlePublish(g)}
                  onActivate={() => handleActivate(g)}
                />
              ))}
            </Section>
          )}

          {/* Active */}
          {activeGraphs.length > 0 && (
            <Section title="Active in Graph DB" count={activeGraphs.length} color="emerald">
              {activeGraphs.map((g) => (
                <GraphCard
                  key={g.graph_key}
                  graph={g}
                  status="active"
                  action={actions[g.graph_key]}
                  onPublish={() => handlePublish(g)}
                  onActivate={() => handleActivate(g)}
                />
              ))}
            </Section>
          )}
        </>
      )}
    </div>
  );
}

/* ═══ Sub-components ═════════════════════════════════════════════ */

function Section({
  title,
  count,
  color,
  children,
}: {
  title: string;
  count: number;
  color: 'blue' | 'amber' | 'emerald';
  children: React.ReactNode;
}) {
  const dotColors = {
    blue: 'bg-blue-400',
    amber: 'bg-amber-400',
    emerald: 'bg-emerald-400',
  };
  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <span className={`h-2 w-2 rounded-full ${dotColors[color]}`} />
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
          {title}
        </h2>
        <span className="text-xs text-gray-600">({count})</span>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function GraphCard({
  graph: g,
  status,
  action,
  onPublish,
  onActivate,
}: {
  graph: AvailableGraph;
  status: 'available' | 'published' | 'active';
  action?: GraphAction;
  onPublish: () => void;
  onActivate: () => void;
}) {
  const busy = action?.state === 'publishing' || action?.state === 'activating';

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 flex items-center gap-4 hover:border-gray-700 transition-colors">
      {/* Icon */}
      <div
        className={`flex items-center justify-center h-11 w-11 rounded-lg shrink-0 ${
          status === 'active'
            ? 'bg-emerald-500/10'
            : status === 'published'
              ? 'bg-amber-500/10'
              : 'bg-indigo-500/10'
        }`}
      >
        {status === 'active' ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
        ) : status === 'published' ? (
          <CircleDot className="h-5 w-5 text-amber-400" />
        ) : (
          <Database className="h-5 w-5 text-indigo-400" />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-200 truncate">{g.display_name}</span>
          {g.is_optimized && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20 flex items-center gap-1">
              <Sparkles size={10} /> optimized
            </span>
          )}
        </div>
        <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
          <span className="font-mono text-gray-600">{g.provider}</span>
          <span>·</span>
          <span>{g.rules} rules</span>
          <span>·</span>
          <span>{g.entities} entities</span>
        </div>
        {action && (
          <div
            className={`text-xs mt-1 ${
              action.state === 'error'
                ? 'text-red-400'
                : action.state === 'done'
                  ? 'text-emerald-400'
                  : 'text-blue-400'
            }`}
          >
            {action.message}
          </div>
        )}
      </div>

      {/* Action button */}
      <div className="shrink-0">
        {status === 'available' && (
          <button
            type="button"
            onClick={onPublish}
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Upload size={14} />
            )}
            Publish to Graph DB
          </button>
        )}
        {status === 'published' && (
          <button
            type="button"
            onClick={onActivate}
            disabled={busy}
            className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <ArrowRight size={14} />
            )}
            Activate
          </button>
        )}
        {status === 'active' && (
          <span className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <Layers size={14} />
            In Graph DB
          </span>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <AlertTriangle className="h-10 w-10 text-gray-700 mb-3" />
      <p className="text-sm text-gray-400">No pipeline outputs found</p>
      <p className="text-xs text-gray-600 mt-1">
        Run the extraction pipeline first to generate knowledge graphs
      </p>
    </div>
  );
}
