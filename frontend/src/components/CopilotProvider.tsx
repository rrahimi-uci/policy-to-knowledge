import type { ReactNode } from 'react';
import { useSettings } from '@/hooks/useSettings';

/**
 * Lightweight wrapper for CopilotKit integration. The actual `@copilotkit/*`
 * packages are loaded by the optional CopilotKit runtime (frontend/server).
 * When the runtime is disabled in Suite Settings, this is a pure passthrough.
 */
export default function CopilotProvider({ children }: { children: ReactNode }) {
  const { settings } = useSettings();

  if (!settings.copilotKitEnabled) {
    return <>{children}</>;
  }

  // CopilotKit runtime is opt-in. Until the React bindings are wired up,
  // we still render children so the suite remains usable when toggled on.
  return <>{children}</>;
}
