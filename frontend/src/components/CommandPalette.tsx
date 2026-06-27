import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiUrl } from '@/config';
import {
  Search,
  Network,
  FileText,
  Activity,
  BarChart3,
  MessageSquare,
  Play,
  GitCompareArrows,
  Settings,
  Loader2,
  ArrowRight,
  Command,
  Shield,
  ClipboardList,
} from 'lucide-react';

/* ─── types ──────────────────────────────────────────────────── */

interface SearchResult {
  id: string;
  label: string;
  description: string;
  category: 'graph' | 'document' | 'run' | 'page';
  route: string;
  icon: typeof Network;
}

/* ─── static pages ───────────────────────────────────────────── */

const PAGES: SearchResult[] = [
  { id: 'p-dash', label: 'Dashboard', description: 'Home overview', category: 'page', route: '/', icon: Activity },
  { id: 'p-docs', label: 'Documents', description: 'Upload & manage source documents', category: 'page', route: '/extraction/documents', icon: FileText },
  { id: 'p-pipe', label: 'Pipeline', description: 'Run AI extraction pipeline', category: 'page', route: '/extraction/pipeline', icon: Play },
  { id: 'p-runs', label: 'Run History', description: 'View past extraction runs', category: 'page', route: '/extraction/runs', icon: Activity },
  { id: 'p-comp', label: 'Compare Graphs', description: 'Diff, union & intersect knowledge graphs', category: 'page', route: '/extraction/compare', icon: GitCompareArrows },
  { id: 'p-expl', label: 'Knowledge Graph Explorer', description: 'Interactive graph visualization', category: 'page', route: '/extraction/explorer', icon: Network },
  { id: 'p-asst', label: 'Chat & Explore', description: 'AI-powered knowledge assistant', category: 'page', route: '/assistant', icon: MessageSquare },
  { id: 'p-anal', label: 'Graph Analytics', description: 'Rule distributions & graph health', category: 'page', route: '/analytics', icon: BarChart3 },
  { id: 'p-impa', label: 'Impact Analysis', description: 'Regulatory change detection & impact scoring', category: 'page', route: '/impact-analysis', icon: Shield },
  { id: 'p-obli', label: 'Obligation Register', description: 'Compliance obligations & gap analysis', category: 'page', route: '/obligations', icon: ClipboardList },
  { id: 'p-sett', label: 'Settings', description: 'Provider & pipeline configuration', category: 'page', route: '/extraction/settings', icon: Settings },
];

/* ─── component ──────────────────────────────────────────────── */

export default function CommandPalette() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fetchRef = useRef(0);

  /* ── Cmd+K / Ctrl+K global shortcut ──────────── */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  /* ── Focus input when opened ──────────────────── */
  useEffect(() => {
    if (open) {
      setQuery('');
      setResults(PAGES);
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  /* ── Search logic ─────────────────────────────── */
  const search = useCallback(async (q: string) => {
    const gen = ++fetchRef.current;
    const term = q.trim().toLowerCase();

    if (!term) {
      setResults(PAGES);
      setActiveIdx(0);
      setLoading(false);
      return;
    }

    setLoading(true);

    // Always include matching pages
    const pageHits = PAGES.filter(
      (p) =>
        p.label.toLowerCase().includes(term) ||
        p.description.toLowerCase().includes(term)
    );

    // Fetch graphs + docs + runs in parallel
    const [graphRes, docRes, runRes] = await Promise.allSettled([
      fetch(apiUrl('kg/graphs')).then((r) => r.json()),
      fetch(apiUrl('kg/documents')).then((r) => r.json()),
      fetch(apiUrl('kg/runs?limit=20')).then((r) => r.json()),
    ]);

    if (gen !== fetchRef.current) return; // stale

    const items: SearchResult[] = [...pageHits];

    // Graphs
    if (graphRes.status === 'fulfilled') {
      const graphs: Array<{ name: string; provider: string; rules: number; entities: number }> =
        graphRes.value.graphs ?? [];
      graphs
        .filter((g) => g.name.toLowerCase().includes(term))
        .forEach((g) =>
          items.push({
            id: `g-${g.name}`,
            label: g.name.replace(/_/g, ' '),
            description: `${g.provider} · ${g.rules} rules · ${g.entities} entities`,
            category: 'graph',
            route: '/extraction/explorer',
            icon: Network,
          })
        );
    }

    // Documents
    if (docRes.status === 'fulfilled') {
      const dirs: Array<{ name: string; file_count: number }> =
        docRes.value.subdirectories ?? [];
      dirs
        .filter((d) => d.name.toLowerCase().includes(term))
        .forEach((d) =>
          items.push({
            id: `d-${d.name}`,
            label: d.name,
            description: `${d.file_count} file${d.file_count !== 1 ? 's' : ''}`,
            category: 'document',
            route: '/extraction/documents',
            icon: FileText,
          })
        );
    }

    // Runs
    if (runRes.status === 'fulfilled') {
      const runs: Array<{ id: string; domain: string; status: string; provider: string; documents: string[] }> =
        runRes.value.runs ?? [];
      runs
        .filter(
          (r) =>
            r.domain?.toLowerCase().includes(term) ||
            r.id?.toLowerCase().includes(term) ||
            r.documents?.some((doc: string) => doc.toLowerCase().includes(term))
        )
        .slice(0, 5)
        .forEach((r) =>
          items.push({
            id: `r-${r.id}`,
            label: `Run ${r.id.slice(0, 8)}`,
            description: `${r.domain} · ${r.status} · ${r.provider}`,
            category: 'run',
            route: '/extraction/runs',
            icon: Activity,
          })
        );
    }

    setResults(items);
    setActiveIdx(0);
    setLoading(false);
  }, []);

  /* ── Debounced search ─────────────────────────── */
  useEffect(() => {
    const t = setTimeout(() => search(query), 200);
    return () => clearTimeout(t);
  }, [query, search]);

  /* ── Keyboard nav ─────────────────────────────── */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && results[activeIdx]) {
      e.preventDefault();
      go(results[activeIdx].route);
    }
  };

  const go = (route: string) => {
    setOpen(false);
    navigate(route);
  };

  /* ── Scroll active into view ──────────────────── */
  useEffect(() => {
    const el = listRef.current?.children[activeIdx] as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx]);

  if (!open) return null;

  /* Group results by category */
  const grouped: Record<string, SearchResult[]> = {};
  results.forEach((r) => {
    (grouped[r.category] ??= []).push(r);
  });
  const categoryLabels: Record<string, string> = {
    page: 'Pages',
    graph: 'Knowledge Graphs',
    document: 'Documents',
    run: 'Pipeline Runs',
  };

  let flatIdx = 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 z-50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        role="presentation"
      />

      {/* Dialog */}
      <div className="fixed top-[15%] left-1/2 -translate-x-1/2 w-full max-w-xl z-50">
        <div className="rounded-xl border border-gray-700 bg-gray-900 shadow-2xl overflow-hidden">
          {/* Input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800">
            {loading ? (
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin shrink-0" />
            ) : (
              <Search className="w-4 h-4 text-gray-500 shrink-0" />
            )}
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search graphs, documents, runs, pages…"
              className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-600 outline-none"
            />
            <kbd className="hidden sm:inline-flex items-center gap-0.5 rounded border border-gray-700 bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-500">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div ref={listRef} className="max-h-80 overflow-y-auto py-1">
            {results.length === 0 && !loading ? (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-gray-500">No results for &ldquo;{query}&rdquo;</p>
              </div>
            ) : (
              Object.entries(grouped).map(([cat, items]) => {
                const catLabel = categoryLabels[cat] ?? cat;
                return (
                  <div key={cat}>
                    <div className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-600">
                      {catLabel}
                    </div>
                    {items.map((item) => {
                      const idx = flatIdx++;
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => go(item.route)}
                          onMouseEnter={() => setActiveIdx(idx)}
                          className={`flex items-center gap-3 w-full px-4 py-2.5 text-left transition-colors ${
                            idx === activeIdx
                              ? 'bg-blue-500/10 text-blue-400'
                              : 'text-gray-300 hover:bg-gray-800/50'
                          }`}
                        >
                          <Icon className="w-4 h-4 shrink-0 opacity-60" />
                          <div className="flex-1 min-w-0">
                            <span className="text-sm">{item.label}</span>
                            <span className="text-xs text-gray-600 ml-2">{item.description}</span>
                          </div>
                          <ArrowRight className="w-3 h-3 opacity-30" />
                        </button>
                      );
                    })}
                  </div>
                );
              })
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-4 py-2 border-t border-gray-800 text-[10px] text-gray-600">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <kbd className="rounded border border-gray-700 bg-gray-800 px-1 py-0.5">↑↓</kbd> navigate
              </span>
              <span className="flex items-center gap-1">
                <kbd className="rounded border border-gray-700 bg-gray-800 px-1 py-0.5">↵</kbd> open
              </span>
              <span className="flex items-center gap-1">
                <kbd className="rounded border border-gray-700 bg-gray-800 px-1 py-0.5">esc</kbd> close
              </span>
            </div>
            <span className="flex items-center gap-1">
              <Command className="w-3 h-3" />K to toggle
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
