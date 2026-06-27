const basePath = (import.meta.env.VITE_BASE_PATH as string ?? '/app').replace(/\/$/, '')

// Allow explicit overrides; otherwise derive from basePath
export const API_BASE = (import.meta.env.VITE_API_BASE as string) || `${basePath}/api`
export const WS_BASE  = (import.meta.env.VITE_WS_BASE  as string) || `${basePath}/ws`

export function apiUrl(path: string): string {
  const clean = path.startsWith('/') ? path.slice(1) : path
  return `${API_BASE}/${clean}`
}

export function wsUrl(path: string): string {
  const clean = path.startsWith('/') ? path.slice(1) : path
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${WS_BASE}/${clean}`
}
