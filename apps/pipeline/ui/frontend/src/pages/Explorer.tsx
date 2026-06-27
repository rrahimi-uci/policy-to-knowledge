import { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { fetchGraphs, fetchGraphData, getVisualizationUrl, getExportUrl, startPublish, fetchPublishedGraphs } from '../api';
import GraphEmbed from '../components/GraphEmbed';
import RuleTable from '../components/RuleTable';
import { useTheme } from '../hooks/useTheme';
import { Loader2, Download, Network, Search, CheckCircle2, XCircle, Database, RefreshCw } from 'lucide-react';

const MORTGAGE_COLORS: Record<string, string> = {
  eligibility: '#3b82f6', constraint: '#ef4444', calculation: '#06b6d4',
  validation: '#f59e0b', process: '#ec4899', compliance: '#10b981',
  documentation: '#8b5cf6', prohibition: '#dc2626', definition: '#6366f1',
  exception: '#f97316', unknown: '#64748b',
};

const AML_COLORS: Record<string, string> = {
  reporting: '#e11d48', monitoring: '#0284c7', screening: '#7c3aed',
  eligibility: '#3b82f6', constraint: '#ef4444', compliance: '#10b981',
  documentation: '#8b5cf6', process: '#ec4899', calculation: '#06b6d4',
  validation: '#f59e0b', unknown: '#64748b',
};

const HEALTHCARE_COLORS: Record<string, string> = {
  clinical_guideline: '#059669', patient_safety: '#e11d48', hipaa_privacy: '#7c3aed',
  billing_compliance: '#f59e0b', documentation: '#8b5cf6', consent_requirement: '#06b6d4',
  credentialing: '#3b82f6', quality_measure: '#10b981', regulatory: '#ec4899',
  reporting: '#dc2626', unknown: '#64748b',
};

const COMMERCIAL_LENDING_COLORS: Record<string, string> = {
  credit_policy: '#3b82f6', collateral: '#ef4444', covenant: '#06b6d4',
  regulatory: '#10b981', documentation: '#8b5cf6', underwriting: '#f59e0b',
  risk_assessment: '#ec4899', compliance: '#7c3aed', pricing: '#f97316',
  reporting: '#e11d48', unknown: '#64748b',
};

function graphNameToDomain(name: string): string {
  const l = name.toLowerCase();
  if (l.startsWith('aml') || l.includes('anti_money') || l.includes('anti-money')) return 'aml';
  if (l.startsWith('healthcare') || l.startsWith('cms') || l.includes('hipaa') || l.includes('medicare') || l.includes('medicaid')) return 'healthcare';
  if (l.includes('lending') || l.includes('commercial') || l.includes('comercial')) return 'commercial_lending';
  return 'mortgage';
}

export default function Explorer() {
  const { theme } = useTheme();
  const [graphs, setGraphs] = useState<any[]>([]);
  const [selectedGraph, setSelectedGraph] = useState<string>('');
  const [graphData, setGraphData] = useState<any>(null);
  const [tab, setTab] = useState<'graph' | 'rules' | 'entities'>('graph');
  const [loading, setLoading] = useState(true);
  const [entityFilter, setEntityFilter] = useState<string>('');
  const [entitySearch, setEntitySearch] = useState('');
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // Publish state
  const [publishedWithData, setPublishedWithData] = useState<Set<string>>(new Set());
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<{ status: string; message: string; runId?: string } | null>(null);

  const selectedProvider = graphs.find(g => g.name === selectedGraph)?.provider || 'openai';

  const domain = selectedGraph ? graphNameToDomain(selectedGraph) : 'mortgage';
  const typeColors = domain === 'aml' ? AML_COLORS
    : domain === 'healthcare' ? HEALTHCARE_COLORS
    : domain === 'commercial_lending' ? COMMERCIAL_LENDING_COLORS
    : MORTGAGE_COLORS;

  useEffect(() => {
    setSelectedGraph('');
    setEntityFilter('');
    // Show every graph that exists on disk under pipeline-output/, then
    // separately mark which ones are actually loaded into the Graph DB so
    // the user can publish (or republish) anything that's missing.
    Promise.all([
      fetchGraphs().catch(() => ({ graphs: [] })),
      fetchPublishedGraphs().catch(() => ({ graphs: [] })),
    ])
      .then(([gRes, pRes]) => {
        const all = gRes.graphs || [];
        const published = pRes.graphs || [];
        const liveKeys = new Set<string>(
          published.filter((p: any) => p.has_data).map((p: any) => p.graph_key)
        );
        setPublishedWithData(liveKeys);
        setGraphs(all);

        const urlGraph = searchParams.get('graph');
        const urlProvider = searchParams.get('provider');
        const match = urlGraph && all.find((gr: any) => gr.name === urlGraph && (!urlProvider || gr.provider === urlProvider));
        if (match) setSelectedGraph(match.name);
        else if (all.length > 0) setSelectedGraph(all[0].name);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    setEntityFilter('');
    if (!selectedGraph) return;
    setLoading(true);
    fetchGraphData(selectedGraph, selectedProvider)
      .then(data => { setGraphData(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedGraph, selectedProvider]);

  // Build a map of relationship-name → {source, target} so rules tagged
  // with a relationship name (rather than an entity name) can still be
  // attributed back to the entities they connect.
  const relMap = (() => {
    const out: Record<string, { source: string; target: string }> = {};
    if (!graphData) return out;
    const raw = graphData.relationships;
    if (raw && !Array.isArray(raw) && typeof raw === 'object') {
      for (const [name, info] of Object.entries(raw as Record<string, any>)) {
        if (info && typeof info === 'object') {
          out[name] = {
            source: info.source_entity ?? info.source ?? '',
            target: info.target_entity ?? info.target ?? '',
          };
        }
      }
    } else if (Array.isArray(raw)) {
      for (const info of raw) {
        if (info && typeof info === 'object') {
          const name = info.relationship_type ?? info.name ?? '';
          if (name) {
            out[name] = {
              source: info.source_entity ?? info.source ?? '',
              target: info.target_entity ?? info.target ?? '',
            };
          }
        }
      }
    }
    return out;
  })();

  // Normalize a raw rule object to the fields RuleTable expects:
  //   title        ← rule_name | title | description[:80]
  //   confidence   ← confidence | confidence_score
  //   entities     ← entities | [entity_or_relationship] expanded with the
  //                  source/target entities of any tagged relationship
  const normalizeRule = (r: any, entity_source?: string) => {
    const baseEntities: string[] = Array.isArray(r.entities)
      ? r.entities
      : r.entity_or_relationship
        ? [r.entity_or_relationship]
        : [];
    const expanded = new Set<string>(baseEntities);
    for (const tag of baseEntities) {
      const rel = relMap[tag];
      if (rel) {
        if (rel.source) expanded.add(rel.source);
        if (rel.target) expanded.add(rel.target);
      }
    }
    return {
      ...r,
      entity_source,
      title: r.title ?? r.rule_name ?? undefined,
      confidence: r.confidence ?? r.confidence_score ?? undefined,
      entities: Array.from(expanded),
    };
  };

  // Flatten rules from root business_rules plus any entity-level rules that
  // are NOT already present in root (by rule_id).  Root rules are the source
  // of truth — they are what data_loader.py loads into JanusGraph — so they
  // are always included first.  Entity-type nested rules are only included
  // when they are genuinely unique (older pipeline formats) to avoid
  // double-counting rules that appear in both locations.
  const allRules = (() => {
    if (!graphData) return [];
    const fromRoot = (graphData.business_rules || [])
      .filter((r: any) => r && typeof r === 'object')
      .map((r: any) => normalizeRule(r));
    const rootIds = new Set(fromRoot.map((r: any) => r.rule_id).filter(Boolean));
    const entityOnly = Object.entries(graphData.entity_types || {}).flatMap(
      ([entity, data]: [string, any]) =>
        (data.business_rules || [])
          .filter((r: any) => r && typeof r === 'object' && !rootIds.has(r.rule_id))
          .map((r: any) => normalizeRule(r, entity))
    );
    return [...fromRoot, ...entityOnly];
  })();

  const entities = (() => {
    if (!graphData) return [];
    return Object.entries(graphData.entity_types || {}).map(
      ([name, data]: [string, any]) => ({
        name,
        // commercial_lending uses "definition"; mortgage/aml use "description"
        description: data.description ?? data.definition,
        attributes: data.attributes,
        rule_count: allRules.filter((r: any) => {
          if (r.entity_source === name) return true;
          const rEntities: string[] = r.entities || [];
          return rEntities.includes(name);
        }).length,
      })
    );
  })();

  const filteredEntities = entities.filter(e =>
    !entitySearch || e.name.toLowerCase().includes(entitySearch.toLowerCase())
  );

  // Rule type distribution for chart
  const typeDistribution = (() => {
    const counts: Record<string, number> = {};
    allRules.forEach(r => {
      const t = (r.rule_type || 'unknown').toLowerCase();
      counts[t] = (counts[t] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({ type, count, pct: allRules.length ? Math.round(count / allRules.length * 100) : 0 }));
  })();

  const handleEntityClick = (entity: string) => {
    if (entity === entityFilter || !entity) {
      setEntityFilter('');
    } else {
      setEntityFilter(entity);
      setTab('rules');
    }
  };

  // Derive graph_key the same way the backend does
  const selectedGraphKey = selectedGraph
    ? selectedGraph.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')
    : '';
  const isActive = publishedWithData.has(selectedGraphKey);

  const handlePublish = useCallback(async () => {
    if (!selectedGraph || publishing) return;
    setPublishing(true);
    setPublishResult(null);
    try {
      const res = await startPublish(selectedGraph, selectedProvider);
      setPublishedWithData(prev => new Set([...prev, selectedGraphKey]));
      setPublishResult({
        status: 'success',
        message: isActive ? 'Graph DB refresh started — tracking in Run History' : 'Publishing started — tracking in Run History',
        runId: res.run_id,
      });
      // Navigate to run history after a short delay so the user sees the banner
      setTimeout(() => navigate('/runs'), 1500);
    } catch (err: any) {
      const msg = err.message || 'Publish failed';
      if (msg.includes('already published')) {
        setPublishedWithData(prev => new Set([...prev, selectedGraphKey]));
        setPublishResult({ status: 'info', message: 'Graph is already published to Graph DB' });
      } else {
        setPublishResult({ status: 'error', message: msg });
      }
    } finally {
      setPublishing(false);
    }
  }, [selectedGraph, selectedProvider, publishing, selectedGraphKey, navigate, isActive]);

  if (loading && graphs.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-blue-400" size={32} />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Knowledge Graph Explorer</h2>
        <div className="flex items-center gap-3">
          <select
            value={selectedGraph}
            onChange={(e) => setSelectedGraph(e.target.value)}
            aria-label="Knowledge graph"
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          >
            {graphs.length === 0 && (
              <option value="">No graphs found in pipeline-output — run extraction first</option>
            )}
            {graphs.map(g => {
              const key = g.name.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
              const live = publishedWithData.has(key);
              return (
                <option key={g.name} value={g.name}>
                  {live ? '●' : '○'} {g.name} ({g.rules} rules){live ? '' : ' — not in DB'}
                </option>
              );
            })}
          </select>
          {selectedGraph && (
            <div className="flex gap-1.5">
              {isActive ? (
                <span className="px-3 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-xs text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 size={14} /> In Graph DB
                </span>
              ) : (
                <span className="px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs text-amber-400 flex items-center gap-1.5">
                  <XCircle size={14} /> Not in Graph DB
                </span>
              )}
              <button
                onClick={handlePublish}
                disabled={publishing}
                className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50 border border-blue-500 rounded-lg text-xs text-white flex items-center gap-1.5 transition-colors"
              >
                {publishing ? <Loader2 size={14} className="animate-spin" /> : isActive ? <RefreshCw size={14} /> : <Database size={14} />}
                {publishing ? (isActive ? 'Refreshing\u2026' : 'Publishing\u2026') : (isActive ? 'Refresh Graph DB' : 'Publish to Graph DB')}
              </button>
              <a
                href={getExportUrl(selectedGraph, 'json', selectedProvider)}
                download={`${selectedGraph}_graph.json`}
                className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-xs text-gray-300 hover:bg-gray-700 flex items-center gap-1.5"
              >
                <Download size={14} /> JSON
              </a>
              <a
                href={getExportUrl(selectedGraph, 'csv', selectedProvider)}
                download={`${selectedGraph}_rules.csv`}
                className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-xs text-gray-300 hover:bg-gray-700 flex items-center gap-1.5"
              >
                <Download size={14} /> CSV
              </a>
            </div>
          )}
        </div>
      </div>

      {!selectedGraph ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500">
          No knowledge graphs found. Run the extraction pipeline first.
        </div>
      ) : (
        <>
          {/* Publish result banner */}
          {publishResult && (
            <div className={`mb-4 px-4 py-3 rounded-xl border text-sm ${
              publishResult.status === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : publishResult.status === 'info'
                ? 'bg-blue-500/10 border-blue-500/30 text-blue-300'
                : 'bg-red-500/10 border-red-500/30 text-red-300'
            }`}>
              <div className="flex items-center gap-3">
                {publishResult.status === 'success' ? <CheckCircle2 size={18} className="shrink-0" /> :
                 publishResult.status === 'error' ? <XCircle size={18} className="shrink-0" /> :
                 <Database size={18} className="shrink-0" />}
                <span className="flex-1">{publishResult.message}</span>
                <button
                  onClick={() => setPublishResult(null)}
                  className="text-gray-400 hover:text-gray-200 text-xs shrink-0"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 mb-4 bg-gray-900 border border-gray-800 rounded-lg p-1 w-fit">
            {(['graph', 'rules', 'entities'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  tab === t
                    ? 'bg-blue-500/20 text-blue-400'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`}
              >
                {t === 'graph' ? 'Graph View' : t === 'rules' ? `Rules (${allRules.length})` : `Entities (${entities.length})`}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="animate-spin text-blue-400" size={24} />
            </div>
          ) : (
            <>
              {tab === 'graph' && (
                <GraphEmbed
                  src={getVisualizationUrl(selectedGraph, selectedProvider, theme)}
                  title={selectedGraph}
                />
              )}

              {tab === 'rules' && (
                <>
                  {/* Rule type distribution bar */}
                  {typeDistribution.length > 0 && (
                    <div className="mb-4 bg-gray-900 border border-gray-800 rounded-xl p-4">
                      <h4 className="text-xs text-gray-500 uppercase tracking-wider mb-3">Rule Type Distribution</h4>
                      <div className="space-y-2">
                        {typeDistribution.map(({ type, count, pct }) => (
                          <div key={type} className="flex items-center gap-3">
                            <span className="text-xs text-gray-400 w-24 truncate capitalize">{type}</span>
                            <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{
                                  width: `${pct}%`,
                                  backgroundColor: typeColors[type] || '#64748b',
                                }}
                              />
                            </div>
                            <span className="text-xs text-gray-500 w-16 text-right">{count} ({pct}%)</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <RuleTable
                    rules={allRules}
                    typeColors={typeColors}
                    entityFilter={entityFilter}
                    onEntityClick={handleEntityClick}
                  />
                </>
              )}

              {tab === 'entities' && (
                <div>
                  {/* Entity search */}
                  <div className="relative max-w-sm mb-4">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                      value={entitySearch}
                      onChange={e => setEntitySearch(e.target.value)}
                      placeholder="Search entities..."
                      className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredEntities.map(e => (
                      <div
                        key={e.name}
                        onClick={() => handleEntityClick(e.name)}
                        className={`bg-gray-900 border rounded-xl p-4 cursor-pointer transition-colors ${
                          entityFilter === e.name
                            ? 'border-purple-500/50 bg-purple-500/5'
                            : 'border-gray-800 hover:border-gray-700'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <Network size={16} className="text-purple-400" />
                          <h4 className="font-medium text-gray-200 text-sm">{e.name}</h4>
                          <span className="ml-auto text-xs text-gray-500">{e.rule_count} rules</span>
                        </div>
                        {e.description && (
                          <p className="text-xs text-gray-400 line-clamp-2 mb-2">{e.description}</p>
                        )}
                        {e.attributes && (
                          <div className="flex flex-wrap gap-1">
                            {(Array.isArray(e.attributes) ? e.attributes : Object.keys(e.attributes))
                              .slice(0, 5)
                              .map((attr: any) => (
                                <span
                                  key={typeof attr === 'string' ? attr : attr.name}
                                  className="px-1.5 py-0.5 bg-gray-800 rounded text-[10px] text-gray-400"
                                >
                                  {typeof attr === 'string' ? attr : attr.name}
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}

    </div>
  );
}
