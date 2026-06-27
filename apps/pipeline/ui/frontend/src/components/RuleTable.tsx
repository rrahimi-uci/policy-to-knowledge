import { useState, useMemo, useEffect, Fragment } from 'react';
import { Search, ChevronDown, ChevronUp, ChevronLeft, ChevronRight } from 'lucide-react';

interface Rule {
  rule_id?: string;
  title?: string;
  description?: string;
  rule_type?: string;
  confidence?: number;
  source_section?: string;
  entities?: string[];
  conditions?: any;
  [key: string]: any;
}

const PAGE_SIZES = [25, 50, 100];

export default function RuleTable({
  rules,
  typeColors,
  entityFilter,
  onEntityClick,
}: {
  rules: Rule[];
  typeColors?: Record<string, string>;
  entityFilter?: string;
  onEntityClick?: (entity: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [sortCol, setSortCol] = useState<string>('');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);

  const types = [...new Set(rules.map(r => r.rule_type?.toLowerCase() || 'unknown'))].sort();

  const filtered = useMemo(() => rules.filter(r => {
    const s = search.toLowerCase();
    const matchSearch =
      !s ||
      (r.title || '').toLowerCase().includes(s) ||
      (r.description || '').toLowerCase().includes(s) ||
      (r.rule_id || '').toLowerCase().includes(s);
    const matchType = !typeFilter || (r.rule_type || '').toLowerCase() === typeFilter;
    const matchEntity = !entityFilter || (r.entities || []).some(e => e.toLowerCase() === entityFilter.toLowerCase()) || (r as any).entity_source?.toLowerCase() === entityFilter.toLowerCase();
    return matchSearch && matchType && matchEntity;
  }), [rules, search, typeFilter, entityFilter]);

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (!sortCol) return 0;
    const av = (a as any)[sortCol] ?? '';
    const bv = (b as any)[sortCol] ?? '';
    const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv));
    return sortDir === 'asc' ? cmp : -cmp;
  }), [filtered, sortCol, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const pageStart = safePage * pageSize;
  const pageRows = sorted.slice(pageStart, pageStart + pageSize);

  // Reset to page 0 when filters change (including external entityFilter prop)
  const setSearchAndReset = (v: string) => { setSearch(v); setPage(0); };
  const setTypeAndReset = (v: string) => { setTypeFilter(v); setPage(0); };
  useEffect(() => { setPage(0); }, [entityFilter]);

  const toggleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortCol(col); setSortDir('asc'); }
  };

  const SortIcon = ({ col }: { col: string }) =>
    sortCol === col ? (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />) : null;

  const confidenceBar = (val: number | undefined) => {
    if (val == null) return <span className="text-gray-500">—</span>;
    const color =
      val >= 80 ? 'bg-green-500' : val >= 60 ? 'bg-amber-500' : 'bg-red-500';
    return (
      <div className="flex items-center gap-2">
        <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${val}%` }} />
        </div>
        <span className="text-xs text-gray-300 w-8">{val}%</span>
      </div>
    );
  };

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="relative flex-1 max-w-sm min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            value={search}
            onChange={(e) => setSearchAndReset(e.target.value)}
            placeholder="Search rules..."
            className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          />
        </div>
        {entityFilter && (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
            Entity: {entityFilter}
            <button onClick={() => onEntityClick?.('')} className="hover:text-white ml-0.5">&times;</button>
          </span>
        )}
        <div className="flex gap-1.5 flex-wrap">
          <button
            onClick={() => setTypeAndReset('')}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
              !typeFilter ? 'bg-blue-500 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            All ({rules.length})
          </button>
          {types.map(t => (
            <button
              key={t}
              onClick={() => setTypeAndReset(t === typeFilter ? '' : t)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                typeFilter === t ? 'text-white' : 'text-gray-400 hover:bg-gray-700'
              }`}
              style={{
                backgroundColor: typeFilter === t ? (typeColors?.[t] || '#3b82f6') : undefined,
                borderColor: typeColors?.[t],
                borderWidth: typeFilter !== t ? 1 : 0,
                borderStyle: 'solid',
              }}
            >
              {t} ({rules.filter(r => (r.rule_type || '').toLowerCase() === t).length})
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-gray-500 mb-2">
        {sorted.length === 0
          ? 'No rules match the current filters'
          : `Showing ${pageStart + 1}–${Math.min(pageStart + pageSize, sorted.length)} of ${sorted.length} rules`}
        {sorted.length > 0 && sorted.length !== rules.length && ` (filtered from ${rules.length})`}
      </p>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-800/60 text-gray-400 text-left text-xs uppercase tracking-wider">
              <th className="px-3 py-2.5 cursor-pointer" onClick={() => toggleSort('rule_id')}>
                ID <SortIcon col="rule_id" />
              </th>
              <th className="px-3 py-2.5 cursor-pointer" onClick={() => toggleSort('title')}>
                Rule <SortIcon col="title" />
              </th>
              <th className="px-3 py-2.5 cursor-pointer" onClick={() => toggleSort('rule_type')}>
                Type <SortIcon col="rule_type" />
              </th>
              <th className="px-3 py-2.5 cursor-pointer" onClick={() => toggleSort('confidence')}>
                Confidence <SortIcon col="confidence" />
              </th>
              <th className="px-3 py-2.5">Entities</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, idx) => {
              const id = r.rule_id || r.id || `rule-${pageStart + idx}`;
              const isOpen = expanded === id;
              return (
                <Fragment key={id}>
                  <tr
                    onClick={() => setExpanded(isOpen ? null : id)}
                    className="border-t border-gray-800/50 cursor-pointer hover:bg-gray-800/30 transition-colors"
                  >
                    <td className="px-3 py-2 font-mono text-gray-500 text-xs">{id}</td>
                    <td className="px-3 py-2 text-gray-200 max-w-md truncate">{r.title || r.description?.slice(0, 80)}</td>
                    <td className="px-3 py-2">
                      <span
                        className="px-2 py-0.5 rounded-full text-xs font-medium text-white"
                        style={{ backgroundColor: typeColors?.[(r.rule_type || '').toLowerCase()] || '#64748b' }}
                      >
                        {r.rule_type || 'unknown'}
                      </span>
                    </td>
                    <td className="px-3 py-2">{confidenceBar(r.confidence)}</td>
                    <td className="px-3 py-2 text-xs">
                      {(r.entities || []).slice(0, 3).map((e: string, i: number) => (
                        <button
                          key={e}
                          onClick={(ev) => { ev.stopPropagation(); onEntityClick?.(e); }}
                          className="text-blue-400 hover:text-blue-300 hover:underline mr-1"
                        >
                          {e}{i < Math.min((r.entities || []).length, 3) - 1 ? ',' : ''}
                        </button>
                      ))}
                      {(r.entities || []).length > 3 && (
                        <span className="text-gray-500"> +{r.entities!.length - 3}</span>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr key={`${id}-detail`} className="bg-gray-800/20">
                      <td colSpan={5} className="px-6 py-4">
                        <p className="text-gray-300 text-sm leading-relaxed mb-2">{r.description}</p>
                        {r.source_section && (
                          <p className="text-xs text-gray-500">Source: {r.source_section}</p>
                        )}
                        {r.conditions && (
                          <pre className="mt-2 text-xs text-gray-400 bg-gray-900 rounded p-2 overflow-x-auto">
                            {JSON.stringify(r.conditions, null, 2)}
                          </pre>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {sorted.length > PAGE_SIZES[0] && (
        <div className="flex items-center justify-between mt-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Rows per page:</span>
            {PAGE_SIZES.map(s => (
              <button
                key={s}
                onClick={() => { setPageSize(s); setPage(0); }}
                className={`px-2 py-0.5 rounded text-xs ${
                  pageSize === s ? 'bg-blue-500/20 text-blue-400' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={safePage === 0}
              title="Previous page"
              className="p-1 rounded hover:bg-gray-800 disabled:opacity-30"
            >
              <ChevronLeft size={16} className="text-gray-400" />
            </button>
            <span className="text-xs text-gray-400 px-2">
              Page {safePage + 1} of {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              title="Next page"
              className="p-1 rounded hover:bg-gray-800 disabled:opacity-30"
            >
              <ChevronRight size={16} className="text-gray-400" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
