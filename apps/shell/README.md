# Suite Shell

The React + Vite **suite shell** — the single front door for Policy to Knowledge.
It renders the sidebar, command palette, and the native suite pages, and embeds
the other app UIs (extraction pipeline, knowledge-graph explorer, assistant) as
micro-frontends so the whole suite feels like one application.

Runs at `http://localhost:4000` under the `/app` base path.

## Start

From the repo root, `./start.sh` brings up the whole suite. To run just the
shell in development:

```bash
cd apps/shell
npm install
npm run dev          # http://localhost:4000/app/
```

The dev server proxies API/WebSocket traffic to the backing services so the
embedded apps work locally:

| Path | Proxied to | Service |
| --- | --- | --- |
| `/api/kg` | `http://localhost:8000/api` | pipeline FastAPI backend |
| `/api/ca` | `http://localhost:5000/app/api` | explorer (graph + chat) backend |
| `/api/assistant-runtime` | `http://localhost:4100/assistant-runtime` | assistant runtime |
| `/ws/kg` | `ws://localhost:8000/ws` | pipeline run/log stream |

Ports and origins are configurable via env vars (`SUITE_PORT`, `KG_BACKEND_PORT`,
`KG_FRONTEND_PORT`, `CA_PORT`, `ASSISTANT_RUNTIME_PORT`, `VITE_BASE_PATH`,
`VITE_CA_URL`, `VITE_KG_FRONTEND_URL`).

## How it embeds the other apps

Native suite pages (Home, Analytics, Impact Analysis, Obligations, Graph
Comparison) are React components. The extraction pipeline UI, the assistant, and
the embedded Settings page are loaded through `MicroFrame` (an `<iframe>`):
in production the suite-shell proxy serves them same-origin under `/app`; in
`vite dev` they point at each app's dev origin.

## Pages

| Route | Page | Source |
| --- | --- | --- |
| `/` | Home / suite landing | native React |
| `/analytics` | Cross-graph analytics | native React |
| `/impact-analysis` | Policy-change impact analysis | native React |
| `/obligations` | Obligation tracking | native React |
| `/extraction/compare` | Graph comparison (set operations) | native React |
| `/extraction/*` | Knowledge extraction pipeline UI | embedded (`MicroFrame`) |
| `/assistant/*` | Assistant | embedded (`MicroFrame`) |
| `/settings` | Suite settings (wraps the pipeline Settings page) | embedded (`MicroFrame`) |

## Structure

| Path | Purpose |
| --- | --- |
| `src/App.tsx` | Routes (lazy-loaded) + layout |
| `src/main.tsx` | App entry / router bootstrap |
| `src/components/` | `Sidebar`, `CommandPalette`, `MicroFrame`, `ErrorBoundary`, … |
| `src/pages/` | The native and embedded suite pages |
| `src/hooks/` | `useSettings`, `useTheme` |
| `src/bridge/messages.ts` | `postMessage` bridge to/from embedded iframes |
| `src/config.ts` | Base-path / origin resolution |

## Performance

Routes are **code-split** with `React.lazy` + `Suspense`, so each page (and its
dependencies) loads only when first visited. The Vite build also isolates the
framework (`react`, `react-dom`, `react-router-dom`) into its own long-lived
chunk that caches across deploys, keeping the initial paint small.

## Tests

```bash
npm test          # Vitest unit tests
npm run build     # type-check (tsc) + production build
npm run test:e2e  # Playwright E2E
```

Vitest and the production build run in the root CI workflow
(`.github/workflows/ci.yml`).
