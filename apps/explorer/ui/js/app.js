/* ── App Initialization ─────────────────────── */

// ── Resize Handle ────────────────────────────
(function initResizeHandle() {
    const handle = document.getElementById('resizeHandle');
    const chatPanel = document.querySelector('.chat-panel');
    if (!handle || !chatPanel) return;

    let startX, startW;

    function onMouseMove(e) {
        const newW = startW + (e.clientX - startX);
        const minW = parseInt(getComputedStyle(chatPanel).minWidth) || 320;
        const maxW = window.innerWidth * 0.7;
        chatPanel.style.width = Math.max(minW, Math.min(maxW, newW)) + 'px';
    }

    function onMouseUp() {
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        // Nudge the graph simulation to refit after resize
        if (typeof simulation !== 'undefined' && simulation) simulation.alpha(0.05).restart();
    }

    handle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startX = e.clientX;
        startW = chatPanel.offsetWidth;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
})();

// ── Configure marked.js ──────────────────────
(function initMarked() {
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false
        });
    }
})();

// ── Chat Input Listeners ─────────────────────
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
});
sendBtn.addEventListener('click', sendMessage);

// ── Auto-scroll lock ─────────────────────────
chatMsgs.addEventListener('scroll', () => {
    const atBottom = chatMsgs.scrollHeight - chatMsgs.scrollTop - chatMsgs.clientHeight < 40;
    userScrolledUp = !atBottom;
});

// ── Theme Toggle ──────────────────────────────
const themeToggle = document.getElementById('themeToggle');
const savedTheme = localStorage.getItem('p2k-theme');
if (savedTheme === 'light') document.body.classList.add('light-theme');
themeToggle.addEventListener('click', () => {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('p2k-theme', isLight ? 'light' : 'dark');
});

// ── Graph Node Search ───────────────────────
const graphSearchInput = document.getElementById('graphSearchInput');
const graphSearchClear = document.getElementById('graphSearchClear');

const _debouncedGraphFilter = debounce(() => {
    const query = graphSearchInput.value.trim().toLowerCase();
    if (!query || !svg || !currentGraphData) return;

    const matchIds = new Set();
    currentGraphData.nodes.forEach(n => {
        if ((n.name || '').toLowerCase().includes(query) ||
            (n.rule_type || '').toLowerCase().includes(query) ||
            (n.id || '').toLowerCase().includes(query)) {
            matchIds.add(n.id);
        }
    });

    d3.selectAll('.graph-node').classed('search-dim', d => !matchIds.has(d.id));
    d3.selectAll('.graph-node-label').classed('search-dim', d => !matchIds.has(d.id));
    d3.selectAll('.graph-link').classed('search-dim', d => {
        const sid = typeof d.source === 'object' ? d.source.id : d.source;
        const tid = typeof d.target === 'object' ? d.target.id : d.target;
        return !matchIds.has(sid) && !matchIds.has(tid);
    });

    // Show match count + empty state
    const countEl = document.getElementById('searchMatchCount');
    const emptyEl = document.getElementById('graphSearchEmpty');
    if (countEl) {
        countEl.textContent = matchIds.size + ' match' + (matchIds.size !== 1 ? 'es' : '');
        countEl.classList.add('visible');
    }
    if (emptyEl) {
        if (matchIds.size === 0) {
            emptyEl.innerHTML = 'No nodes matching <strong>"' + escapeHtml(query) + '"</strong>';
            emptyEl.classList.add('visible');
        } else {
            emptyEl.classList.remove('visible');
            emptyEl.innerHTML = '';
        }
    }
}, 150);

graphSearchInput.addEventListener('input', () => {
    const query = graphSearchInput.value.trim();
    if (!query) { clearGraphSearch(); return; }
    graphSearchClear.style.display = 'flex';
    _debouncedGraphFilter();
});

// ── Close detail on background click ────────
document.getElementById('graphContainer')?.addEventListener('click', e => {
    if (e.target.tagName === 'svg' || e.target.id === 'graphContainer') {
        closeDetail();
    }
});

chatInput.focus();

// ── Escape key closes detail panel ────────────
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        // Blur any focused input/textarea first
        if (document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')) {
            document.activeElement.blur();
        }
        // Close any open sub-panels first
        if (typeof closeSubPanel === 'function') closeSubPanel();
        if (typeof closeEdgeSubPanel === 'function') closeEdgeSubPanel();
        // Close all detail/create panels
        closeDetail();
        closeEdgeDetail();
        if (typeof closeCreatePanel === 'function') closeCreatePanel();
    }
});

// ── Keyboard Shortcuts ──────────────────────
document.addEventListener('keydown', e => {
    // / or Cmd+K → focus chat input
    if ((e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') ||
        (e.key === 'k' && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        chatInput.focus();
    }
    // Cmd+Shift+F → focus graph search
    if (e.key === 'f' && e.shiftKey && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        const gs = document.getElementById('graphSearchInput');
        if (gs) gs.focus();
    }
});

// ── Deep Linking ────────────────────────────
window.addEventListener('hashchange', handleHash);

// ── Connection Health-Check ──────────────────
(function healthCheck() {
    const badge = document.getElementById('statusBadge');
    if (!badge) return;
    async function ping() {
        try {
            const r = await fetch('/api/', { method: 'GET', signal: AbortSignal.timeout(5000) });
            if (r.ok) {
                badge.classList.remove('disconnected');
                badge.querySelector('.status-text').textContent = 'Connected';
            } else { throw new Error(); }
        } catch {
            badge.classList.add('disconnected');
            badge.querySelector('.status-text').textContent = 'Disconnected';
        }
    }
    ping();
    setInterval(ping, 20000);
})();

// ── Restore Chat History ─────────────────────
(function restoreChatHistory() {
    try {
        const saved = localStorage.getItem('p2k-chat-history');
        if (!saved) return;
        const history = JSON.parse(saved);
        if (!Array.isArray(history) || !history.length) return;
        conversationHistory = history;
        history.forEach(entry => addMessage(entry.role, entry.content));
    } catch { /* ignore parse errors */ }
})();

// ── Load persistent annotations from server ──
loadAnnotationsFromServer();

// Check deep link after initial graph load
setTimeout(handleHash, 1000);

// ── Embedded Mode (Policy to Knowledge integration) ──
(function initEmbeddedMode() {
    if (!new URLSearchParams(location.search).has('embedded')) return;

    // Hide header when embedded inside Policy to Knowledge shell
    const header = document.querySelector('header');
    if (header) header.style.display = 'none';

    // Add embedded class — CSS handles the chat-right layout
    document.body.classList.add('embedded');

    // Listen for theme-change messages from parent shell
    window.addEventListener('message', (e) => {
        if (e.data?.source === 'p2k-suite' && e.data?.type === 'theme-change') {
            const theme = e.data.payload?.theme;
            if (theme === 'light') {
                document.body.classList.add('light-theme');
            } else {
                document.body.classList.remove('light-theme');
            }
        }
    });

    // Auto-load graph specified by ?graph_name= param
    const defaultGraph = new URLSearchParams(location.search).get('graph_name');
    if (defaultGraph) {
        fetch(`/api/graph?graph_name=${encodeURIComponent(defaultGraph)}`)
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data) renderGraph(data); })
            .catch(() => {});
    }
})();
