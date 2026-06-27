import { useEffect, useState, useRef } from 'react';
import { fetchSettings, updateSettings } from '../api';
import { useToast } from '../components/Toast';
import { Loader2, Save, RotateCcw, Eye, EyeOff, HelpCircle } from 'lucide-react';

const FIELD_TIPS: Record<string, string> = {
  'pipeline.max_workers': 'Default parallel workers for the extraction pipeline. Override per-run on the Pipeline page.',
  'semantic_matcher.max_workers': 'Parallel workers used when matching rules during KG joining.',
  'join_graphs.max_workers': 'Parallel workers used by the graph-joining pipeline.',
  'join_graphs.batch_size': 'Rules processed per batch during graph joining.',
  'openai.api_key': 'Your OpenAI API key from platform.openai.com',
  'openai.models.reasoning': 'Model name for reasoning tasks (e.g., o3-mini)',
  'openai.models.reasoning_effort': 'How much effort the model should spend reasoning',
  'openai.rate_limiting.timeout': 'Max seconds to wait for a single API call',
  'openai.rate_limiting.max_retries': 'Number of automatic retries on rate-limit errors',

  'document_organizer.chunk_size_target': 'Target character count per document chunk',
  'document_organizer.max_chunk_size': 'Maximum allowed chunk size in characters',
  'document_organizer.min_chunk_size': 'Minimum chunk size — smaller chunks get merged',
  'entity_extractor.n_iterations': 'Number of meta-agent refinement loops',
  'entity_extractor.temperature': 'LLM temperature (0 = deterministic, 1 = creative)',
  'entity_extractor.min_score_threshold': 'Entities below this score are discarded',
  'rules_extractor.target_rules': 'Total number of rules to aim for',
  'rules_extractor.rules_per_batch_openai': 'Rules extracted per LLM call (OpenAI)',

  'rules_extractor.temperature': 'LLM temperature for rule extraction',
  'optimizer.dedup_temperature': 'Temperature for deduplication comparisons',
  'optimizer.dependency_temperature': 'Temperature for dependency analysis',
  'optimizer.batch_size': 'Number of rules processed per optimization batch',
};

export default function Settings() {
  const [cfg, setCfg] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<'providers' | 'pipeline'>('providers');
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState(false);
  const originalRef = useRef<string>('');
  const { toast } = useToast();

  useEffect(() => {
    fetchSettings()
      .then(data => {
        setCfg(data);
        originalRef.current = JSON.stringify(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateSettings(cfg);
      originalRef.current = JSON.stringify(cfg);
      setDirty(false);
      toast('success', 'Settings saved successfully');
    } catch {
      toast('error', 'Failed to save settings');
    }
    setSaving(false);
  };

  const handleReset = () => {
    setLoading(true);
    fetchSettings().then(data => {
      setCfg(data);
      originalRef.current = JSON.stringify(data);
      setDirty(false);
      setLoading(false);
      toast('info', 'Settings reset from server');
    });
  };

  const toggleKeyVisibility = (path: string) =>
    setShowKeys(prev => ({ ...prev, [path]: !prev[path] }));

  const update = (path: string, value: any) => {
    setCfg((prev: any) => {
      const next = JSON.parse(JSON.stringify(prev));
      const keys = path.split('.');
      let obj = next;
      for (let i = 0; i < keys.length - 1; i++) {
        if (!obj[keys[i]]) obj[keys[i]] = {};
        obj = obj[keys[i]];
      }
      obj[keys[keys.length - 1]] = value;
      setDirty(JSON.stringify(next) !== originalRef.current);
      return next;
    });
  };

  if (loading || !cfg) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-blue-400" size={32} /></div>;
  }

  const Field = ({ label, path, type = 'text', disabled = false, secret = false }: { label: string; path: string; type?: string; disabled?: boolean; secret?: boolean }) => {
    const keys = path.split('.');
    let val = cfg;
    for (const k of keys) val = val?.[k];
    const isVisible = showKeys[path];
    const tip = FIELD_TIPS[path];

    return (
      <div>
        <label className="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
          {label}
          {tip && (
            <span className="group relative">
              <HelpCircle size={12} className="text-gray-600 hover:text-gray-400 cursor-help" />
              <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2.5 py-1.5 bg-gray-700 border border-gray-600 text-gray-200 text-[11px] rounded-lg whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-10 shadow-lg">
                {tip}
              </span>
            </span>
          )}
        </label>
        <div className="relative">
          <input
            type={secret && !isVisible ? 'password' : type}
            title={label}
            aria-label={label}
            value={val ?? ''}
            onChange={(e) => update(path, type === 'number' ? Number(e.target.value) : e.target.value)}
            disabled={disabled}
            className={`w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 disabled:opacity-50 ${secret ? 'pr-10' : ''}`}
          />
          {secret && (
            <button
              type="button"
              onClick={() => toggleKeyVisibility(path)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              title={isVisible ? 'Hide' : 'Show'}
            >
              {isVisible ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Settings</h2>
        <div className="flex gap-2">
          <button
            onClick={handleReset}
            className="flex items-center gap-2 px-4 py-2 bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg hover:bg-gray-700"
          >
            <RotateCcw size={16} /> Reset
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg relative"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />} Save
            {dirty && (
              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-amber-400 rounded-full border-2 border-gray-950" />
            )}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 border border-gray-800 rounded-lg p-1 w-fit">
        {(['providers', 'pipeline'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-md text-sm font-medium capitalize transition-colors ${
              tab === t ? 'bg-blue-500/20 text-blue-400' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
            }`}
          >
            {t === 'providers' ? 'LLM Providers' : t}
          </button>
        ))}
      </div>

      {/* Providers Tab */}
      {tab === 'providers' && (
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">OpenAI</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="API Key" path="openai.api_key" secret />
              <Field label="Reasoning Model" path="openai.models.reasoning" />
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Reasoning Effort</label>
                <select
                  value={cfg.openai?.models?.reasoning_effort || 'medium'}
                  onChange={(e) => update('openai.models.reasoning_effort', e.target.value)}
                  title="OpenAI reasoning effort"
                  aria-label="OpenAI reasoning effort"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <Field label="Timeout (seconds)" path="openai.rate_limiting.timeout" type="number" />
              <Field label="Max Retries" path="openai.rate_limiting.max_retries" type="number" />
            </div>
          </div>


        </div>
      )}

      {/* Pipeline Tab */}
      {tab === 'pipeline' && (
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-1">Parallelism Defaults</h3>
            <p className="text-xs text-gray-500 mb-4">
              These are the default worker counts saved to <code className="text-gray-400">config.json</code>.
              You can override per-run on the <span className="text-blue-400">Pipeline</span> page.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Extraction Workers" path="pipeline.max_workers" type="number" />
              <Field label="Semantic Matcher Workers" path="semantic_matcher.max_workers" type="number" />
              <Field label="Join Pipeline Workers" path="join_graphs.max_workers" type="number" />
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Document Organization</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Chunk Size Target" path="document_organizer.chunk_size_target" type="number" />
              <Field label="Max Chunk Size" path="document_organizer.max_chunk_size" type="number" />
              <Field label="Min Chunk Size" path="document_organizer.min_chunk_size" type="number" />
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Entity Extraction</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Meta-Agent Iterations" path="entity_extractor.n_iterations" type="number" />
              <Field label="Temperature" path="entity_extractor.temperature" type="number" />
              <Field label="Min Score Threshold" path="entity_extractor.min_score_threshold" type="number" />
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Rules Extraction</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Target Rules" path="rules_extractor.target_rules" type="number" />
              <Field label="Batch Size (OpenAI)" path="rules_extractor.rules_per_batch_openai" type="number" />
              <Field label="Batch Size (Anthropic)" path="rules_extractor.rules_per_batch_anthropic" type="number" />
              <Field label="Temperature" path="rules_extractor.temperature" type="number" />
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Optimizer</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field label="Dedup Temperature" path="optimizer.dedup_temperature" type="number" />
              <Field label="Dependency Temperature" path="optimizer.dependency_temperature" type="number" />
              <Field label="Batch Size" path="optimizer.batch_size" type="number" />
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
