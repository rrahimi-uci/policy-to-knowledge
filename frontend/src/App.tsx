import { Routes, Route } from 'react-router-dom';
import Sidebar from '@/components/Sidebar';
import CommandPalette from '@/components/CommandPalette';
import CopilotProvider from '@/components/CopilotProvider';
import Home from '@/pages/Home';
import Extraction from '@/pages/Extraction';
import Assistant from '@/pages/Assistant';
import Analytics from '@/pages/Analytics';
import ImpactAnalysis from '@/pages/ImpactAnalysis';
import Obligations from '@/pages/Obligations';
import GraphComparison from '@/pages/GraphComparison';
import SuiteSettings from '@/pages/SuiteSettings';

export default function App() {
  return (
    <CopilotProvider>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <Sidebar />
        <CommandPalette />
        <main className="ml-60 h-screen overflow-y-auto">
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
        </main>
      </div>
    </CopilotProvider>
  );
}
