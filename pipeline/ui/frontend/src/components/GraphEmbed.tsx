import { useEffect, useState } from 'react';
import { Loader2, AlertTriangle, RefreshCw } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';

export default function GraphEmbed({ src, title }: { src: string; title?: string }) {
  const { theme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [key, setKey] = useState(0);

  const retry = () => {
    setError(false);
    setLoading(true);
    setKey(k => k + 1);
  };

  // Match the app theme tokens (Midnight Studio / Warm Linen)
  const iframeBg = theme === 'light' ? '#f7f5f0' : '#0b0b18';

  // Re-key the iframe when src or theme changes so the report reloads
  // with the corresponding ?theme= query param.
  const iframeKey = `${src}::${theme}::${key}`;

  // Show the loading overlay whenever the iframe is about to refetch.
  useEffect(() => {
    setLoading(true);
    setError(false);
  }, [src, theme]);

  return (
    <div className="relative rounded-xl border border-gray-800 overflow-hidden bg-gray-950" style={{ height: '80vh', minHeight: '600px' }}>
      {/* Loading overlay */}
      {loading && !error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950 z-10">
          <Loader2 className="animate-spin text-blue-400 mb-3" size={32} />
          <p className="text-sm text-gray-400">Loading graph visualization…</p>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-950 z-10">
          <AlertTriangle className="text-amber-400 mb-3" size={32} />
          <p className="text-sm text-gray-300 mb-1">Failed to load graph visualization</p>
          <p className="text-xs text-gray-500 mb-4">The visualization server may be unavailable</p>
          <button
            onClick={retry}
            className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 rounded-lg text-sm text-gray-300 transition-colors"
          >
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      )}

      <iframe
        key={iframeKey}
        src={src}
        title={title || 'Knowledge Graph'}
        className="w-full h-full border-0"
        style={{ background: iframeBg }}
        sandbox="allow-scripts allow-same-origin"
        onLoad={() => setLoading(false)}
        onError={() => { setLoading(false); setError(true); }}
      />
    </div>
  );
}
