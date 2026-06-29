import { useSettings } from '@/hooks/useSettings';
import MicroFrame from '@/components/MicroFrame';

// Build the embedded pipeline Settings URL the same way Extraction does:
// same-origin in prod (nginx proxies), the kg-frontend dev origin in `vite dev`.
const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
const KG_FRONTEND_ORIGIN = import.meta.env.DEV
  ? ((import.meta.env.VITE_KG_FRONTEND_URL as string | undefined) ?? 'http://localhost:5173')
  : '';
const PIPELINE_SETTINGS_SRC = `${KG_FRONTEND_ORIGIN}${BASE}/settings?embedded=true`;

export default function SuiteSettings() {
  const { settings, updateSettings, resetSettings } = useSettings();

  return (
    <div className="flex flex-col h-[calc(100vh-0px)] page-enter">
      <div className="p-8 pb-4">
        <h1 className="text-2xl font-bold mb-6">Settings</h1>

        {/* Suite-level settings (shell) */}
        <section className="mb-6 rounded-lg border border-gray-800 bg-gray-900/40 p-6 max-w-3xl">
          <h2 className="text-lg font-semibold mb-1">
            Assistant Runtime <span className="text-xs font-normal text-gray-500">· suite</span>
          </h2>
          <p className="text-xs text-gray-500 mb-4">Shell-level integration for the embedded assistant.</p>

          <label className="flex items-center gap-3 mb-4">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={settings.assistantRuntimeEnabled}
              onChange={(e) => updateSettings({ assistantRuntimeEnabled: e.target.checked })}
            />
            <span>Enable assistant runtime integration</span>
          </label>

          <label className="block text-sm mb-4">
            <span className="block mb-1 text-gray-400">Runtime URL</span>
            <input
              type="text"
              className="w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-sm"
              value={settings.assistantRuntimeUrl}
              onChange={(e) => updateSettings({ assistantRuntimeUrl: e.target.value })}
            />
          </label>

          <button
            type="button"
            onClick={resetSettings}
            className="rounded border border-gray-700 px-4 py-2 text-sm hover:bg-gray-800"
          >
            Reset suite defaults
          </button>
        </section>

        {/* Pipeline configuration (embedded from the pipeline UI; saved to config.json) */}
        <h2 className="text-lg font-semibold mb-1">Pipeline Configuration</h2>
        <p className="text-xs text-gray-500">
          LLM models, reasoning effort, chunk sizes, worker counts, temperatures and more —
          persisted to the pipeline&apos;s <code className="text-gray-400">config.json</code>.
        </p>
      </div>

      {/* The embedded pipeline Settings page (its own tabs + Save button). */}
      <div className="flex-1 min-h-[560px] border-t border-gray-800">
        <MicroFrame src={PIPELINE_SETTINGS_SRC} title="Pipeline Configuration" />
      </div>
    </div>
  );
}
