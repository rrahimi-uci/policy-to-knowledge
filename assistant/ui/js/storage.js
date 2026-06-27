/* ── Persistent Storage Helpers (SQLAlchemy backend) ─── */

const _DEFAULTS = { reviewed: null, reviewHistory: [], approved: null, approvalHistory: [], versionHistory: [], deleted: false, deletedAt: null, edits: {} };
const _EDGE_DEFAULTS = { edits: {}, approved: null, approvalHistory: [], versionHistory: [] };

// In-memory cache so reads are instant; writes always persist to server
const _nodeCache = {};

function getNodeData(nodeId) {
    if (_nodeCache[nodeId]) return structuredClone(_nodeCache[nodeId]);
    // Fallback to localStorage for backward compat during initial load
    try {
        const all = JSON.parse(localStorage.getItem('p2k-node-data') || '{}');
        if (all[nodeId]) { _nodeCache[nodeId] = all[nodeId]; return structuredClone(all[nodeId]); }
    } catch {}
    return structuredClone(_DEFAULTS);
}

function setNodeData(nodeId, data) {
    _nodeCache[nodeId] = structuredClone(data);
    // Also keep localStorage in sync as fallback
    try {
        const all = JSON.parse(localStorage.getItem('p2k-node-data') || '{}');
        all[nodeId] = data;
        localStorage.setItem('p2k-node-data', JSON.stringify(all));
    } catch {}
    // Persist to server asynchronously
    fetch(`/api/annotations/${encodeURIComponent(nodeId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    }).catch(err => {
        console.warn('Annotation save failed:', err);
        showToast('Failed to save annotation', ICONS.warning);
    });
}

/** Pre-load all annotations from server into cache at startup. */
async function loadAnnotationsFromServer() {
    try {
        const resp = await fetch('/api/annotations');
        if (!resp.ok) return;
        const all = await resp.json();
        for (const [id, data] of Object.entries(all)) {
            _nodeCache[id] = data;
        }
        // Merge into localStorage for offline fallback
        try {
            const existing = JSON.parse(localStorage.getItem('p2k-node-data') || '{}');
            Object.assign(existing, all);
            localStorage.setItem('p2k-node-data', JSON.stringify(existing));
        } catch {}
    } catch (err) {
        console.warn('Could not load annotations from server, using localStorage fallback:', err);
    }
}

function saveChatHistory() {
    try {
        const data = JSON.stringify(conversationHistory.slice(-50)); // cap at 50 messages
        if (data.length < 512000) localStorage.setItem('p2k-chat-history', data);
    } catch { /* ignore quota errors */ }
}

// ── Edge Annotation Helpers ─────────────────
function _edgeKey(edgeId) { return `edge:${edgeId}`; }

function getEdgeData(edgeId) {
    const key = _edgeKey(edgeId);
    if (_nodeCache[key]) return structuredClone(_nodeCache[key]);
    try {
        const all = JSON.parse(localStorage.getItem('p2k-edge-data') || '{}');
        if (all[edgeId]) { _nodeCache[key] = all[edgeId]; return structuredClone(all[edgeId]); }
    } catch {}
    return structuredClone(_EDGE_DEFAULTS);
}

function setEdgeData(edgeId, data) {
    const key = _edgeKey(edgeId);
    _nodeCache[key] = structuredClone(data);
    try {
        const all = JSON.parse(localStorage.getItem('p2k-edge-data') || '{}');
        all[edgeId] = data;
        localStorage.setItem('p2k-edge-data', JSON.stringify(all));
    } catch {}
    // Persist to server asynchronously
    fetch(`/api/annotations/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    }).catch(err => {
        console.warn('Edge annotation save failed:', err);
        showToast('Failed to save edge annotation', ICONS.warning);
    });
}
