import { NavLink, useLocation } from 'react-router-dom';
import { useTheme } from '@/hooks/useTheme';
import {
  LayoutDashboard,
  FileText,
  Play,
  Network,
  History,
  GitCompareArrows,
  MessageSquare,
  Settings,
  Sun,
  Moon,
  BarChart3,
  AlertTriangle,
  Shield,
  BrainCircuit,
  SearchCheck,
  PencilRuler,
  type LucideIcon,
} from 'lucide-react';

const sections: { heading: string | null; headingIcon?: LucideIcon; links: { to: string; icon: LucideIcon; label: string }[] }[] = [
  {
    heading: null,
    links: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    ],
  },
  {
    heading: 'KNOWLEDGE GRAPHS',
    headingIcon: BrainCircuit,
    links: [
      { to: '/extraction/documents', icon: FileText, label: 'Documents' },
      { to: '/extraction/pipeline', icon: Play, label: 'Pipeline' },
      { to: '/extraction/runs', icon: History, label: 'Run History' },
      { to: '/extraction/explorer', icon: Network, label: 'Knowledge Graph Explorer' },
      { to: '/extraction/compare', icon: GitCompareArrows, label: 'Compare Knowledge Graphs' },
    ],
  },
  {
    heading: 'COMPLIANCE INSIGHTS',
    headingIcon: SearchCheck,
    links: [
      { to: '/impact-analysis', icon: AlertTriangle, label: 'Impact Analysis' },
      { to: '/obligations', icon: Shield, label: 'Obligations' },
      { to: '/analytics', icon: BarChart3, label: 'Analytics' },
    ],
  },
  {
    heading: 'WORKSPACE',
    headingIcon: PencilRuler,
    links: [
      { to: '/assistant/chat', icon: MessageSquare, label: 'Assistant' },
    ],
  },
  {
    heading: null,
    links: [
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
];

export default function Sidebar() {
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-60 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      {/* Logo / Brand */}
      <div className="px-5 py-6 border-b border-gray-800">
        <div className="flex flex-col items-center gap-3 text-center">
          <img src={`${import.meta.env.BASE_URL}logo.svg`} alt="Policy to Knowledge" className="h-14 w-14 rounded-xl object-cover ring-2 ring-blue-500/20 shadow-lg shadow-blue-500/10" />
          <div>
            <h1 className="text-xl font-bold text-white tracking-wide">Policy to Knowledge</h1>
            <p className="text-[11px] text-gray-400 leading-snug mt-1">Compliance Knowledge Extraction,<br />Exploration, Editing &amp; Versioning</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 overflow-y-auto">
        {sections.map((section, si) => (
          <div key={si}>
            {section.heading && (
              <div className="mx-4 mt-5 mb-1 pt-4 border-t border-gray-800/60">
                <div className="flex items-center gap-1.5 px-1 text-[11px] font-bold uppercase tracking-[0.15em] text-blue-400/70">
                  {section.headingIcon && <section.headingIcon size={13} strokeWidth={2.5} />}
                  {section.heading}
                </div>
              </div>
            )}
            {section.links.map(({ to, icon: Icon, label }) => {
              const isActive =
                to === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(to);
              return (
                <NavLink
                  key={to}
                  to={to}
                  className={`flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${isActive
                      ? 'text-blue-400 bg-blue-500/10 border-r-2 border-blue-400'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
                    }`}
                >
                  <Icon size={18} />
                  {label}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Theme toggle */}
      <div className="px-5 py-4 border-t border-gray-800">
        <button
          type="button"
          onClick={toggleTheme}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
        </button>
      </div>
    </aside>
  );
}
