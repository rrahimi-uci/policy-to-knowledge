import { useEffect, useState, useRef } from 'react';
import { NavLink } from 'react-router-dom';
import { fetchRuns } from '../api';
import { useTheme } from '../hooks/useTheme';
import {
  LayoutDashboard,
  FileText,
  Play,
  Network,
  History,
  Settings,
  Sun,
  Moon,
} from 'lucide-react';

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/documents', icon: FileText, label: 'Domain Documents' },
  { to: '/pipeline', icon: Play, label: 'Knowledge Extraction Pipeline' },
  { to: '/explorer', icon: Network, label: 'Explorer' },
  { to: '/runs', icon: History, label: 'Run History' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Sidebar() {
  const { theme, toggleTheme } = useTheme();
  const [hasRunning, setHasRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    const check = () =>
      fetchRuns().then(res => {
        setHasRunning((res.runs || []).some((r: any) => r.status === 'running'));
      }).catch(() => {});
    check();
    pollRef.current = setInterval(check, 4000);
    return () => clearInterval(pollRef.current);
  }, []);
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-60 bg-gray-900 border-r border-gray-800 flex flex-col z-30">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-gray-800">
        <img src={`${import.meta.env.BASE_URL}logo.svg`} alt="Policy to Knowledge" className="h-[84px] w-auto" />
        <p className="text-[11px] text-gray-400 mt-3 leading-relaxed">
          <span className="font-bold text-blue-400">Policy to Knowledge:</span>{' '}
          <span className="font-bold underline decoration-blue-400 text-white">C</span>ompliance &amp;{' '}
          <span className="font-bold underline decoration-blue-400 text-white">O</span>perational{' '}
          <span className="font-bold underline decoration-blue-400 text-white">R</span>ules{' '}
          <span className="font-bold underline decoration-blue-400 text-white">T</span>ransformation and{' '}
          <span className="font-bold underline decoration-blue-400 text-white">E</span>
          <span className="font-bold underline decoration-blue-400 text-white">x</span>traction Service
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 overflow-y-auto">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-2.5 text-base transition-colors ${
                isActive
                  ? 'text-blue-400 bg-blue-500/10 border-r-2 border-blue-400'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
              }`
            }
          >
            <Icon size={20} />
            {label}
            {to === '/pipeline' && hasRunning && (
              <span className="ml-auto flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                </span>
                <span className="text-[10px] text-green-400 font-medium">Running</span>
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Theme toggle */}
      <div className="px-5 py-4 border-t border-gray-800">
        <button
          type="button"
          onClick={toggleTheme}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-base text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
        >
          {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
          {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
        </button>
      </div>
    </aside>
  );
}
