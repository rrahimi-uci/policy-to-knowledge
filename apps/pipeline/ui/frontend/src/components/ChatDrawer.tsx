import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageSquare, X, Send, Loader2, Sparkles, ChevronRight } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  /** Currently selected entity name — shown as a quick-ask chip */
  entityName?: string;
  /** Currently selected graph name — included as context in the prompt */
  graphName?: string;
}

/** Collapsible chat drawer that talks to the Assistant backend. */
export default function ChatDrawer({ entityName, graphName }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll on new content
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, currentStep]);

  // Focus input when drawer opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 150);
  }, [open]);

  // Abort any in-flight stream on unmount so the fetch reader is cancelled and
  // setState doesn't fire on an unmounted component.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Also abort when the drawer is closed mid-stream.
  useEffect(() => {
    if (!open) abortRef.current?.abort();
  }, [open]);

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    const userMsg: Message = { role: 'user', content: trimmed };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setStreaming(true);
    setCurrentStep(null);

    // Include the just-sent user message in history so the backend sees the full conversation
    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }));
    const contextPrefix = graphName ? `[Context: Knowledge graph "${graphName}"] ` : '';
    const body = {
      message: contextPrefix + trimmed,
      history,
    };

    let assistantContent = '';
    setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

    try {
      abortRef.current = new AbortController();
      const apiPrefix = (import.meta.env.VITE_API_BASE_PREFIX as string) ?? '';
      const res = await fetch(`${apiPrefix}/api/ca/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abortRef.current.signal,
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `${res.status}`);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            const eventType = line.slice(7).trim();
            // read next data line
            continue;
          }
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.content !== undefined) {
                // token event
                assistantContent += data.content;
                setMessages(prev => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
                  return updated;
                });
              }
              if (data.label !== undefined) {
                // step event
                setCurrentStep(data.status === 'done' ? null : data.label);
              }
              if (data.message !== undefined && !data.content) {
                // error event
                assistantContent += data.message;
                setMessages(prev => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
                  return updated;
                });
              }
            } catch { /* non-JSON line, skip */ }
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // Remove the empty assistant placeholder so aborted sends leave no ghost bubble
        setMessages(prev => prev.slice(0, -1));
        return;
      }
      assistantContent = assistantContent || `Error: ${err.message}`;
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
        return updated;
      });
    } finally {
      setStreaming(false);
      setCurrentStep(null);
      abortRef.current = null;
    }
  }, [messages, streaming, graphName]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const quickAsk = (question: string) => {
    setOpen(true);
    sendMessage(question);
  };

  return (
    <>
      {/* Floating toggle button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-indigo-600 to-cyan-600 text-white rounded-full shadow-lg hover:shadow-xl hover:scale-105 transition-all duration-200"
        >
          <MessageSquare size={18} />
          <span className="text-sm font-medium">Ask about this graph</span>
        </button>
      )}

      {/* Entity context chip — appears when entity selected and drawer closed */}
      {!open && entityName && (
        <button
          onClick={() => quickAsk(`Tell me about the entity "${entityName}" — what are its key rules, relationships, and significance in this knowledge graph?`)}
          className="fixed bottom-20 right-6 z-50 flex items-center gap-1.5 px-3 py-2 bg-purple-600/90 text-white rounded-full shadow-lg hover:bg-purple-500 transition-colors text-xs"
        >
          <Sparkles size={14} />
          Ask about {entityName}
          <ChevronRight size={14} />
        </button>
      )}

      {/* Drawer panel */}
      <div
        className={`fixed top-0 right-0 bottom-0 z-40 w-[420px] bg-gray-900 border-l border-gray-800 flex flex-col shadow-2xl transition-transform duration-300 ease-out ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center">
              <MessageSquare size={14} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-200">Knowledge Assistant</h3>
              {graphName && (
                <p className="text-[10px] text-gray-500">{graphName}</p>
              )}
            </div>
          </div>
          <button
            onClick={() => setOpen(false)}
            title="Close chat"
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Messages area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-12">
              <MessageSquare size={32} className="mx-auto text-gray-700 mb-3" />
              <p className="text-sm text-gray-500 mb-1">Ask anything about this knowledge graph</p>
              <p className="text-xs text-gray-600">Rules, entities, relationships, contradictions...</p>

              {/* Suggested questions */}
              <div className="mt-6 space-y-2">
                {[
                  'What are the most critical compliance rules?',
                  'Which entities have the most rules?',
                  entityName ? `Tell me about ${entityName}` : 'Summarize this knowledge graph',
                ].map((q, i) => (
                  <button
                    key={i}
                    onClick={() => sendMessage(q)}
                    className="block w-full text-left px-3 py-2 bg-gray-800/50 border border-gray-800 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:border-gray-700 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-blue-600/20 text-blue-100 border border-blue-500/20'
                    : 'bg-gray-800/60 text-gray-300 border border-gray-800'
                }`}
              >
                <div className="whitespace-pre-wrap break-words">{msg.content || '...'}</div>
              </div>
            </div>
          ))}

          {/* Streaming step indicator */}
          {currentStep && (
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Loader2 size={12} className="animate-spin" />
              {currentStep}
            </div>
          )}
        </div>

        {/* Entity context bar */}
        {entityName && (
          <div className="px-4 py-2 border-t border-gray-800 bg-purple-500/5">
            <button
              onClick={() => sendMessage(`Tell me about the entity "${entityName}" — what are its key rules, relationships, and significance?`)}
              className="flex items-center gap-1.5 text-xs text-purple-400 hover:text-purple-300 transition-colors"
            >
              <Sparkles size={12} />
              Ask about <span className="font-medium">{entityName}</span>
            </button>
          </div>
        )}

        {/* Input area */}
        <div className="p-3 border-t border-gray-800">
          <div className="flex items-end gap-2 bg-gray-800 rounded-xl border border-gray-700 px-3 py-2 focus-within:border-blue-500/50 transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about rules, entities, relationships..."
              rows={1}
              className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-600 resize-none outline-none max-h-24"
              style={{ minHeight: '20px' }}
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || streaming}
              className="p-1.5 rounded-lg text-blue-400 hover:bg-blue-500/10 disabled:text-gray-600 disabled:hover:bg-transparent transition-colors flex-shrink-0"
            >
              {streaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>
      </div>

      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  );
}
