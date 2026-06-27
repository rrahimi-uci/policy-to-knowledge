import { useEffect, useState } from 'react';
import { fetchPromptDomains, fetchPrompt, savePrompt } from '../api';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Loader2, FileText, BookOpen, Copy, Check, Pencil, Save, X } from 'lucide-react';

const PROMPT_LABELS: Record<string, string> = {
  business_rules_extraction: 'Business Rules Extraction',
  dependency_analysis: 'Dependency Analysis',
  document_structure_analysis: 'Document Structure Analysis',
  entity_extraction: 'Entity Extraction',
  entity_refinement: 'Entity Refinement',
  entity_resolution: 'Entity Resolution',
  rule_deduplication: 'Rule Deduplication',
  rule_matcher: 'Rule Matcher',
  rule_matcher_batch: 'Rule Matcher (Batch)',
  rule_resolution: 'Rule Resolution',
  validation_report: 'Validation Report',
};

/** Convert the prompt's plain-text formatting to markdown for rendering. */
function toMarkdown(raw: string): string {
  let text = raw
    // Convert ════ section headers: line surrounded by ════ lines
    .replace(/═{4,}\n(.+)\n═{4,}/g, '\n## $1\n')
    // Convert ────── sub-headers
    .replace(/─{4,}\n(.+)\n─{4,}/g, '\n### $1\n')
    // Convert standalone ════ or ──── dividers left over
    .replace(/^[═─]{4,}$/gm, '\n---\n');

  // Unescape Python double-braces in existing ```json``` blocks
  text = text.replace(
    /```json\n([\s\S]*?)```/g,
    (_, inner) => '```json\n' + unescapeBraces(inner) + '```'
  );

  // Line-by-line processing: JSON block detection + text formatting
  const lines = text.split('\n');
  const result: string[] = [];
  let inCodeFence = false;
  let jsonBuf: string[] = [];
  let braceDepth = 0;

  const lastNonEmpty = () => {
    for (let j = result.length - 1; j >= 0; j--) {
      if (result[j].trim() !== '') return result[j];
    }
    return '';
  };
  const ensureBlankBefore = () => {
    if (result.length > 0 && result[result.length - 1].trim() !== '') result.push('');
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // Track code fences
    if (trimmed.startsWith('```')) {
      if (inCodeFence) {
        inCodeFence = false;
      } else {
        inCodeFence = true;
      }
      result.push(line);
      continue;
    }

    if (inCodeFence) {
      result.push(line);
      continue;
    }

    // --- JSON block detection ---
    if (jsonBuf.length === 0 && /^\{+$/.test(trimmed)) {
      jsonBuf.push(line);
      braceDepth = 1;
      continue;
    }

    if (jsonBuf.length > 0) {
      jsonBuf.push(line);
      for (const ch of trimmed) {
        if (ch === '{') braceDepth++;
        if (ch === '}') braceDepth--;
      }
      if (braceDepth <= 0) {
        const clean = unescapeBraces(jsonBuf.join('\n'));
        result.push('```json');
        result.push(clean);
        result.push('```');
        jsonBuf = [];
        braceDepth = 0;
      }
      continue;
    }

    // --- Text formatting ---

    // Blank lines pass through
    if (trimmed === '') {
      result.push('');
      continue;
    }

    // Standalone template variables → inline code block
    if (/^\{[a-z_]+\}$/.test(trimmed)) {
      ensureBlankBefore();
      result.push('`' + trimmed + '`');
      result.push('');
      continue;
    }

    // ALL-CAPS label with colon at end of meaningful text
    // e.g. "UPSTREAM INPUT (Agent 2):", "YOUR TASK (Agent 3):", "CRITICAL:"
    // But NOT lines that are numbered list items or already markdown
    if (
      /^[A-Z][A-Z\s,\-/&]+(\s*\([^)]*\)\s*)?:\s*$/.test(trimmed) &&
      !trimmed.startsWith('#')
    ) {
      ensureBlankBefore();
      result.push('**' + trimmed + '**');
      result.push('');
      continue;
    }

    // ALL-CAPS label followed by body text on same line
    // e.g. "CRITICAL: Every rule MUST be traceable..."
    const capsLabelMatch = trimmed.match(/^([A-Z][A-Z\s,\-/&]{2,}(?:\s*\([^)]*\))?):\s+(.+)$/);
    if (capsLabelMatch && !/^\d/.test(trimmed)) {
      ensureBlankBefore();
      result.push('**' + capsLabelMatch[1] + ':** ' + capsLabelMatch[2]);
      result.push('');
      continue;
    }

    // ✓ lines → markdown list items (- ✓)
    if (/^✓\s/.test(trimmed)) {
      // Ensure blank line before the first ✓ in a group
      if (!/^- ✓/.test(lastNonEmpty())) ensureBlankBefore();
      result.push('- ' + trimmed);
      continue;
    }

    // ✅ / ❌ lines → markdown list items
    if (/^[✅❌]\s/.test(trimmed)) {
      if (!/^- [✅❌]/.test(lastNonEmpty())) ensureBlankBefore();
      // Preserve indentation
      const indent = line.match(/^(\s*)/)?.[1] || '';
      result.push(indent + '- ' + trimmed);
      continue;
    }

    // Indented sub-item label (like "   ✅ USE SPECIFIC..." or "   ❌ AVOID...")
    if (/^\s+[✅❌✓]/.test(line)) {
      const indent = line.match(/^(\s*)/)?.[1] || '';
      result.push(indent + '- ' + trimmed);
      continue;
    }

    // Detection/Examples sub-labels within numbered lists
    // e.g. "   Detection: ..." or "   Examples:"
    if (/^\s+(Detection|Examples|Note|Warning|Important):\s*/.test(line)) {
      const indent = line.match(/^(\s*)/)?.[1] || '';
      const labelMatch = trimmed.match(/^(Detection|Examples|Note|Warning|Important):\s*(.*)$/);
      if (labelMatch) {
        result.push(indent + '**' + labelMatch[1] + ':** ' + (labelMatch[2] || ''));
        continue;
      }
    }

    // Default: pass through unchanged
    result.push(line);
  }

  // Flush any remaining JSON buffer
  if (jsonBuf.length > 0) {
    const clean = unescapeBraces(jsonBuf.join('\n'));
    result.push('```json');
    result.push(clean);
    result.push('```');
  }

  // Clean up excessive blank lines (max 2 consecutive)
  return result.join('\n').replace(/\n{4,}/g, '\n\n\n');
}

function unescapeBraces(s: string): string {
  // Handle any nesting depth: replace pairs from inside out
  let r = s;
  // 8-brace → single brace (covers {{{{{{{{ from dependency_analysis)
  r = r.replace(/\{\{\{\{\{\{\{\{/g, '{').replace(/\}\}\}\}\}\}\}\}/g, '}');
  // 4-brace → single brace
  r = r.replace(/\{\{\{\{/g, '{').replace(/\}\}\}\}/g, '}');
  // 2-brace → single brace
  r = r.replace(/\{\{/g, '{').replace(/\}\}/g, '}');
  return r;
}

export default function Prompts({ domain }: { domain: string }) {
  const [domains, setDomains] = useState<any[]>([]);
  const [defaultPrompts, setDefaultPrompts] = useState<string[]>([]);
  const [activeDomain, setActiveDomain] = useState(domain);
  const [activePrompt, setActivePrompt] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [promptMeta, setPromptMeta] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [loadingPrompt, setLoadingPrompt] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchPromptDomains()
      .then(res => {
        setDomains(res.domains || []);
        setDefaultPrompts(res.default?.prompts || []);
        const dm = res.domains?.find((d: any) => d.name === domain) || res.domains?.[0];
        if (dm) {
          setActiveDomain(dm.name);
          if (dm.prompts?.length > 0) {
            loadPrompt(dm.name, dm.prompts[0]);
          }
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const selectDomain = (dom: string) => {
    setActiveDomain(dom);
    setActivePrompt(null);
    setContent('');
    setPromptMeta(null);
    // Auto-load first prompt in the new domain
    const prompts = dom === 'default'
      ? defaultPrompts
      : domains.find(d => d.name === dom)?.prompts || [];
    if (prompts.length > 0) {
      loadPrompt(dom, prompts[0]);
    }
  };

  const loadPrompt = async (dom: string, name: string) => {
    setLoadingPrompt(true);
    setActivePrompt(name);
    setActiveDomain(dom);
    setEditing(false);
    try {
      const res = await fetchPrompt(dom, name);
      setContent(res.content);
      setPromptMeta(res);
    } catch {
      setContent('');
      setPromptMeta(null);
    }
    setLoadingPrompt(false);
  };

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const startEditing = () => {
    setEditContent(content);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditContent('');
  };

  const handleSave = async () => {
    if (!activePrompt) return;
    setSaving(true);
    try {
      await savePrompt(activeDomain, activePrompt, editContent);
      setContent(editContent);
      setEditing(false);
    } catch { /* ignore */ }
    setSaving(false);
  };

  const currentPrompts = activeDomain === 'default'
    ? defaultPrompts
    : domains.find(d => d.name === activeDomain)?.prompts || [];

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-blue-400" size={32} /></div>;
  }

  return (
    <div className="flex gap-6 h-[calc(100vh-6rem)]">
      {/* Left: Domain + Prompt list */}
      <div className="w-64 shrink-0 flex flex-col">
        <h2 className="text-2xl font-bold mb-4">Prompts</h2>

        {/* Domain tabs */}
        <div className="flex flex-wrap gap-1 mb-3">
          {domains.map(d => (
            <button
              key={d.name}
              onClick={() => selectDomain(d.name)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors capitalize ${
                activeDomain === d.name
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
              }`}
            >
              {d.name}
            </button>
          ))}
          <button
            onClick={() => selectDomain('default')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              activeDomain === 'default'
                ? 'bg-purple-500/20 text-purple-400'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
            }`}
          >
            Base
          </button>
        </div>

        {/* Prompt list */}
        <div className="flex-1 overflow-y-auto space-y-0.5 bg-gray-900 border border-gray-800 rounded-xl p-2">
          {currentPrompts.map((p: string) => (
            <button
              key={p}
              onClick={() => loadPrompt(activeDomain, p)}
              className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                activePrompt === p
                  ? 'bg-blue-500/10 text-blue-400'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
              }`}
            >
              <FileText size={14} className="shrink-0" />
              <span className="truncate">{PROMPT_LABELS[p] || p}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Right: Prompt preview */}
      <div className="flex-1 flex flex-col min-w-0">
        {activePrompt ? (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 mb-3">
              <BookOpen size={20} className="text-blue-400" />
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-gray-200">
                  {PROMPT_LABELS[activePrompt] || activePrompt}
                </h3>
                <p className="text-xs text-gray-500">
                  <span className="capitalize">{activeDomain}</span> &middot; {promptMeta?.lines || 0} lines &middot; {promptMeta?.size ? `${(promptMeta.size / 1024).toFixed(1)} KB` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-300 transition-colors"
                  title="Copy to clipboard"
                >
                  {copied ? <><Check size={13} className="text-green-400" /> Copied</> : <><Copy size={13} /> Copy</>}
                </button>
                {editing ? (
                  <>
                    <button
                      onClick={cancelEditing}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-300 transition-colors"
                    >
                      <X size={13} /> Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-xs text-white transition-colors"
                    >
                      {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                      Save
                    </button>
                  </>
                ) : (
                  <button
                    onClick={startEditing}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-300 transition-colors"
                    title="Edit prompt"
                  >
                    <Pencil size={13} /> Edit
                  </button>
                )}
              </div>
            </div>

            {/* Rendered content */}
            {loadingPrompt ? (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="animate-spin text-blue-400" size={24} />
              </div>
            ) : editing ? (
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                title="Edit prompt content"
                className="flex-1 w-full bg-gray-900 border border-gray-800 rounded-xl p-6 text-sm text-gray-200 font-mono leading-relaxed resize-none focus:outline-none focus:border-blue-500/50"
                spellCheck={false}
              />
            ) : (
              <div className="flex-1 overflow-y-auto bg-gray-900 border border-gray-800 rounded-xl p-6">
                <article className="prose prose-invert prose-sm max-w-none
                  prose-headings:text-blue-400 prose-headings:border-b prose-headings:border-gray-700/50 prose-headings:pb-2 prose-headings:mb-4
                  prose-h2:text-lg prose-h2:font-bold prose-h2:mt-8 prose-h2:first:mt-0
                  prose-h3:text-base prose-h3:font-semibold prose-h3:mt-5 prose-h3:border-none
                  prose-p:text-gray-300 prose-p:leading-relaxed prose-p:my-3
                  prose-strong:text-gray-100
                  prose-li:text-gray-300 prose-li:my-1
                  prose-ul:my-2 prose-ol:my-2
                  prose-code:text-blue-300 prose-code:bg-gray-800/70 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono
                  prose-pre:bg-gray-950 prose-pre:border prose-pre:border-gray-800 prose-pre:rounded-lg prose-pre:my-4
                  prose-hr:border-gray-700/40 prose-hr:my-6
                  prose-a:text-blue-400
                ">
                  <ReactMarkdown
                    components={{
                      code({ className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || '');
                        const code = String(children).replace(/\n$/, '');
                        if (match) {
                          return (
                            <SyntaxHighlighter
                              style={oneDark}
                              language={match[1]}
                              PreTag="div"
                              customStyle={{ margin: 0, borderRadius: '0.5rem', fontSize: '0.8rem' }}
                            >
                              {code}
                            </SyntaxHighlighter>
                          );
                        }
                        // Try auto-detecting JSON for un-tagged code blocks
                        const trimmed = code.trim();
                        if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
                          return (
                            <SyntaxHighlighter
                              style={oneDark}
                              language="json"
                              PreTag="div"
                              customStyle={{ margin: 0, borderRadius: '0.5rem', fontSize: '0.8rem' }}
                            >
                              {code}
                            </SyntaxHighlighter>
                          );
                        }
                        return <code className={className} {...props}>{children}</code>;
                      }
                    }}
                  >{toMarkdown(content)}</ReactMarkdown>
                </article>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <div className="text-center">
              <BookOpen size={40} className="mx-auto mb-3 text-gray-600" />
              <p className="text-sm">Select a prompt to preview</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
