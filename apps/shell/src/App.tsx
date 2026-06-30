import { Suspense, lazy } from 'react';
import { Routes, Route } from 'react-router-dom';
import Sidebar from '@/components/Sidebar';
import CommandPalette from '@/components/CommandPalette';
import AssistantRuntimeProvider from '@/components/AssistantRuntimeProvider';
import ErrorBoundary from '@/components/ErrorBoundary';

// Route-level code splitting: each page (and its heavy deps — e.g. cytoscape on
// GraphComparison) loads only when first navigated to, keeping the initial
// bundle small and the first paint fast.
const Home = lazy(() => import('@/pages/Home'));
const Extraction = lazy(() => import('@/pages/Extraction'));
const Assistant = lazy(() => import('@/pages/Assistant'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const ImpactAnalysis = lazy(() => import('@/pages/ImpactAnalysis'));
const Obligations = lazy(() => import('@/pages/Obligations'));
const GraphComparison = lazy(() => import('@/pages/GraphComparison'));
const SuiteSettings = lazy(() => import('@/pages/SuiteSettings'));

function PageFallback() {
  return <div className="p-8 text-sm text-gray-500 page-enter">Loading…</div>;
}

export default function App() {
  return (
    <AssistantRuntimeProvider>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <Sidebar />
        <CommandPalette />
        <main className="ml-60 h-screen overflow-y-auto">
          <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<div className="p-8 page-enter"><Home /></div>} />
            <Route path="/extraction/compare" element={<GraphComparison />} />
            <Route path="/extraction/*" element={<Extraction />} />
            <Route path="/assistant/*" element={<Assistant />} />
            <Route path="/analytics" element={<div className="p-8 page-enter"><Analytics /></div>} />
            <Route path="/impact-analysis" element={<div className="p-8 page-enter"><ImpactAnalysis /></div>} />
            <Route path="/obligations" element={<div className="p-8 page-enter"><Obligations /></div>} />
            <Route path="/settings" element={<SuiteSettings />} />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </AssistantRuntimeProvider>
  );
}
