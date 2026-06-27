import { useNavigate, useSearchParams } from 'react-router-dom';
import { useCallback } from 'react';

/**
 * Wraps useNavigate to preserve ?embedded=true across route changes.
 */
export function useEmbeddedNavigate() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const embedded = params.get('embedded') === 'true';

  return useCallback(
    (to: string, options?: { state?: unknown; replace?: boolean }) => {
      const url = embedded && !to.includes('embedded=')
        ? to + (to.includes('?') ? '&' : '?') + 'embedded=true'
        : to;
      navigate(url, options);
    },
    [navigate, embedded],
  );
}
