import { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import MicroFrame from '@/components/MicroFrame';

// Vite injects BASE_URL from `base` (always ends with '/'). Strip the trailing
// slash so we can concatenate cleanly with leading-slash sub-paths.
const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

// In production the suite-shell nginx proxies kg-frontend routes under the
// same base path, so we use a same-origin URL. In `vite dev` each app runs
// on its own port, so we point the iframe at the kg-frontend dev origin
// (overridable via VITE_KG_FRONTEND_URL — kept for backwards compatibility).
const KG_FRONTEND_ORIGIN = import.meta.env.DEV
  ? (import.meta.env.VITE_KG_FRONTEND_URL ?? 'http://localhost:5173')
  : '';

/**
 * Maps suite routes to embedded KG Extraction child routes.
 *   /extraction/documents  →  /app/documents?embedded=true (prod, same-origin)
 *                          →  http://localhost:5173/app/documents?embedded=true (dev)
 */
export default function Extraction() {
  const location = useLocation();

  const childPath = useMemo(() => {
    const sub = location.pathname.replace(/^\/extraction/, '') || '/';
    return `${KG_FRONTEND_ORIGIN}${BASE}${sub}?embedded=true`;
  }, [location.pathname]);

  return (
    <div className="h-[calc(100vh-0px)]">
      <MicroFrame src={childPath} title="Knowledge Extraction" />
    </div>
  );
}
