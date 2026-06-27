import type { ReactNode } from 'react';

/**
 * Placeholder wrapper reserved for optional assistant runtime integration.
 *
 * The runtime bindings are not wired up yet, so this is currently
 * a pure passthrough regardless of the Suite Settings toggle. It exists as a
 * single seam where the real provider can be mounted later without touching
 * every call site. When that happens, read `useSettings().assistantRuntimeEnabled`
 * here and conditionally mount the runtime.
 */
export default function AssistantRuntimeProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
