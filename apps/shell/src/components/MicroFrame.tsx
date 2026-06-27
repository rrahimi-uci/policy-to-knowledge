import { useRef, useEffect, useState } from 'react';
import { useTheme } from '@/hooks/useTheme';
import { syncThemeToFrame } from '@/bridge/messages';
import { Loader2, AlertTriangle } from 'lucide-react';

interface MicroFrameProps {
  src: string;
  title: string;
}

// How long to wait for an iframe to load before assuming the service is down.
// iframe `onError` does NOT fire for HTTP errors (404/500) or refused
// connections, so a watchdog timer is the only reliable failure signal.
const LOAD_TIMEOUT_MS = 12000;

export default function MicroFrame({ src, title }: MicroFrameProps) {
  const ref = useRef<HTMLIFrameElement>(null);
  const { theme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const initialSrc = useRef(src);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const armWatchdog = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setError(true);
      setLoading(false);
    }, LOAD_TIMEOUT_MS);
  };

  // When src changes after initial mount, navigate inside the iframe without
  // reloading it (avoids a full SPA restart on every sidebar click). Reset the
  // loading/error state and re-arm the watchdog for the new destination.
  useEffect(() => {
    if (src === initialSrc.current) return;
    setLoading(true);
    setError(false);
    armWatchdog();
    const win = ref.current?.contentWindow;
    if (win) {
      try {
        win.location.replace(src);
      } catch {
        // cross-origin fallback — update src attribute directly
        if (ref.current) ref.current.src = src;
      }
    }
  }, [src]);

  // Arm the watchdog for the initial load and clear it on unmount.
  useEffect(() => {
    armWatchdog();
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // sync theme whenever it changes
  useEffect(() => {
    if (!loading) syncThemeToFrame(ref.current, theme);
  }, [theme, loading]);

  const handleLoad = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setLoading(false);
    setError(false);
    syncThemeToFrame(ref.current, theme);
  };

  const handleError = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setLoading(false);
    setError(true);
  };

  return (
    <div className="relative w-full h-full">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 z-10">
          <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gray-950/90 z-10">
          <AlertTriangle className="h-10 w-10 text-amber-400" />
          <p className="text-sm text-gray-400">
            Failed to load <span className="text-gray-200">{title}</span>.
            Is the service running?
          </p>
          <button
            type="button"
            onClick={() => { setLoading(true); setError(false); ref.current?.contentWindow?.location.reload(); }}
            className="px-4 py-1.5 text-xs rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            Retry
          </button>
        </div>
      )}
      <iframe
        ref={ref}
        src={initialSrc.current}
        title={title}
        onLoad={handleLoad}
        onError={handleError}
        className="w-full h-full border-0"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
