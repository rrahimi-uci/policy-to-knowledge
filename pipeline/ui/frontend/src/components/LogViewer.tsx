import { useRef, useEffect, useState, useMemo } from 'react';
import type { WsMessage } from '../hooks/useWebSocket';
import { Search, Copy, Check, Filter } from 'lucide-react';

const LEVELS = ['ALL', 'ERROR', 'WARN', 'INFO'] as const;

export default function LogViewer({ logs }: { logs: WsMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState('');
  const [levelFilter, setLevelFilter] = useState<string>('ALL');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs.length]);

  const logEntries = useMemo(() => logs.filter(l => l.type === 'log'), [logs]);

  const filtered = useMemo(() => {
    let result = logEntries;
    if (levelFilter !== 'ALL') result = result.filter(l => l.level === levelFilter);
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(l => l.message?.toLowerCase().includes(q));
    }
    return result;
  }, [logEntries, levelFilter, search]);

  const levelColor = (level?: string) => {
    switch (level) {
      case 'ERROR': return 'text-red-400';
      case 'WARN': return 'text-yellow-400';
      case 'INFO': return 'text-blue-300';
      default: return 'text-gray-400';
    }
  };

  const levelBadge = (level?: string) => {
    switch (level) {
      case 'ERROR': return 'bg-red-500/15 text-red-400';
      case 'WARN': return 'bg-yellow-500/15 text-yellow-400';
      case 'INFO': return 'bg-blue-500/15 text-blue-300';
      default: return 'bg-gray-800 text-gray-500';
    }
  };

  const handleCopy = () => {
    const text = filtered.map(l => `[${l.level || 'LOG'}] ${l.message}`).join('\n');
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const errorCount = logEntries.filter(l => l.level === 'ERROR').length;
  const warnCount = logEntries.filter(l => l.level === 'WARN').length;

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search logs..."
            className="w-full pl-8 pr-3 py-1.5 bg-gray-900 border border-gray-800 rounded-lg text-xs text-gray-300 focus:outline-none focus:border-blue-500/50"
          />
        </div>

        {/* Level filters */}
        <div className="flex items-center gap-1">
          <Filter size={12} className="text-gray-600 mr-0.5" />
          {LEVELS.map(lv => (
            <button
              key={lv}
              onClick={() => setLevelFilter(lv)}
              className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
                levelFilter === lv
                  ? lv === 'ERROR' ? 'bg-red-500/20 text-red-400'
                    : lv === 'WARN' ? 'bg-yellow-500/20 text-yellow-400'
                    : lv === 'INFO' ? 'bg-blue-500/20 text-blue-300'
                    : 'bg-gray-700 text-gray-200'
                  : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'
              }`}
            >
              {lv}
              {lv === 'ERROR' && errorCount > 0 && (
                <span className="ml-1 text-[9px]">({errorCount})</span>
              )}
              {lv === 'WARN' && warnCount > 0 && (
                <span className="ml-1 text-[9px]">({warnCount})</span>
              )}
            </button>
          ))}
        </div>

        {/* Copy */}
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          title="Copy logs to clipboard"
        >
          {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>

        {/* Count */}
        <span className="text-[10px] text-gray-600">
          {filtered.length === logEntries.length
            ? `${logEntries.length} lines`
            : `${filtered.length} / ${logEntries.length}`}
        </span>
      </div>

      {/* Log output */}
      <div className="bg-gray-950 border border-gray-800 rounded-lg max-h-72 overflow-y-auto p-3 font-mono text-xs leading-relaxed">
        {filtered.length === 0 && (
          <p className="text-gray-600 italic">
            {logEntries.length === 0 ? 'Waiting for output...' : 'No matching log entries'}
          </p>
        )}
        {filtered.map((l, i) => (
          <div key={i} className={`log-line flex items-start gap-2 ${levelColor(l.level)}`}>
            <span className={`shrink-0 px-1 py-0 rounded text-[9px] font-semibold ${levelBadge(l.level)}`}>
              {(l.level || 'LOG').padEnd(5)}
            </span>
            <span className="flex-1">{l.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
