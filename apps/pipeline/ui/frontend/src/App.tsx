import { Suspense, lazy } from 'react';
import { Routes, Route, useLocation, useSearchParams } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ErrorBoundary from './components/ErrorBoundary';

// Route-level code splitting: the landing Dashboard no longer pulls in the
// heavy graph (react-force-graph-2d → Explorer/Compare) or markdown/syntax
// highlighting (Documents) libraries — they load only when those routes open.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Documents = lazy(() => import('./pages/Documents'));
const Pipeline = lazy(() => import('./pages/Pipeline'));
const Explorer = lazy(() => import('./pages/Explorer'));
const Compare = lazy(() => import('./pages/Compare'));
const RunHistory = lazy(() => import('./pages/RunHistory'));
const Settings = lazy(() => import('./pages/Settings'));

function PageFallback() {
  return <div className="text-sm text-gray-500">Loading…</div>;
}

export default function App() {
  const location = useLocation();
  const [params] = useSearchParams();
  const embedded = params.get('embedded') === 'true' || window.self !== window.top;

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {!embedded && <Sidebar />}
      <main className={embedded ? 'p-6' : 'ml-60 p-8'}>
        <div key={location.pathname} className="page-enter">
          <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/explorer" element={<Explorer />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
