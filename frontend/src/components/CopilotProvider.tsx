import type { ReactNode } from 'react';

/**
 * Placeholder wrapper reserved for an optional CopilotKit integration.
 *
 * The `@copilotkit/*` React bindings are not wired up yet, so this is currently
 * a pure passthrough regardless of the Suite Settings toggle. It exists as a
 * single seam where the real provider can be mounted later without touching
 * every call site. When that happens, read `useSettings().copilotKitEnabled`
 * here and conditionally mount the runtime.
 */
export default function CopilotProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
