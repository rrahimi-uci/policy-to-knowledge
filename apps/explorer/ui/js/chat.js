/* ── Chat Functions ─────────────────────────── */
async function sendMessage() {
    const msg = chatInput.value.trim();
    if (!msg || isStreaming) return;
    isStreaming = true;
    chatInput.disabled = true;
    sendBtn.disabled = true;

    addMessage('user', msg);
    lastUserMessage = msg;
    conversationHistory.push({ role: 'user', content: msg });
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Create streaming assistant message
    const { wrap, toolZone, bubble } = createStreamingMessage();
    streamingNodeRefs = null;  // reset for new message

    try {
        const res = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: msg,
                history: conversationHistory,
                active_graph: (typeof currentGraphName !== 'undefined' && currentGraphName) ? currentGraphName : null,
            })
        });

        if (!res.ok) {
            let err = {};
            try {
                err = await res.json();
            } catch {
                err = { error: await res.text() || `Request failed with HTTP ${res.status}` };
            }
            bubble.innerHTML = '<span style="color:var(--rose)">\u26a0\ufe0f ' + escapeHtml(err.error || 'Something went wrong.') + '</span>'
                + '<button class="retry-btn" onclick="retryLastMessage(this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Retry</button>';
            finishStreaming(bubble, '');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || ''; // last incomplete part stays in buffer

            for (const part of parts) {
                if (!part.trim()) continue;
                const lines = part.split('\n');
                let eventType = 'message';
                let eventData = '';

                for (const line of lines) {
                    if (line.startsWith('event: ')) eventType = line.slice(7);
                    else if (line.startsWith('data: ')) eventData = line.slice(6);
                }

                if (!eventData) continue;
                let data;
                try { data = JSON.parse(eventData); } catch { continue; }

                switch (eventType) {
                    case 'step':
                        renderStep(toolZone, data);
                        break;
                    case 'thinking':
                        renderThinking(toolZone, data);
                        break;
                    case 'tool_call':
                        renderToolCall(toolZone, data);
                        break;
                    case 'tool_result':
                        renderToolResult(toolZone, data);
                        break;
                    case 'token':
                        fullText += data.content;
                        bubble.innerHTML = formatMarkdown(fullText);
                        bubble.classList.add('streaming-cursor');
                        autoScroll();
                        break;
                    case 'node_references':
                        streamingNodeRefs = data.references || {};
                        break;
                    case 'navigate':
                        handleNavigateEvent(data);
                        break;
                    case 'error':
                        bubble.innerHTML += '<br><span style="color:var(--rose)">\u26a0\ufe0f ' + escapeHtml(data.message) + '</span>';
                        break;
                    case 'done':
                        break;
                }
            }
        }

        finishStreaming(bubble, fullText);
        // Linkify rule names: merge server-provided refs with loaded graph data
        const mergedRefs = buildMergedNodeRefs(streamingNodeRefs);
        if (Object.keys(mergedRefs).length > 0) {
            linkifyBubble(bubble, mergedRefs);
        }

    } catch (err) {
        bubble.innerHTML = '<span style="color:var(--rose)">\u26a0\ufe0f Network error: ' + escapeHtml(err.message) + '</span>'
            + '<button class="retry-btn" onclick="retryLastMessage(this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Retry</button>';
        finishStreaming(bubble, '');
    }
}

function retryLastMessage(btn) {
    if (!lastUserMessage || isStreaming) return;
    // Remove the error message
    const errMsg = btn.closest('.message');
    if (errMsg) errMsg.remove();
    // Pop the last user entry from history (sendMessage will re-add)
    if (conversationHistory.length && conversationHistory[conversationHistory.length - 1].role === 'user') {
        conversationHistory.pop();
    }
    chatInput.value = lastUserMessage;
    sendMessage();
}

function finishStreaming(bubble, fullText) {
    bubble.classList.remove('streaming-cursor');
    if (fullText) {
        conversationHistory.push({ role: 'assistant', content: fullText });
        addCopyButton(bubble, fullText);
        saveChatHistory();
    }
    isStreaming = false;
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
}

function createStreamingMessage() {
    const wrap = document.createElement('div');
    wrap.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.innerHTML = `<img src="${_urlPrefix}/logo.png" alt="CA" onerror="this.outerHTML='<span style=&quot;font-size:0.75rem;font-weight:700;color:var(--accent-light)&quot;>CA</span>'">`;

    const body = document.createElement('div');
    body.className = 'msg-body';

    const sender = document.createElement('div');
    sender.className = 'msg-sender';
    sender.textContent = 'Policy to Knowledge Assistant';

    const toolZone = document.createElement('div');
    toolZone.className = 'tool-zone';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble streaming-cursor';

    const ts = document.createElement('div');
    ts.className = 'msg-timestamp';
    ts.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    body.appendChild(sender);
    body.appendChild(toolZone);
    body.appendChild(bubble);
    body.appendChild(ts);
    wrap.appendChild(avatar);
    wrap.appendChild(body);
    chatMsgs.appendChild(wrap);
    autoScroll();

    return { wrap, toolZone, bubble };
}

function addMessage(role, content) {
    const wrap = document.createElement('div');
    wrap.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    if (role === 'assistant') {
        avatar.innerHTML = `<img src="${_urlPrefix}/logo.png" alt="CA" onerror="this.outerHTML='<span style=&quot;font-size:0.75rem;font-weight:700;color:var(--accent-light)&quot;>CA</span>'">`;
    } else {
        avatar.textContent = 'You';
    }

    const body = document.createElement('div');
    body.className = 'msg-body';

    const sender = document.createElement('div');
    sender.className = 'msg-sender';
    sender.textContent = role === 'user' ? 'You' : 'Policy to Knowledge Assistant';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = formatMarkdown(content);

    const ts = document.createElement('div');
    ts.className = 'msg-timestamp';
    ts.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    body.appendChild(sender);
    body.appendChild(bubble);
    body.appendChild(ts);
    wrap.appendChild(avatar);
    wrap.appendChild(body);
    chatMsgs.appendChild(wrap);
    autoScroll();
}

// ── Process Visibility Rendering ─────────────
function renderStep(zone, data) {
    const label = data.label || data.message || 'Working';
    const status = data.status || 'active';
    const stepId = 'step-' + String(label).replace(/[^a-z0-9]/gi, '-').toLowerCase();
    let existing = zone.querySelector('#' + CSS.escape(stepId));

    if (existing) {
        // Update existing step status
        existing.className = 'process-step ' + status;
        const icon = existing.querySelector('.process-step-icon');
        if (status === 'done') {
            icon.textContent = '\u2713';
            icon.style.animation = 'none';
        }
    } else {
        const el = document.createElement('div');
        el.className = 'process-step ' + status;
        el.id = stepId;
        const iconChar = status === 'done' ? '\u2713' : '\u25F4';
        el.innerHTML = '<span class="process-step-icon">' + iconChar + '</span><span>' + escapeHtml(label) + '</span>';
        zone.appendChild(el);
    }
    autoScroll();
}

function renderThinking(zone, data) {
    const el = document.createElement('div');
    el.className = 'thinking-block';
    el.innerHTML =
        '<span class="thinking-block-icon">\uD83E\uDDE0</span>' +
        '<div class="thinking-block-content">' +
        '<span class="thinking-block-label">Plan:</span>' +
        escapeHtml(data.content) +
        '</div>';
    zone.appendChild(el);
    autoScroll();
}

// ── Tool Result Rendering ─────────────────────
function renderToolCall(zone, data) {
    const toolNames = {
        semantic_search: 'Semantic Search',
        text_search: 'Text Search',
        execute_gremlin: 'Gremlin Query',
        get_graph_data: 'Loading Graph',
        get_vertex_details: 'Vertex Details',
    };
    const el = document.createElement('div');
    el.className = 'tool-indicator';
    el.id = 'tc-' + Date.now();
    el.innerHTML = `<svg class="tool-indicator-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/></svg>
        <span>${toolNames[data.name] || data.name}${data.args?.query ? ': "' + escapeHtml(truncate(data.args.query, 40)) + '"' : ''}</span>`;
    zone.appendChild(el);
    autoScroll();
}

function renderToolResult(zone, data) {
    data = (data && data.result) ? data.result : (data || {});

    // Remove the last tool indicator spinner
    const indicators = zone.querySelectorAll('.tool-indicator:not(.done)');
    if (indicators.length) {
        const last = indicators[indicators.length - 1];
        last.classList.add('done');
        last.querySelector('.tool-indicator-icon').innerHTML = '\u2713';
        last.querySelector('.tool-indicator-icon').style.animation = 'none';
    }

    if (data.type === 'gremlin') {
        // Show Gremlin query block
        const block = document.createElement('div');
        block.className = 'gremlin-block';
        const queryText = data.query;
        block.innerHTML = `
            <div class="gremlin-header"><span>Gremlin Query</span><span style="display:flex;align-items:center;gap:6px"><button class="gremlin-copy-btn" onclick="copyGremlin(this)">Copy</button><span class="lang-tag">gremlin</span></span></div>
            <div class="gremlin-body">${escapeHtml(queryText)}</div>
            <div class="gremlin-results-count"><span>${data.count}</span> result${data.count !== 1 ? 's' : ''}</div>`;
        block.querySelector('.gremlin-copy-btn').dataset.query = queryText;
        zone.appendChild(block);
    }

    if (data.type === 'search' && data.nodes?.length) {
        const container = document.createElement('div');
        container.className = 'node-cards';
        for (const node of data.nodes.slice(0, 8)) {
            const card = document.createElement('div');
            card.className = 'node-card';
            const color = nodeColorByType(node.rule_type || node.label);
            card.innerHTML = `
                <div class="node-card-dot" style="background:${color}"></div>
                <div class="node-card-body">
                    <div class="node-card-name">${escapeHtml(node.name)}</div>
                    <div class="node-card-meta">
                        ${node.rule_type ? '<span class="tag">' + escapeHtml(node.rule_type) + '</span>' : ''}
                        ${node.similarity ? '<span>score: ' + node.similarity.toFixed(3) + '</span>' : ''}
                        ${node.label ? '<span>' + escapeHtml(node.label) + '</span>' : ''}
                    </div>
                    ${node.content ? '<div class="node-card-snippet">' + escapeHtml(truncate(node.content, 120)) + '</div>' : ''}
                </div>
                <div class="node-card-arrow">\u203a</div>`;
            card.setAttribute('tabindex', '0');
            card.setAttribute('role', 'button');
            card.addEventListener('click', () => handleNodeCardClick(node));
            card.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleNodeCardClick(node); }
            });
            container.appendChild(card);
        }
        zone.appendChild(container);
    }

    if (data.type === 'graph') {
        if (data.data) {
            renderGraph(data.data);
        } else if (data.graph_name) {
            fetch(`/api/graph?graph_name=${encodeURIComponent(data.graph_name)}`)
                .then(res => res.ok ? res.json() : null)
                .then(graphData => { if (graphData) renderGraph(graphData); })
                .catch(() => {});
        }
    }

    if (data.type === 'vertex' && data.data) {
        renderVertexDetailCard(zone, data.data, data.graph_name || currentGraphName);
    }

    autoScroll();
}

function renderVertexDetailCard(zone, vdata, graphName) {
    graphName = graphName || currentGraphName;
    const props = vdata.properties || {};
    const name = props.name || vdata.id;
    const label = vdata.label || 'business_rule';
    const ruleType = props.rule_type || '';
    const color = nodeColorByType(ruleType || label);
    const content = props.content || props.description || '';
    const deps = vdata.depends_on || [];
    const depBy = vdata.depended_by || [];

    const card = document.createElement('div');
    card.className = 'vertex-detail-card';

    // Header
    let headerHTML = `
        <div class="vertex-detail-header">
            <div class="vertex-detail-header-left">
                <div class="vertex-detail-dot" style="background:${color}"></div>
                <div class="vertex-detail-name">${escapeHtml(name)}</div>
                ${ruleType ? '<span class="vertex-detail-badge">' + escapeHtml(ruleType) + '</span>' : ''}
                ${label === 'entity_category' ? '<span class="vertex-detail-badge">category</span>' : ''}
            </div>
            <button class="vertex-detail-show-btn" data-vid="${escapeHtml(vdata.id)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
                Show on Graph
            </button>
        </div>`;

    // Body - key properties
    let bodyHTML = '<div class="vertex-detail-body">';
    const showProps = ['category', 'rule_id', 'entity_or_relationship', 'reference', 'confidence_score', 'mandatory', 'requires_review'];
    const visibleProps = showProps.filter(k => props[k] !== undefined && props[k] !== '' && props[k] !== null);

    if (visibleProps.length) {
        bodyHTML += '<div class="vertex-detail-props">';
        for (const k of visibleProps) {
            const val = props[k];
            const display = typeof val === 'boolean'
                ? (val ? '<span style="color:var(--amber)">Yes</span>' : 'No')
                : escapeHtml(String(val));
            bodyHTML += `<div class="pk">${escapeHtml(k.replace(/_/g, ' '))}</div><div class="pv">${display}</div>`;
        }
        bodyHTML += '</div>';
    }

    // Content snippet
    if (content) {
        bodyHTML += `<div class="vertex-detail-content">${escapeHtml(truncate(content, 300))}</div>`;
    }

    // Dependencies summary
    if (deps.length || depBy.length) {
        bodyHTML += '<div class="vertex-detail-deps">';
        for (const d of deps.slice(0, 5)) {
            bodyHTML += `<span class="vertex-dep-chip"><span class="dep-arrow">\u2192</span> ${escapeHtml(truncate(d.target_name || '', 30))} <span class="dep-type">${escapeHtml(d.dependency_type || '')}</span></span>`;
        }
        for (const d of depBy.slice(0, 5)) {
            bodyHTML += `<span class="vertex-dep-chip"><span class="dep-arrow">\u2190</span> ${escapeHtml(truncate(d.source_name || '', 30))} <span class="dep-type">${escapeHtml(d.dependency_type || '')}</span></span>`;
        }
        if (deps.length + depBy.length > 10) {
            bodyHTML += `<span class="vertex-dep-chip" style="color:var(--text-muted)">+${deps.length + depBy.length - 10} more</span>`;
        }
        bodyHTML += '</div>';
    }

    bodyHTML += '</div>';
    card.innerHTML = headerHTML + bodyHTML;

    // Bind the "Show on Graph" button
    const showBtn = card.querySelector('.vertex-detail-show-btn');
    showBtn.addEventListener('click', () => {
        handleNavigateEvent({ id: vdata.id, name: name, label: label, graph_name: graphName });
    });

    zone.appendChild(card);
    autoScroll();
}

async function handleNavigateEvent(data) {
    const nodeId = String(data.id);
    if (!nodeId) return;

    const targetGraph = data.graph_name || currentGraphName;

    // If the correct graph is already loaded and has this node, navigate directly
    if (currentGraphData && currentGraphName === targetGraph) {
        const graphNode = currentGraphData.nodes.find(n => n.id === nodeId);
        if (graphNode) {
            navigateToNode(nodeId);
            return;
        }
    }

    // Graph not loaded or wrong graph — load the correct graph first, then navigate
    try {
        const _url = targetGraph
            ? `/api/graph?graph_name=${encodeURIComponent(targetGraph)}`
            : '/api/graph';
        const res = await fetch(_url);
        if (!res.ok) throw new Error('Failed to load graph');
        const graphData = await res.json();
        renderGraph(graphData);

        // Wait for simulation to settle a bit, then navigate
        setTimeout(() => {
            navigateToNode(nodeId);
        }, 2000);
    } catch (err) {
        // Fallback: open detail panel directly
        const panel = document.getElementById('detailPanel');
        const body = document.getElementById('detailBody');
        const title = document.getElementById('detailTitle');
        const badge = document.getElementById('detailBadge');

        title.textContent = data.name || nodeId;
        badge.textContent = data.label || 'rule';
        badge.className = 'detail-label-badge badge-rule';
        body.innerHTML = showDetailSkeleton();
        panel.classList.add('open');

        try {
            const detailRes = await fetch(`/api/vertex/${nodeId}?graph_name=${currentGraphName}`);
            const info = await detailRes.json();
            if (!detailRes.ok) throw new Error(info.error || 'Failed to load');
            renderDetail(info);
        } catch (e) {
            body.innerHTML = `<div style="color:var(--rose);text-align:center;padding:2rem">Error: ${escapeHtml(e.message)}</div>`;
        }
    }
}

async function handleNodeCardClick(node) {
    const nodeId = node.id;
    if (!nodeId) return;

    // Determine the graph this node belongs to
    const nodeGraph = node.graph_name || currentGraphName;

    // If the correct graph is already loaded and contains this node, zoom to it directly
    if (currentGraphData && currentGraphName === nodeGraph) {
        const graphNode = currentGraphData.nodes.find(n => n.id === String(nodeId));
        if (graphNode) {
            navigateToNode(nodeId);
            return;
        }
    }

    // Graph not loaded — load it, open detail panel, then navigate
    const panel = document.getElementById('detailPanel');
    const body = document.getElementById('detailBody');
    const title = document.getElementById('detailTitle');
    const badge = document.getElementById('detailBadge');

    title.textContent = node.name || node.id;
    badge.textContent = node.label || 'rule';
    badge.className = 'detail-label-badge ' +
        (node.label === 'entity_category' ? 'badge-category' : 'badge-rule');

    body.innerHTML = showDetailSkeleton();
    panel.classList.add('open');

    // Fetch detail immediately from the correct graph
    try {
        const res = await fetch(`/api/vertex/${nodeId}?graph_name=${encodeURIComponent(nodeGraph)}`);
        const info = await res.json();
        if (!res.ok) throw new Error(info.error || 'Failed to load');
        renderDetail(info);
    } catch (err) {
        body.innerHTML = `<div style="color:var(--rose);text-align:center;padding:2rem">Error: ${escapeHtml(err.message)}</div>`;
    }

    // Also load graph in background and navigate once ready
    if (currentGraphName !== nodeGraph || !currentGraphData) {
        try {
            const _graphUrl = nodeGraph
                ? `/api/graph?graph_name=${encodeURIComponent(nodeGraph)}`
                : '/api/graph';
            const graphRes = await fetch(_graphUrl);
            if (graphRes.ok) {
                const graphData = await graphRes.json();
                renderGraph(graphData);
                setTimeout(() => navigateToNode(nodeId), 2400);
            }
        } catch (e) { /* graph load failed — detail panel is already showing */ }
    }
}

// ── Build Merged Node Refs (server refs + loaded graph) ──
function buildMergedNodeRefs(serverRefs) {
    const merged = Object.assign({}, serverRefs || {});

    // Also include every node from the currently-loaded graph so that any
    // rule name the LLM mentions in prose gets a clickable link — even if
    // the server didn't return that name in the node_references event.
    if (currentGraphData && currentGraphData.nodes) {
        for (const node of currentGraphData.nodes) {
            const name = node.name || (node.properties && node.properties.name);
            if (name && !merged[name]) {
                merged[name] = {
                    id: String(node.id),
                    name: name,
                    label: node.label || node.type || '',
                };
            }
        }
    }
    return merged;
}

// ── Linkify Node References in Chat Bubbles ──
function linkifyBubble(bubble, nodeRefs) {
    if (!nodeRefs || Object.keys(nodeRefs).length === 0) return;

    // Filter out very short names (<=3 chars) to avoid false-positive highlights
    // Sort remaining names by length descending to match longest first
    const names = Object.keys(nodeRefs)
        .filter(n => n.length > 3)
        .sort((a, b) => b.length - a.length);
    if (names.length === 0) return;

    // Build a case-insensitive regex; node names may appear with different casing
    const escapedNames = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const pattern = new RegExp('(' + escapedNames.join('|') + ')', 'gi');

    // Build a quick lowercase-name → original-key map for case-insensitive lookup
    const lcMap = {};
    for (const n of names) { lcMap[n.toLowerCase()] = n; }

    // Walk all text nodes in the bubble
    const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT, null, false);
    const textNodes = [];
    while (walker.nextNode()) {
        textNodes.push(walker.currentNode);
    }

    for (const textNode of textNodes) {
        const text = textNode.textContent;
        if (!pattern.test(text)) continue;
        pattern.lastIndex = 0;

        // Skip text inside code, pre, anchor, or already-linked elements
        const parent = textNode.parentElement;
        if (!parent) continue;
        const tag = parent.tagName;
        if (tag === 'CODE' || tag === 'PRE' || tag === 'A' ||
            parent.classList.contains('node-ref-link')) continue;

        // Split text and wrap matches with clickable spans
        const fragment = document.createDocumentFragment();
        let lastIndex = 0;
        let match;
        pattern.lastIndex = 0;

        while ((match = pattern.exec(text)) !== null) {
            // Text before the match
            if (match.index > lastIndex) {
                fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
            }
            // Resolve the ref via case-insensitive lookup
            const key = lcMap[match[1].toLowerCase()] || match[1];
            const ref = nodeRefs[key];
            if (!ref) { lastIndex = pattern.lastIndex; continue; }
            const link = document.createElement('span');
            link.className = 'node-ref-link';
            link.textContent = match[1];
            link.dataset.nodeId = ref.id;
            link.dataset.nodeName = ref.name;
            link.dataset.nodeLabel = ref.label || '';
            link.title = 'Click to show on graph';
            link.setAttribute('tabindex', '0');
            link.setAttribute('role', 'link');
            link.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                handleNavigateEvent({ id: ref.id, name: ref.name, label: ref.label });
            });
            link.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); handleNavigateEvent({ id: ref.id, name: ref.name, label: ref.label }); }
            });
            fragment.appendChild(link);
            lastIndex = pattern.lastIndex;
        }

        // Remaining text after last match
        if (lastIndex < text.length) {
            fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
        }

        textNode.parentNode.replaceChild(fragment, textNode);
    }
}

function quickQuery(q) { chatInput.value = q; sendMessage(); }

// ── Export Conversation ─────────────────────
function exportConversation() {
    if (!conversationHistory.length) {
        showToast('No conversation to export', ICONS.info);
        return;
    }
    // Build Markdown
    const lines = [
        '# Assistant — Conversation Export',
        '',
        `**Exported:** ${new Date().toLocaleString()}`,
        `**Messages:** ${conversationHistory.length}`,
        '',
        '---',
        '',
    ];
    for (const entry of conversationHistory) {
        const role = entry.role === 'user' ? 'You' : 'Assistant';
        lines.push(`### ${role}`);
        lines.push('');
        lines.push(entry.content);
        lines.push('');
        lines.push('---');
        lines.push('');
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `p2k-conversation-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
    showToast('Conversation exported as Markdown', ICONS.download);
}

// ── Clear Chat / New Conversation ───────────
function clearChat() {
    conversationHistory = [];
    navHistory = [];
    localStorage.removeItem('p2k-chat-history');
    const msgs = document.getElementById('chatMessages');
    const welcomeMsg = msgs.querySelector('.message.assistant');
    msgs.innerHTML = '';
    if (welcomeMsg) msgs.appendChild(welcomeMsg);
    showToast('New conversation started', ICONS.plus);
}
