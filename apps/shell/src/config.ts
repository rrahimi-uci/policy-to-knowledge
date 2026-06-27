// Normalize the base path to always have a leading slash and no trailing slash
// (e.g. "app" -> "/app", "/app/" -> "/app", "/" -> "").
export function normalizeBasePath(raw: string | undefined): string {
  const trimmed = (raw ?? 'app').trim()
  const noSlashes = trimmed.replace(/^\/+|\/+$/g, '')
  return noSlashes ? `/${noSlashes}` : ''
}

const basePath = normalizeBasePath(import.meta.env.VITE_BASE_PATH as string | undefined)

// Allow explicit overrides; otherwise derive from basePath
export const API_BASE = (import.meta.env.VITE_API_BASE as string) || `${basePath}/api`
export const WS_BASE  = (import.meta.env.VITE_WS_BASE  as string) || `${basePath}/ws`

export function apiUrl(path: string): string {
  const clean = path.startsWith('/') ? path.slice(1) : path
  return `${API_BASE}/${clean}`
}

export function wsUrl(path: string): string {
  const clean = path.startsWith('/') ? path.slice(1) : path
  // If WS_BASE is an absolute URL (explicit override, e.g. wss://api.host/ws),
  // use it directly instead of prefixing the current protocol+host.
  if (/^wss?:\/\//i.test(WS_BASE)) {
    return `${WS_BASE}/${clean}`
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${WS_BASE}/${clean}`
}
