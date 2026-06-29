import MicroFrame from '@/components/MicroFrame';

// Build the embedded pipeline Settings URL the same way Extraction does:
// same-origin in prod (nginx proxies), the kg-frontend dev origin in `vite dev`.
const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
const KG_FRONTEND_ORIGIN = import.meta.env.DEV
  ? ((import.meta.env.VITE_KG_FRONTEND_URL as string | undefined) ?? 'http://localhost:5173')
  : '';
const PIPELINE_SETTINGS_SRC = `${KG_FRONTEND_ORIGIN}${BASE}/settings?embedded=true`;

export default function SuiteSettings() {
  return (
    <div className="flex flex-col h-[calc(100vh-0px)] page-enter">
      <div className="p-8 pb-4">
        <h1 className="text-2xl font-bold mb-1">Settings</h1>
        <p className="text-xs text-gray-500">
          LLM models, reasoning effort, chunk sizes, worker counts, temperatures and more —
          persisted to the pipeline&apos;s <code className="text-gray-400">config.json</code>.
        </p>
      </div>

      {/* The embedded pipeline Settings page (its own tabs + Save button). */}
      <div className="flex-1 min-h-[560px] border-t border-gray-800">
        <MicroFrame src={PIPELINE_SETTINGS_SRC} title="Settings" />
      </div>
    </div>
  );
}
