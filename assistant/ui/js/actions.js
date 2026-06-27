/* ── Action Button Handlers ─────────────────── */
function closeSubPanel() {
    const existing = document.getElementById('actionSubPanel');
    if (existing) existing.remove();
}

function insertSubPanel(html) {
    closeSubPanel();
    const container = document.querySelector('.detail-actions');
    if (!container) return;
    const div = document.createElement('div');
    div.id = 'actionSubPanel';
    div.className = 'action-subpanel';
    div.innerHTML = html;
    container.appendChild(div);
    return div;
}

function handleAction(action, nodeName) {
    const nodeId = selectedNodeId;
    if (!nodeId) return;

    switch (action) {
        case 'edit': openEditPanel(nodeId, nodeName); break;
        case 'reviewed_yes': setReviewStatus(nodeId, nodeName, 'yes'); break;
        case 'reviewed_no': setReviewStatus(nodeId, nodeName, 'no'); break;
        case 'approved_yes': setApprovalStatus(nodeId, nodeName, 'yes'); break;
        case 'approved_no': setApprovalStatus(nodeId, nodeName, 'no'); break;
        case 'version': openVersionPanel(nodeId, nodeName); break;
        case 'delete': openDeleteConfirm(nodeId, nodeName); break;
    }
}

// ── Edit ─────────────────────────────────────
function openEditPanel(nodeId, nodeName) {
    const data = getNodeData(nodeId);
    const edits = data.edits || {};
    // Pull live node data to pre-fill fields
    const ni = currentGraphData?.nodes?.find(n => String(n.id) === String(nodeId)) || {};
    const v   = f => edits[f] !== undefined ? edits[f] : (ni[f] !== undefined ? ni[f] : '');
    const vB  = f => edits[f] !== undefined ? edits[f] : (ni[f] || false);
    const vN  = (f, d) => edits[f] !== undefined ? edits[f] : (ni[f] !== undefined ? ni[f] : d);

    // Build rule type list from graph data + known defaults
    const _defaultRuleTypes = ['constraint','eligibility','process','prohibition','documentation','validation','compliance','definition'];
    const _graphRuleTypes = new Set(_defaultRuleTypes);
    if (currentGraphData?.nodes) {
        currentGraphData.nodes.forEach(n => { if (n.rule_type) _graphRuleTypes.add(n.rule_type); });
    }
    const ruleTypes = Array.from(_graphRuleTypes).sort();
    const ruleTypeOpts = ruleTypes.map(t =>
        `<option value="${t}"${v('rule_type') === t ? ' selected' : ''}>${t}</option>`).join('');
    const confVal = vN('confidence_score', 85);
    const requiresReview = vB('requires_review');
    const safeId = escapeHtml(String(nodeId));
    const safeNameAttr = escapeHtml(String(nodeName)).replace(/'/g, "&#39;");
    const contentVal = escapeHtml(String(v('content') || ni.content || ni.description || ''));

    insertSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Edit Node</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeSubPanel()">&times;</button>
        </div>
        <div class="edit-form">

            <div class="edit-uuid-row">
                <span class="edit-uuid-label">Vertex UUID</span>
                <span class="edit-uuid-value">${safeId}</span>
            </div>

            <div class="edit-field">
                <label>Name ${sparkleBtn('editName', 'node name')}</label>
                <input type="text" id="editName" value="${escapeHtml(String(v('name') || nodeName))}">
            </div>

            <div class="edit-field-row">
                <div class="edit-field">
                    <label>Rule ID</label>
                    <input type="text" id="editRuleId" value="${escapeHtml(String(v('rule_id')))}">
                </div>
                <div class="edit-field">
                    <label>Rule Type</label>
                    <select id="editRuleType">
                        <option value="">— none —</option>
                        ${ruleTypeOpts}
                    </select>
                </div>
            </div>

            <div class="edit-field-row">
                <div class="edit-field">
                    <label>Entity</label>
                    <input type="text" id="editEntity" value="${escapeHtml(String(v('entity_or_relationship')))}">
                </div>
                <div class="edit-field edit-field--center">
                    <label class="edit-checkbox-label">
                        <input type="checkbox" id="editMandatory" ${vB('mandatory') ? 'checked' : ''}>
                        Mandatory
                    </label>
                </div>
            </div>

            <div class="edit-field">
                <label>Description ${sparkleBtn('editDescription', 'rule description')}</label>
                <textarea id="editDescription">${escapeHtml(String(v('description')))}</textarea>
            </div>

            <details class="edit-details">
                <summary>More Fields</summary>
                <div class="edit-details-body">
                    <div class="edit-field">
                        <label>Conditions ${sparkleBtn('editConditions', 'conditions')}</label>
                        <textarea id="editConditions">${escapeHtml(String(v('conditions')))}</textarea>
                    </div>
                    <div class="edit-field">
                        <label>Consequences ${sparkleBtn('editConsequences', 'consequences')}</label>
                        <textarea id="editConsequences">${escapeHtml(String(v('consequences')))}</textarea>
                    </div>
                    <div class="edit-field">
                        <label>Exceptions ${sparkleBtn('editExceptions', 'exceptions')}</label>
                        <textarea id="editExceptions">${escapeHtml(String(v('exceptions')))}</textarea>
                    </div>
                    <div class="edit-field">
                        <label>Reference</label>
                        <input type="text" id="editReference" value="${escapeHtml(String(v('reference')))}">
                    </div>
                    <div class="edit-field">
                        <label>Confidence Score &nbsp;<span id="editConfVal">${confVal}</span></label>
                        <input type="range" id="editConfidence" min="0" max="100" step="0.5" value="${confVal}"
                               oninput="document.getElementById('editConfVal').textContent=this.value">
                    </div>
                    <div class="edit-field">
                        <label class="edit-checkbox-label">
                            <input type="checkbox" id="editRequiresReview" ${requiresReview ? 'checked' : ''}
                                   onchange="document.getElementById('editReviewReasonRow').style.display=this.checked?'':'none'">
                            Requires Review
                        </label>
                    </div>
                    <div class="edit-field" id="editReviewReasonRow" style="${requiresReview ? '' : 'display:none'}">
                        <label>Review Reason</label>
                        <input type="text" id="editReviewReason" value="${escapeHtml(String(v('review_reason')))}">
                    </div>
                </div>
            </details>

            <div class="edit-field">
                <label>Content ${sparkleBtn('editContent', 'compliance rule content')}</label>
                <textarea id="editContent">${contentVal}</textarea>
            </div>

            <div class="edit-actions">
                <button class="edit-cancel" title="Discard all unsaved edits" onclick="clearEdits('${safeId}', '${safeNameAttr}')">Clear Edits</button>
                <button class="edit-save" title="Save changes to server" onclick="saveEdits('${safeId}', '${safeNameAttr}')">Save</button>
            </div>
        </div>
    `);

    // Auto-grow all textareas in the edit form
    const _arEdit = ta => {
        ta.style.height = 'auto';
        ta.style.height = Math.min(ta.scrollHeight, 320) + 'px';
        ta.style.overflowY = ta.scrollHeight > 320 ? 'auto' : 'hidden';
    };
    document.querySelectorAll('.edit-form textarea').forEach(ta => {
        _arEdit(ta);
        ta.addEventListener('input', () => _arEdit(ta));
    });
    document.querySelector('.edit-details')?.addEventListener('toggle', function() {
        if (this.open) document.querySelectorAll('.edit-form textarea').forEach(_arEdit);
    });

    document.getElementById('editName')?.focus();
}

function saveEdits(nodeId, nodeName) {
    const data = getNodeData(nodeId);
    const oldEdits = data.edits || {};
    const ni = currentGraphData?.nodes?.find(n => String(n.id) === String(nodeId)) || {};

    const g   = id => document.getElementById(id)?.value?.trim() ?? '';
    const gB  = id => document.getElementById(id)?.checked ?? false;
    const gN  = id => parseFloat(document.getElementById(id)?.value ?? '85');

    const newEdits = {
        name:                   g('editName') || nodeName,
        rule_id:                g('editRuleId'),
        rule_type:              g('editRuleType'),
        entity_or_relationship: g('editEntity'),
        mandatory:              gB('editMandatory'),
        description:            g('editDescription'),
        conditions:             g('editConditions'),
        consequences:           g('editConsequences'),
        exceptions:             g('editExceptions'),
        reference:              g('editReference'),
        confidence_score:       gN('editConfidence'),
        requires_review:        gB('editRequiresReview'),
        review_reason:          g('editReviewReason'),
        content:                g('editContent'),
    };

    // Track per-field changes for version history
    const changes = {};
    for (const f of Object.keys(newEdits)) {
        const oldVal = oldEdits[f] !== undefined ? oldEdits[f] : ni[f];
        const newVal = newEdits[f];
        if (String(newVal) !== String(oldVal !== undefined ? oldVal : '')) {
            changes[f] = {
                from: String(oldVal ?? '').slice(0, 60),
                to:   String(newVal).slice(0, 60),
            };
        }
    }
    if (Object.keys(changes).length) {
        if (!data.versionHistory) data.versionHistory = [];
        data.versionHistory.push({ changes, time: new Date().toLocaleString() });
    }

    data.edits = newEdits;
    setNodeData(nodeId, data);
    closeSubPanel();

    // Reflect the two most-visible fields immediately without a full re-render
    if (newEdits.name) {
        const titleEl = document.getElementById('detailTitle');
        if (titleEl) titleEl.innerHTML = escapeHtml(newEdits.name) + '<span class="edit-overlay-badge">edited</span>';
    }
    if (newEdits.content) {
        const ctEl = document.querySelector('.detail-content-text');
        if (ctEl) ctEl.textContent = newEdits.content;
    }
    showToast('Edits saved', ICONS.edit);
}

function clearEdits(nodeId, nodeName) {
    const data = getNodeData(nodeId);
    data.edits = {};
    setNodeData(nodeId, data);
    closeSubPanel();
    if (selectedNodeId) {
        const node = currentGraphData?.nodes?.find(n => n.id == selectedNodeId);
        if (node) onNodeClick({ stopPropagation() {}, currentTarget: null }, node);
    }
    showToast('Edits cleared', ICONS.edit);
}

// ── Reviewed toggle ──────────────────────────
function setReviewStatus(nodeId, nodeName, status) {
    const data = getNodeData(nodeId);
    const oldStatus = data.reviewed;
    data.reviewed = status;
    data.reviewHistory.push({ status, time: new Date().toLocaleString() });

    // Record in version history
    if (status !== oldStatus) {
        if (!data.versionHistory) data.versionHistory = [];
        data.versionHistory.push({
            changes: { reviewed: { from: oldStatus || 'none', to: status } },
            time: new Date().toLocaleString()
        });
    }
    setNodeData(nodeId, data);

    const yesBtn = document.querySelector('.reviewed-toggle-btn[data-val="yes"]');
    const noBtn = document.querySelector('.reviewed-toggle-btn[data-val="no"]');
    if (yesBtn && noBtn) {
        yesBtn.classList.toggle('active-yes', status === 'yes');
        noBtn.classList.toggle('active-no', status === 'no');
    }

    showToast(`"${nodeName}" marked as ${status === 'yes' ? 'reviewed' : 'not reviewed'}`, status === 'yes' ? ICONS.success : ICONS.error);
}

// ── Approved toggle ──────────────────────────
function setApprovalStatus(nodeId, nodeName, status) {
    const data = getNodeData(nodeId);
    const oldStatus = data.approved;
    if (!data.approvalHistory) data.approvalHistory = [];
    data.approved = status;
    data.approvalHistory.push({ status, time: new Date().toLocaleString() });

    // Record in version history
    if (status !== oldStatus) {
        if (!data.versionHistory) data.versionHistory = [];
        data.versionHistory.push({
            changes: { approved: { from: oldStatus || 'none', to: status } },
            time: new Date().toLocaleString()
        });
    }
    setNodeData(nodeId, data);

    const yesBtn = document.querySelector('.approved-toggle-btn[data-val="yes"]');
    const noBtn = document.querySelector('.approved-toggle-btn[data-val="no"]');
    if (yesBtn && noBtn) {
        yesBtn.classList.toggle('active-yes', status === 'yes');
        noBtn.classList.toggle('active-no', status === 'no');
    }

    showToast(`"${nodeName}" marked as ${status === 'yes' ? 'approved' : 'not approved'}`, status === 'yes' ? ICONS.success : ICONS.info);
}

// ── Edge Approved toggle ─────────────────────
function setEdgeApprovalStatus(edgeId, status) {
    const data = getEdgeData(edgeId);
    const oldStatus = data.approved;
    if (!data.approvalHistory) data.approvalHistory = [];
    data.approved = status;
    data.approvalHistory.push({ status, time: new Date().toLocaleString() });

    if (status !== oldStatus) {
        if (!data.versionHistory) data.versionHistory = [];
        data.versionHistory.push({
            changes: { approved: { from: oldStatus || 'none', to: status } },
            time: new Date().toLocaleString()
        });
    }
    setEdgeData(edgeId, data);

    const yesBtn = document.querySelector('.edge-detail-actions .approved-toggle-btn[data-val="yes"]');
    const noBtn = document.querySelector('.edge-detail-actions .approved-toggle-btn[data-val="no"]');
    if (yesBtn && noBtn) {
        yesBtn.classList.toggle('active-yes', status === 'yes');
        noBtn.classList.toggle('active-no', status === 'no');
    }

    showToast(`Edge marked as ${status === 'yes' ? 'approved' : 'not approved'}`, status === 'yes' ? ICONS.success : ICONS.info);
}

// ── Version History ─────────────────────────
function openVersionPanel(nodeId, nodeName) {
    const data = getNodeData(nodeId);
    const versions = data.versionHistory || [];
    const safeId = escapeHtml(String(nodeId));
    const safeName = escapeHtml(nodeName).replace(/'/g, '&#39;');
    const versionHTML = versions.length
        ? versions.slice().reverse().map((v, i) => {
            const num = versions.length - i;
            const idx = num - 1; // 0-based index into versionHistory array
            const changesHTML = Object.entries(v.changes || {}).map(([field, vals]) =>
                `<div class="version-change">
                    <span class="version-field">${escapeHtml(field)}</span>
                    <span class="version-from">${escapeHtml(String(vals.from || '').slice(0, 60))}</span>
                    <span class="version-arrow">→</span>
                    <span class="version-value">${escapeHtml(String(vals.to).slice(0, 60))}</span>
                </div>`
            ).join('');
            // Only show revert for edit-type changes (name/content), not status/delete changes
            const hasEditChanges = Object.keys(v.changes || {}).some(k => k === 'name' || k === 'content');
            const revertBtn = hasEditChanges
                ? `<button class="version-revert-btn" onclick="revertToVersion('${safeId}','${safeName}',${idx})" title="Revert to values before this change">↩ Revert</button>`
                : '';
            return `<div class="version-item">
                <div class="version-header">
                    <span class="version-number">v${num}</span>
                    <span class="version-time">${v.time}</span>
                    ${revertBtn}
                </div>
                <div class="version-changes">${changesHTML}</div>
            </div>`;
        }).join('')
        : '<div class="history-empty">No version history yet</div>';

    insertSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Version History</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeSubPanel()">&times;</button>
        </div>
        <div class="version-info">All edits and reviews are saved on the server and persist across sessions and browsers.</div>
        <div class="version-list">${versionHTML}</div>
    `);
}

function revertToVersion(nodeId, nodeName, versionIndex) {
    const data = getNodeData(nodeId);
    const versions = data.versionHistory || [];
    if (versionIndex < 0 || versionIndex >= versions.length) return;

    const version = versions[versionIndex];
    const changes = version.changes || {};

    // Build the reverted edits — restore the "from" values
    const revertedEdits = { ...(data.edits || {}) };
    if (changes.name) revertedEdits.name = changes.name.from;
    if (changes.content) revertedEdits.content = changes.content.from;

    // If both name and content revert to original/empty, clear edits entirely
    const nameEmpty = !revertedEdits.name || revertedEdits.name === nodeName;
    const contentEmpty = !revertedEdits.content || revertedEdits.content === '(original)';
    if (nameEmpty && contentEmpty) {
        revertedEdits.name = '';
        revertedEdits.content = '';
    }

    // Record the revert itself as a version entry
    const revertChanges = {};
    if (changes.name) revertChanges.name = { from: changes.name.to, to: changes.name.from };
    if (changes.content) revertChanges.content = { from: changes.content.to, to: changes.content.from };
    data.versionHistory.push({ changes: revertChanges, time: new Date().toLocaleString(), revert: true });

    data.edits = revertedEdits;
    setNodeData(nodeId, data);

    // Refresh the detail panel
    closeSubPanel();
    if (selectedNodeId) {
        const node = currentGraphData?.nodes?.find(n => String(n.id) === String(nodeId));
        if (node) onNodeClick({ stopPropagation() {}, currentTarget: null }, node);
    }
    showToast(`Reverted to v${versionIndex + 1}`, ICONS.revert);
}

// ── Delete (permanent) ──────────────────────
function openDeleteConfirm(nodeId, nodeName) {
    insertSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Delete Node</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeSubPanel()">&times;</button>
        </div>
        <div class="delete-confirm">
            <p>Permanently delete <strong>${escapeHtml(nodeName)}</strong>?<br><span style="font-size:0.72rem;color:var(--rose)">This will remove the node <em>and all its edges</em> from the database. This cannot be undone.</span></p>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn cancel" title="Cancel — keep this node" onclick="closeSubPanel()">Cancel</button>
                <button class="delete-confirm-btn danger" id="deleteConfirmBtn" title="Permanently delete this node and all its edges" onclick="confirmDeleteNode('${nodeId}', '${escapeHtml(nodeName).replace(/'/g,"&#39;")}')">Delete Permanently</button>
            </div>
        </div>
    `);
}

async function confirmDeleteNode(nodeId, nodeName) {
    const btn = document.getElementById('deleteConfirmBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Deleting…'; }
    try {
        const graphName = currentGraphName || '';
        const res = await fetch(
            `/api/vertex/${encodeURIComponent(nodeId)}?graph_name=${encodeURIComponent(graphName)}`,
            { method: 'DELETE' }
        );
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err.errors || [res.statusText]).join(', '));
        }
        // Remove from in-memory graph data
        if (currentGraphData) {
            currentGraphData.nodes = currentGraphData.nodes.filter(n => String(n.id) !== String(nodeId));
            currentGraphData.links = currentGraphData.links.filter(l => {
                const srcId = typeof l.source === 'object' ? l.source.id : l.source;
                const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
                return String(srcId) !== String(nodeId) && String(tgtId) !== String(nodeId);
            });
        }
        // Remove D3 elements immediately
        if (gRoot) {
            gRoot.selectAll('.graph-node, .graph-node-hit').filter(d => String(d.id) === String(nodeId)).remove();
            const _nodeEdgeFilter = l => {
                const srcId = typeof l.source === 'object' ? l.source.id : l.source;
                const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
                return String(srcId) === String(nodeId) || String(tgtId) === String(nodeId);
            };
            gRoot.selectAll('.graph-link, .graph-link-hit').filter(_nodeEdgeFilter).remove();
            gRoot.selectAll('.graph-link-label, .link-label').filter(_nodeEdgeFilter).remove();
            // Remove the node label too
            gRoot.selectAll('.graph-node-label').filter(d => String(d.id) === String(nodeId)).remove();
        }
        if (simulation) {
            simulation.nodes(currentGraphData?.nodes || []);
            simulation.force('link')?.links(currentGraphData?.links || []);
            simulation.alpha(0.3).restart();
        }
        closeSubPanel();
        closeDetail();
        showToast(`"${nodeName}" deleted permanently`, ICONS.trash);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Delete Permanently'; }
        showToast(`Delete failed: ${e.message}`, ICONS.error);
    }
}

function undoDeleteFlag(nodeId, nodeName) {
    const data = getNodeData(nodeId);
    data.deleted = false;
    delete data.deletedAt;
    if (!data.versionHistory) data.versionHistory = [];
    data.versionHistory.push({ changes: { deleted: { from: true, to: false } }, time: new Date().toLocaleString() });
    setNodeData(nodeId, data);
    const banner = document.getElementById('deletedBanner');
    if (banner) banner.remove();
    if (svg) d3.selectAll('.graph-node').filter(d => String(d.id) === String(nodeId)).style('opacity', null);
    showToast(`Deletion flag removed for "${nodeName}"`, ICONS.success);
}

// ── Delete Edge From Node Detail ─────────────
// Called from the × button on dep-cards inside the node detail panel.
async function deleteEdgeFromDetail(sourceId, targetId, edgeLabel, direction) {
    const graphName = currentGraphName || '';
    try {
        const res = await fetch('/api/edge', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_name: graphName, source_id: sourceId, target_id: targetId, label: edgeLabel }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err.errors || [res.statusText]).join(', '));
        }
        // Remove from in-memory graph data
        if (currentGraphData) {
            currentGraphData.links = currentGraphData.links.filter(l => {
                const srcId = typeof l.source === 'object' ? l.source.id : l.source;
                const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
                return !(String(srcId) === String(sourceId) && String(tgtId) === String(targetId) && (l.label || '') === edgeLabel);
            });
        }
        // Remove D3 elements
        if (gRoot) {
            const _filter = l => {
                const srcId = typeof l.source === 'object' ? l.source.id : l.source;
                const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
                return String(srcId) === String(sourceId) && String(tgtId) === String(targetId) && (l.label || '') === edgeLabel;
            };
            gRoot.selectAll('.graph-link, .graph-link-hit').filter(_filter).remove();
            gRoot.selectAll('.graph-link-label, .link-label').filter(_filter).remove();
        }
        if (simulation) {
            simulation.force('link')?.links(currentGraphData?.links || []);
            simulation.alpha(0.3).restart();
        }
        showToast('Edge removed', ICONS.trash);
        // Refresh the node detail panel to update the edge lists
        const currentNodeId = selectedNodeId;
        if (currentNodeId) {
            try {
                const r = await fetch(`/api/vertex/${currentNodeId}?graph_name=${encodeURIComponent(graphName)}`);
                const info = await r.json();
                if (r.ok) renderDetail(info);
            } catch (_e) { /* detail refresh is best-effort */ }
        }
    } catch (e) {
        showToast(`Delete failed: ${e.message}`, ICONS.error);
    }
}

/* ── Edge Action Handlers ──────────────────── */
function closeEdgeSubPanel() {
    const existing = document.getElementById('edgeActionSubPanel');
    if (existing) existing.remove();
}

function insertEdgeSubPanel(html) {
    closeEdgeSubPanel();
    const container = document.querySelector('.edge-detail-actions');
    if (!container) return;
    const div = document.createElement('div');
    div.id = 'edgeActionSubPanel';
    div.className = 'action-subpanel';
    div.innerHTML = html;
    container.appendChild(div);
    return div;
}

function handleEdgeAction(action, edgeId) {
    if (!edgeId) return;
    switch (action) {
        case 'edit': openEdgeEditPanel(edgeId); break;
        case 'reverse': openEdgeReverseConfirm(edgeId); break;
        case 'delete': openEdgeDeleteConfirm(edgeId); break;
        case 'approved_yes': setEdgeApprovalStatus(edgeId, 'yes'); break;
        case 'approved_no': setEdgeApprovalStatus(edgeId, 'no'); break;
    }
}

// ── Edge Edit ────────────────────────────────
function openEdgeEditPanel(edgeId) {
    const data = getEdgeData(edgeId);
    const edits = data.edits || {};
    // Find the current edge from graph data
    const edgeData = _findEdgeById(edgeId);

    const depType = escapeHtml(edits.dependency_type || edgeData?.dependency_type || '');
    const strength = edits.strength !== undefined ? edits.strength : (edgeData?.strength || '');
    const rationale = escapeHtml(edits.rationale || edgeData?.rationale || '');

    const depTypeOptions = ['prerequisite', 'complementary', 'conditional', 'sequential', 'override']
        .map(t => `<option value="${t}"${t === (edits.dependency_type || edgeData?.dependency_type) ? ' selected' : ''}>${t}</option>`)
        .join('');

    insertEdgeSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Edit Edge</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeEdgeSubPanel()">&times;</button>
        </div>
        <div class="edit-form">
            <div class="edit-field">
                <label>Dependency Type</label>
                <select id="edgeEditDepType">
                    <option value="">None</option>
                    ${depTypeOptions}
                </select>
            </div>
            <div class="edit-field">
                <label>Strength (1-5)</label>
                <input type="number" id="edgeEditStrength" min="1" max="5" value="${strength}">
            </div>
            <div class="edit-field">
                <label>Rationale</label>
                <textarea id="edgeEditRationale">${rationale}</textarea>
            </div>
            <div class="edit-actions">
                <button class="edit-cancel" title="Discard all unsaved edits" onclick="clearEdgeEdits(decodeURIComponent('${encodeURIComponent(edgeId)}'))">Clear Edits</button>
                <button class="edit-save" title="Save edge changes" onclick="saveEdgeEdits(decodeURIComponent('${encodeURIComponent(edgeId)}'))">Save</button>
            </div>
        </div>
    `);
}

function saveEdgeEdits(edgeId) {
    const depType = document.getElementById('edgeEditDepType')?.value || '';
    const strength = document.getElementById('edgeEditStrength')?.value || '';
    const rationale = document.getElementById('edgeEditRationale')?.value.trim() || '';
    const data = getEdgeData(edgeId);
    const oldEdits = data.edits || {};

    const changes = {};
    if (depType !== (oldEdits.dependency_type || '')) changes.dependency_type = { from: oldEdits.dependency_type || '(original)', to: depType };
    if (strength !== String(oldEdits.strength || '')) changes.strength = { from: String(oldEdits.strength || '(original)'), to: strength };
    if (rationale !== (oldEdits.rationale || '')) changes.rationale = { from: (oldEdits.rationale || '(original)').slice(0, 80), to: rationale.slice(0, 80) };

    if (Object.keys(changes).length) {
        if (!data.versionHistory) data.versionHistory = [];
        data.versionHistory.push({ changes, time: new Date().toLocaleString() });
    }

    data.edits = { dependency_type: depType, strength, rationale };
    setEdgeData(edgeId, data);
    closeEdgeSubPanel();

    // Re-render the edge detail to show updated values
    _refreshEdgeDetail(edgeId);

    showToast('Edge edits saved', ICONS.edit);
}

function clearEdgeEdits(edgeId) {
    const data = getEdgeData(edgeId);
    data.edits = {};
    setEdgeData(edgeId, data);
    closeEdgeSubPanel();
    _refreshEdgeDetail(edgeId);
    showToast('Edge edits cleared', ICONS.edit);
}

// ── Edge Direction Reverse (confirm + persist) ──
function openEdgeReverseConfirm(edgeId) {
    const edge = _findEdgeById(edgeId);
    if (!edge) { showToast('Edge not found', ICONS.error); return; }
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const srcName = typeof edge.source === 'object' ? (edge.source.name || srcId) : (currentGraphData?.nodes.find(n => String(n.id) === String(srcId))?.name || srcId);
    const tgtName = typeof edge.target === 'object' ? (edge.target.name || tgtId) : (currentGraphData?.nodes.find(n => String(n.id) === String(tgtId))?.name || tgtId);
    const encEdgeId = encodeURIComponent(edgeId);
    insertEdgeSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Reverse Direction</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeEdgeSubPanel()">&times;</button>
        </div>
        <div class="delete-confirm">
            <p style="line-height:1.7">Change direction from<br><strong>${escapeHtml(truncate(String(srcName),30))} &rarr; ${escapeHtml(truncate(String(tgtName),30))}</strong><br>to<br><strong>${escapeHtml(truncate(String(tgtName),30))} &rarr; ${escapeHtml(truncate(String(srcName),30))}</strong>?<br><span style="font-size:0.7rem;color:var(--text-muted)">This will update the edge in the database.</span></p>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn cancel" onclick="closeEdgeSubPanel()">Cancel</button>
                <button class="delete-confirm-btn danger" id="edgeReverseConfirmBtn" onclick="confirmReverseEdge(decodeURIComponent('${encEdgeId}'))">Reverse &amp; Save</button>
            </div>
        </div>
    `);
}

async function confirmReverseEdge(edgeId) {
    const btn = document.getElementById('edgeReverseConfirmBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    const edge = _findEdgeById(edgeId);
    if (!edge) { showToast('Edge not found', ICONS.warning); return; }
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const graphName = currentGraphName || '';
    try {
        const res = await fetch('/api/edge/reverse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_name: graphName, source_id: srcId, target_id: tgtId, label: edge.label || 'depends_on' }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err.errors || [res.statusText]).join(', '));
        }
        const result = await res.json();
        // Swap in local graph data
        const oldSource = edge.source;
        const oldTarget = edge.target;
        edge.source = oldTarget;
        edge.target = oldSource;
        const newEdgeId = result.new_id || edgeId;
        if (result.new_id) edge.id = result.new_id;
        // Log version history
        const data = getEdgeData(edgeId);
        if (!data.versionHistory) data.versionHistory = [];
        const sn = typeof oldSource === 'object' ? (oldSource.name || oldSource.id) : oldSource;
        const tn = typeof oldTarget === 'object' ? (oldTarget.name || oldTarget.id) : oldTarget;
        data.versionHistory.push({ changes: { direction: { from: `${sn} → ${tn}`, to: `${tn} → ${sn}` } }, time: new Date().toLocaleString() });
        setEdgeData(edgeId, data);
        // Update D3
        if (simulation) simulation.alpha(0.3).restart();
        closeEdgeSubPanel();
        // Refresh edge detail panel with new direction
        const newSrcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
        const newTgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
        const newSrcName = typeof edge.source === 'object' ? (edge.source.name || newSrcId) : (currentGraphData?.nodes.find(n => String(n.id) === String(newSrcId))?.name || newSrcId);
        const newTgtName = typeof edge.target === 'object' ? (edge.target.name || newTgtId) : (currentGraphData?.nodes.find(n => String(n.id) === String(newTgtId))?.name || newTgtId);
        renderEdgeDetail(edge, newEdgeId, newSrcId, newTgtId, newSrcName, newTgtName);
        showToast('Edge direction reversed & saved', ICONS.reverse);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Reverse & Save'; }
        showToast(`Reverse failed: ${e.message}`, ICONS.error);
    }
}

// ── Edge Delete ──────────────────────────────
function openEdgeDeleteConfirm(edgeId) {
    const edge = _findEdgeById(edgeId);
    if (!edge) { showToast('Edge not found', ICONS.warning); return; }
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const srcName = typeof edge.source === 'object' ? (edge.source.name || srcId) : (currentGraphData?.nodes.find(n => String(n.id) === String(srcId))?.name || srcId);
    const tgtName = typeof edge.target === 'object' ? (edge.target.name || tgtId) : (currentGraphData?.nodes.find(n => String(n.id) === String(tgtId))?.name || tgtId);
    const encEdgeId = encodeURIComponent(edgeId);
    insertEdgeSubPanel(`
        <div class="action-subpanel-header">
            <span class="action-subpanel-title">Delete Edge</span>
            <button class="action-subpanel-close" title="Close panel" onclick="closeEdgeSubPanel()">&times;</button>
        </div>
        <div class="delete-confirm">
            <p>Permanently delete the edge<br><strong>${escapeHtml(truncate(String(srcName),30))} &rarr; ${escapeHtml(truncate(String(tgtName),30))}</strong>?<br><span style="font-size:0.72rem;color:var(--rose)">This will remove the edge from the database. This cannot be undone.</span></p>
            <div class="delete-confirm-actions">
                <button class="delete-confirm-btn cancel" onclick="closeEdgeSubPanel()">Cancel</button>
                <button class="delete-confirm-btn danger" id="edgeDeleteConfirmBtn" onclick="confirmDeleteEdge(decodeURIComponent('${encEdgeId}'))">Delete Edge</button>
            </div>
        </div>
    `);
}

async function confirmDeleteEdge(edgeId) {
    const btn = document.getElementById('edgeDeleteConfirmBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Deleting…'; }
    const edge = _findEdgeById(edgeId);
    if (!edge) { showToast('Edge not found', ICONS.warning); return; }
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const graphName = currentGraphName || '';
    try {
        const res = await fetch('/api/edge', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_name: graphName, source_id: srcId, target_id: tgtId, label: edge.label || 'depends_on' }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err.errors || [res.statusText]).join(', '));
        }
        // Remove from in-memory graph data
        if (currentGraphData) {
            currentGraphData.links = currentGraphData.links.filter(l => {
                const lid = makeEdgeId(l);
                return lid !== edgeId && String(l.id) !== edgeId;
            });
        }
        // Remove D3 elements
        if (gRoot) {
            const _edgeFilter = l => {
                const lid = makeEdgeId(l);
                return lid === edgeId || String(l.id) === edgeId;
            };
            gRoot.selectAll('.graph-link, .graph-link-hit').filter(_edgeFilter).remove();
            gRoot.selectAll('.graph-link-label, .link-label').filter(_edgeFilter).remove();
        }
        if (simulation) {
            simulation.force('link')?.links(currentGraphData?.links || []);
            simulation.alpha(0.3).restart();
        }
        closeEdgeSubPanel();
        closeEdgeDetail();
        showToast('Edge deleted permanently', ICONS.trash);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Delete Edge'; }
        showToast(`Delete failed: ${e.message}`, ICONS.error);
    }
}

// ── Edge Helpers ─────────────────────────────
function _findEdgeById(edgeId) {
    if (!currentGraphData?.links) return null;
    return currentGraphData.links.find(l => {
        const computedId = makeEdgeId(l);
        return computedId === edgeId || String(l.id) === edgeId;
    });
}

function _refreshEdgeDetail(edgeId) {
    const edge = _findEdgeById(edgeId);
    if (!edge) return;
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const srcName = typeof edge.source === 'object' ? (edge.source.name || srcId) : srcId;
    const tgtName = typeof edge.target === 'object' ? (edge.target.name || tgtId) : tgtId;
    renderEdgeDetail(edge, edgeId, srcId, tgtId, srcName, tgtName);
}
