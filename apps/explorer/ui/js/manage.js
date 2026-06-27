/* ── Graph Management (Clean / Remove) ─────── */

function openManageModal() {
    const graphName = currentGraphName;
    if (!graphName || graphName === 'g') {
        showToast('No graph selected', ICONS.warning);
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'manage-overlay';
    overlay.id = 'manageOverlay';

    const displayName = currentGraphData?.display_name || graphName;

    overlay.innerHTML = `
        <div class="manage-modal" role="dialog" aria-modal="true" aria-label="Manage graph">
            <div class="manage-header">
                <h3>Manage Graph</h3>
                <span class="manage-graph-badge">${escapeHtml(displayName)}</span>
                <button class="manage-close" aria-label="Close" onclick="closeManageModal()">&times;</button>
            </div>
            <div class="manage-cards">
                <div class="manage-card">
                    <div class="manage-card-icon manage-card-icon--clean">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 2v6m0 4v6m0-16a4 4 0 0 1 0 8 4 4 0 0 1 0-8z"/>
                            <path d="M3 12h6m4 0h6"/>
                        </svg>
                    </div>
                    <div class="manage-card-body">
                        <h4>Clean Graph</h4>
                        <p>Remove all vertices, edges, and embeddings. The graph configuration is preserved and can be re-populated.</p>
                    </div>
                    <button class="manage-action-btn manage-action-btn--clean" id="manageCleanBtn"
                        onclick="handleCleanGraph()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                        Clean
                    </button>
                </div>
                <div class="manage-card manage-card--danger">
                    <div class="manage-card-icon manage-card-icon--remove">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="15" y1="9" x2="9" y2="15"/>
                            <line x1="9" y1="9" x2="15" y2="15"/>
                        </svg>
                    </div>
                    <div class="manage-card-body">
                        <h4>Remove Graph</h4>
                        <p>Permanently delete the graph, all data, embeddings, configuration, and associated files. <strong>This cannot be undone.</strong></p>
                    </div>
                    <button class="manage-action-btn manage-action-btn--remove" id="manageRemoveBtn"
                        onclick="handleRemoveGraph()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="15" y1="9" x2="9" y2="15"/>
                            <line x1="9" y1="9" x2="15" y2="15"/>
                        </svg>
                        Remove
                    </button>
                </div>
            </div>
        </div>`;

    overlay.addEventListener('click', e => { if (e.target === overlay) closeManageModal(); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') closeManageModal(); });
    document.body.appendChild(overlay);
}

function closeManageModal() {
    const overlay = document.getElementById('manageOverlay');
    if (overlay) overlay.remove();
}

async function handleCleanGraph() {
    const graphName = currentGraphName;
    const displayName = currentGraphData?.display_name || graphName;

    const confirmed = await confirmAction(
        `Are you sure you want to <strong>clean</strong> the graph <strong>${escapeHtml(displayName)}</strong>?<br><br>` +
        `All vertices, edges, and embeddings will be permanently removed. The graph configuration will be preserved.`,
        { danger: true, confirmText: 'Clean Graph', cancelText: 'Cancel' }
    );
    if (!confirmed) return;

    const btn = document.getElementById('manageCleanBtn');

    await withLoading(btn, async () => {
        const res = await fetch('/api/graph/clean', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_name: graphName }),
        });
        const data = await res.json();

        if (!res.ok) {
            showToast(data.errors?.[0] || 'Failed to clean graph', ICONS.error);
            return;
        }

        showToast(
            `Cleaned: ${data.vertices_dropped} vertices, ${data.embeddings_deleted} embeddings removed`,
            ICONS.success
        );
        closeManageModal();

        // Reload graph (will be empty now)
        try {
            const graphRes = await fetch(`/api/graph?graph_name=${encodeURIComponent(graphName)}`);
            if (graphRes.ok) {
                const graphData = await graphRes.json();
                if (graphData?.nodes?.length) {
                    renderGraph(graphData);
                } else {
                    // Graph is empty — clear the current visualization
                    currentGraphData = null;
                    if (gRoot) gRoot.selectAll('*').remove();
                    document.getElementById('nodeCount').textContent = '0';
                    document.getElementById('linkCount').textContent = '0';
                }
            }
        } catch (_) { /* best-effort refresh */ }
    });
}

async function handleRemoveGraph() {
    const graphName = currentGraphName;
    const displayName = currentGraphData?.display_name || graphName;

    // Step 1: First confirmation
    const confirmed = await confirmAction(
        `Are you sure you want to <strong>permanently remove</strong> the graph <strong>${escapeHtml(displayName)}</strong>?<br><br>` +
        `This will delete all data, embeddings, configuration files, and cannot be undone.`,
        { danger: true, confirmText: 'Continue', cancelText: 'Cancel' }
    );
    if (!confirmed) return;

    // Step 2: Type-to-confirm
    const typeConfirmed = await _typeToConfirm(graphName, displayName);
    if (!typeConfirmed) return;

    const btn = document.getElementById('manageRemoveBtn');

    // Resolve graph_key from the published list
    let graphKey = null;
    try {
        const pubRes = await fetch('/api/graph/published');
        if (pubRes.ok) {
            const pubData = await pubRes.json();
            const match = pubData.graphs?.find(g => g.traversal_source === graphName);
            if (match) graphKey = match.graph_key;
        }
    } catch (_) { /* continue */ }

    if (!graphKey) {
        showToast('Could not resolve graph key', ICONS.error);
        return;
    }

    await withLoading(btn, async () => {
        const res = await fetch(`/api/graph/${encodeURIComponent(graphKey)}`, {
            method: 'DELETE',
        });
        const data = await res.json();

        if (!res.ok) {
            showToast(data.errors?.[0] || 'Failed to remove graph', ICONS.error);
            return;
        }

        showToast(`Graph "${escapeHtml(displayName)}" removed`, ICONS.trash);
        closeManageModal();

        // Switch to another available graph
        try {
            const pubRes = await fetch('/api/graph/published');
            if (pubRes.ok) {
                const pubData = await pubRes.json();
                const remaining = pubData.graphs || [];
                if (remaining.length > 0) {
                    const next = remaining[0];
                    const graphRes = await fetch(`/api/graph?graph_name=${encodeURIComponent(next.traversal_source)}`);
                    if (graphRes.ok) {
                        const graphData = await graphRes.json();
                        renderGraph(graphData);
                    }
                } else {
                    // No graphs left — clear visualization
                    currentGraphData = null;
                    currentGraphName = 'g';
                    if (gRoot) gRoot.selectAll('*').remove();
                    document.getElementById('nodeCount').textContent = '0';
                    document.getElementById('linkCount').textContent = '0';
                    const gBadge = document.getElementById('graphNameBadge');
                    if (gBadge) gBadge.classList.remove('visible');
                }
            }
        } catch (_) { /* best-effort switch */ }
    });
}

/**
 * Type-to-confirm dialog: user must type the graph name to proceed.
 * @returns {Promise<boolean>}
 */
function _typeToConfirm(graphName, displayName) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        overlay.innerHTML = `
            <div class="confirm-dialog" role="alertdialog" aria-modal="true" aria-label="Type to confirm">
                <div class="confirm-message">
                    Type <strong>${escapeHtml(graphName)}</strong> to confirm removal of <strong>${escapeHtml(displayName)}</strong>:
                </div>
                <input class="manage-confirm-input" id="manageTypeConfirmInput"
                    type="text" autocomplete="off" spellcheck="false"
                    placeholder="${escapeAttr(graphName)}">
                <div class="confirm-actions">
                    <button class="confirm-btn cancel" data-action="cancel">Cancel</button>
                    <button class="confirm-btn danger" data-action="confirm" disabled id="manageTypeConfirmBtn">Remove Permanently</button>
                </div>
            </div>`;

        const close = (result) => { overlay.remove(); resolve(result); };

        const input = overlay.querySelector('#manageTypeConfirmInput');
        const confirmBtn = overlay.querySelector('#manageTypeConfirmBtn');

        input.addEventListener('input', () => {
            confirmBtn.disabled = input.value.trim() !== graphName;
        });

        overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => close(false));
        confirmBtn.addEventListener('click', () => {
            if (input.value.trim() === graphName) close(true);
        });
        overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
        overlay.addEventListener('keydown', e => { if (e.key === 'Escape') close(false); });

        document.body.appendChild(overlay);
        input.focus();
    });
}
