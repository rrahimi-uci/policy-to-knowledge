import { useEffect, useState } from 'react';
import { fetchGraphs, fetchComparisons, getComparisonVizUrl } from '../api';
import GraphEmbed from '../components/GraphEmbed';
import { usePipeline } from '../hooks/usePipeline';
import ProgressTracker from '../components/ProgressTracker';
import LogViewer from '../components/LogViewer';
import { useTheme } from '../hooks/useTheme';
import { Loader2, GitCompareArrows, Square } from 'lucide-react';

export default function Compare() {
  const { theme } = useTheme();
  const provider = 'openai';
  const [graphs, setGraphs] = useState<any[]>([]);
  const [comparisons, setComparisons] = useState<any[]>([]);
  const [g1, setG1] = useState('');
  const [g2, setG2] = useState('');
  const [workers, setWorkers] = useState(15);
  const [batchSize, setBatchSize] = useState(10);
  const [selectedComparison, setSelectedComparison] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('intersection');
  const { runId, status, steps, logs, launch, cancel } = usePipeline('comparison');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchGraphs(provider).catch(() => ({ graphs: [] })),
      fetchComparisons(provider).catch(() => ({ comparisons: [] })),
    ]).then(([gr, co]) => {
      const g = gr.graphs || [];
      setGraphs(g);
      if (g.length >= 2) { setG1(g[0].name); setG2(g[1].name); }
      setComparisons(co.comparisons || []);
      setLoading(false);
    });
  }, [provider]);

  const isRunning = status === 'running';

  const handleCompare = async () => {
    await launch({
      g1, g2, provider, workers, batch_size: batchSize,
    });
  };

  const ops = [
    { key: 'intersection', label: 'Intersection', symbol: '∩' },
    { key: 'g1_minus_g2', label: 'G1 − G2', symbol: '−' },
    { key: 'g2_minus_g1', label: 'G2 − G1', symbol: '−' },
    { key: 'union', label: 'Union', symbol: '∪' },
    { key: 'contradictions', label: 'Contradictions', symbol: '⚠' },
  ];

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-blue-400" size={32} /></div>;
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Graph Compare</h2>

      {/* Select Graphs */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Select Graphs</h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Graph 1 (G1)</label>
            <select
              aria-label="Graph 1"
              value={g1}
              onChange={(e) => setG1(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
              disabled={isRunning}
            >
              {graphs.map(g => <option key={g.name} value={g.name}>{g.name} ({g.rules} rules)</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Graph 2 (G2)</label>
            <select
              aria-label="Graph 2"
              value={g2}
              onChange={(e) => setG2(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
              disabled={isRunning}
            >
              {graphs.map(g => <option key={g.name} value={g.name}>{g.name} ({g.rules} rules)</option>)}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Workers: {workers}</label>
            <input type="range" min={1} max={30} value={workers} onChange={(e) => setWorkers(Number(e.target.value))} title="Comparison workers" aria-label="Comparison workers" className="w-full accent-blue-500" disabled={isRunning} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Batch Size: {batchSize}</label>
            <input type="range" min={1} max={20} value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} title="Comparison batch size" aria-label="Comparison batch size" className="w-full accent-blue-500" disabled={isRunning} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleCompare}
            disabled={!g1 || !g2 || g1 === g2 || isRunning}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium rounded-lg transition-colors"
          >
            <GitCompareArrows size={18} />
            Run Comparison
          </button>
          {isRunning && (
            <button
              onClick={() => cancel()}
              className="flex items-center gap-2 px-5 py-2.5 bg-red-600 hover:bg-red-500 text-white font-medium rounded-lg transition-colors"
            >
              <Square size={18} />
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Running comparison progress */}
      {runId && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div>
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Progress</h3>
            <ProgressTracker steps={steps} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Output</h3>
            <LogViewer logs={logs} />
          </div>
        </div>
      )}

      {/* Past Comparisons */}
      {comparisons.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Completed Comparisons</h3>
          <div className="space-y-3 mb-6">
            {comparisons.map(c => (
              <div
                key={c.name}
                onClick={() => setSelectedComparison(c.name)}
                className={`flex items-center gap-3 p-4 rounded-xl cursor-pointer transition-colors ${
                  selectedComparison === c.name
                    ? 'bg-blue-500/10 border border-blue-500/30'
                    : 'bg-gray-900 border border-gray-800 hover:border-gray-700'
                }`}
              >
                <GitCompareArrows size={18} className="text-blue-400" />
                <span className="text-sm text-gray-200">{c.g1} vs {c.g2}</span>
                {c.has_visualizations && (
                  <span className="ml-auto text-xs text-green-400">Visualizations available</span>
                )}
              </div>
            ))}
          </div>

          {/* Comparison result tabs */}
          {selectedComparison && (
            <>
              <div className="flex gap-1 mb-4 bg-gray-900 border border-gray-800 rounded-lg p-1 w-fit">
                {ops.map(op => (
                  <button
                    key={op.key}
                    onClick={() => setActiveTab(op.key)}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                      activeTab === op.key
                        ? op.key === 'contradictions'
                          ? 'bg-red-500/20 text-red-400'
                          : 'bg-blue-500/20 text-blue-400'
                        : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                    }`}
                  >
                    {op.symbol} {op.label}
                  </button>
                ))}
              </div>
              <GraphEmbed
                src={getComparisonVizUrl(selectedComparison, activeTab, provider, theme)}
                title={`${selectedComparison} — ${activeTab}`}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}
