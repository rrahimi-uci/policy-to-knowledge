import { useSettings } from '@/hooks/useSettings';

export default function SuiteSettings() {
  const { settings, updateSettings, resetSettings } = useSettings();

  return (
    <div className="p-8 page-enter max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Suite Settings</h1>

      <section className="mb-8 rounded-lg border border-gray-800 bg-gray-900/40 p-6">
        <h2 className="text-lg font-semibold mb-4">CopilotKit Runtime</h2>

        <label className="flex items-center gap-3 mb-4">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={settings.copilotKitEnabled}
            onChange={(e) =>
              updateSettings({ copilotKitEnabled: e.target.checked })
            }
          />
          <span>Enable CopilotKit integration</span>
        </label>

        <label className="block text-sm">
          <span className="block mb-1 text-gray-400">Runtime URL</span>
          <input
            type="text"
            className="w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-sm"
            value={settings.copilotKitUrl}
            onChange={(e) => updateSettings({ copilotKitUrl: e.target.value })}
          />
        </label>
      </section>

      <button
        type="button"
        onClick={resetSettings}
        className="rounded border border-gray-700 px-4 py-2 text-sm hover:bg-gray-800"
      >
        Reset to defaults
      </button>
    </div>
  );
}
