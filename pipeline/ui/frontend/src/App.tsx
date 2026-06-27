import { Routes, Route, useLocation, useSearchParams } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ErrorBoundary from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import Documents from './pages/Documents';
import Pipeline from './pages/Pipeline';
import Explorer from './pages/Explorer';
import Compare from './pages/Compare';
import RunHistory from './pages/RunHistory';
import Settings from './pages/Settings';

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
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/explorer" element={<Explorer />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/runs" element={<RunHistory />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
