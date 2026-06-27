/* ── Detail Panel ──────────────────────────── */

/**
 * Format a raw reference string for human-readable display.
 * Strips internal chunk-page IDs like `_017` and cleans up `>` separators.
 * The raw value is preserved in data-ref for backend resolution.
 */
function _formatRefDisplay(raw) {
    let s = raw;
    // Strip chunk page suffixes: "Handbook_011" → "Handbook", "2006_017" → "2006"
    // Pattern: word boundary + _NNN (2-3 digits) followed by comma, paren, end, or space
    s = s.replace(/(_\d{2,3})(?=[,\s);\]]|$)/g, '');
    // Strip standalone "(Chunk _NNN, ...)" or "Chunk _NNN"
    s = s.replace(/\(?\bChunk\s+_?\d{2,3}\b[^)]*\)?\s*/gi, '');
    // Clean up ">" section separators → "›"
    s = s.replace(/\s*>\s*/g, ' › ');
    // Collapse multiple spaces
    s = s.replace(/\s{2,}/g, ' ');
    // Clean up trailing commas or leading/trailing whitespace
    s = s.replace(/,\s*$/, '').trim();
    return s;
}

function showDetailSkeleton() {
    return `<div style="padding:0.25rem 0">
        <div style="margin-bottom:1.25rem;padding:0.75rem;border:1px solid var(--border);border-radius:var(--radius);background:linear-gradient(135deg,rgba(99,102,241,0.06) 0%,rgba(34,211,238,0.03) 100%)">
            <div class="skeleton skeleton-line w-40" style="margin-bottom:12px"></div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
                <div class="skeleton" style="height:34px;border-radius:8px"></div>
                <div class="skeleton" style="height:34px;border-radius:8px"></div>
                <div class="skeleton" style="height:34px;border-radius:8px"></div>
            </div>
        </div>
        <div class="skeleton skeleton-line w-40"></div>
        <div class="skeleton-grid">
            <div class="skeleton skeleton-grid-item"></div><div class="skeleton skeleton-grid-item"></div>
            <div class="skeleton skeleton-grid-item"></div><div class="skeleton skeleton-grid-item"></div>
            <div class="skeleton skeleton-grid-item"></div><div class="skeleton skeleton-grid-item"></div>
        </div>
        <div class="skeleton skeleton-line w-40" style="margin-top:16px"></div>
        <div class="skeleton skeleton-block"></div>
        <div class="skeleton skeleton-line w-60" style="margin-top:16px"></div>
        <div class="skeleton" style="height:44px;margin-bottom:8px;border-radius:8px"></div>
        <div class="skeleton" style="height:44px;border-radius:8px"></div>
    </div>`;
}

// ── Navigation History ───────────────────────
function pushNavHistory() {
    if (_skipNavPush) return;
    if (selectedNodeId) {
        const current = currentGraphData?.nodes?.find(n => n.id === String(selectedNodeId));
        navHistory.push({
            id: selectedNodeId,
            name: current?.name || document.getElementById('detailTitle')?.textContent || selectedNodeId,
            label: current?.label || 'rule'
        });
    }
    updateBackButton();
}

function goBack() {
    if (!navHistory.length) return;
    const prev = navHistory.pop();
    updateBackButton();
    _skipNavPush = true;
    navigateToNode(prev.id);
    _skipNavPush = false;
}

function updateBackButton() {
    const btn = document.getElementById('detailBackBtn');
    if (btn) {
        btn.classList.toggle('visible', navHistory.length > 0);
        if (navHistory.length) {
            btn.title = 'Back to ' + navHistory[navHistory.length - 1].name;
        }
    }
}

// ── Copy Message Button ─────────────────────
function addCopyButton(bubble, text) {
    const btn = document.createElement('button');
    btn.className = 'msg-copy-btn';
    btn.setAttribute('aria-label', 'Copy message');
    btn.title = 'Copy message';
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text).then(() => {
            btn.classList.add('copied');
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
            }, 1500);
        });
    });
    bubble.appendChild(btn);
}

function renderDetail(info) {
    const body = document.getElementById('detailBody');
    const nodeName = info.name || info.id || 'Node';
    // Escape for safe use in inline onclick attributes
    const safeNodeName = escapeHtml(String(nodeName)).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
    const nodeId = String(info.id || selectedNodeId || '');
    const persisted = getNodeData(nodeId);
    let html = '';

    // Show deleted banner if flagged
    if (persisted.deleted) {
        html += `<div class="node-deleted-banner" id="deletedBanner"><span>\u26a0\ufe0f Flagged for deletion</span><button title="Undo deletion flag" onclick="undoDeleteFlag('${nodeId}', '${safeNodeName}')">Undo</button></div>`;
    }

    // Apply edit overlay to title if present
    if (persisted.edits?.name) {
        const titleEl = document.getElementById('detailTitle');
        if (titleEl) titleEl.innerHTML = escapeHtml(persisted.edits.name) + '<span class="edit-overlay-badge">edited</span>';
    }

    // Determine reviewed button states from persisted data
    const yesActive = persisted.reviewed === 'yes' ? ' active-yes' : '';
    const noActive = persisted.reviewed === 'no' ? ' active-no' : (persisted.reviewed === null ? ' active-no' : '');
    // Determine approved button states from persisted data
    const approvedYesActive = persisted.approved === 'yes' ? ' active-yes' : '';
    const approvedNoActive = persisted.approved === 'no' ? ' active-no' : (persisted.approved === null ? ' active-no' : '');

    // ── Action Buttons Toolbar
    html += `<div class="detail-actions">
        <div class="detail-actions-title">Actions</div>
        <div class="detail-actions-grid">
            <button class="action-btn action-btn--edit" onclick="handleAction('edit','${safeNodeName}')" title="Edit this node">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                Edit
            </button>

            <div class="reviewed-toggle">
                <span class="reviewed-toggle-label">Reviewed</span>
                <div class="reviewed-toggle-group">
                    <button class="reviewed-toggle-btn${yesActive}" data-val="yes" title="Mark as reviewed" onclick="handleAction('reviewed_yes','${safeNodeName}')">Yes</button>
                    <button class="reviewed-toggle-btn${noActive}" data-val="no" title="Mark as not reviewed" onclick="handleAction('reviewed_no','${safeNodeName}')">No</button>
                </div>
            </div>
            <div class="approved-toggle">
                <span class="approved-toggle-label">Approved</span>
                <div class="approved-toggle-group">
                    <button class="approved-toggle-btn${approvedYesActive}" data-val="yes" title="Approve this node" onclick="handleAction('approved_yes','${safeNodeName}')">Yes</button>
                    <button class="approved-toggle-btn${approvedNoActive}" data-val="no" title="Reject approval" onclick="handleAction('approved_no','${safeNodeName}')">No</button>
                </div>
            </div>

            <button class="action-btn action-btn--version" onclick="handleAction('version','${safeNodeName}')" title="View version history">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3"/><path d="M3.05 11a9 9 0 1 1 .5 4"/><polyline points="1 4 3 11 10 9"/></svg>
                Version History
            </button>
            <button class="action-btn action-btn--delete" onclick="handleAction('delete','${safeNodeName}')" title="Delete this node">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                Delete
            </button>
        </div>
    </div>`;

    // ── Properties Section – merge any persisted edits on top of live data
    const _editedInfo = persisted.edits && Object.keys(persisted.edits).length
        ? { ...info, ...persisted.edits }
        : info;
    const skipKeys = ['neighbors', 'depends_on', 'depended_by', 'id', 'label', 'content', 'description', 'embedding',
        // Extended v2 fields rendered in dedicated sections below
        'source_reference', 'applicability_scope', 'confidence_breakdown',
        'deduplication_info', 'related_rules', 'data_points_required'];
    const props = Object.entries(_editedInfo).filter(([k]) => !skipKeys.includes(k));

    // Determine graph_name for reference links
    const refGraphName = currentGraphName || currentGraphData?.graph_name || '';

    // Helper: parse a JSON string property safely
    function _tryParseJson(val) {
        if (!val || val === '""' || val === 'null') return null;
        if (typeof val === 'object') return val;
        try { return JSON.parse(val); } catch { return null; }
    }

    if (props.length) {
        html += `<div class="detail-section"><div class="detail-section-title">Properties</div><div class="prop-grid">`;
        for (const [k, v] of props) {
            const key = k.replace(/_/g, ' ');
            let val;
            if (typeof v === 'boolean') {
                val = `<span class="prop-val ${v ? 'bool-true' : 'bool-false'}">${v}</span>`;
            } else if (v === null || v === undefined || v === '') {
                val = '<span class="prop-val" style="opacity:0.3">\u2014</span>';
            } else if (k === 'reference' && v) {
                // Render reference with a placeholder; async-resolve to decide link vs plain text
                // Also pass source_reference if available for better matching
                const displayRef = escapeHtml(_formatRefDisplay(String(v)));
                const encodedRef = encodeURIComponent(String(v));
                const encodedGraph = encodeURIComponent(refGraphName);
                const srcRef = _editedInfo.source_reference || '';
                const encodedSrcRef = srcRef ? encodeURIComponent(typeof srcRef === 'string' ? srcRef : JSON.stringify(srcRef)) : '';
                const refSpanId = 'ref-resolve-' + Date.now();
                val = `<span id="${refSpanId}" class="ref-resolving" data-ref="${encodedRef}" data-graph="${encodedGraph}" data-source-ref="${encodedSrcRef}">${displayRef} <span class="ref-spinner"></span></span>`;
            } else if (k === 'risk_level' && v) {
                const riskClass = v === 'high' ? 'risk-high' : v === 'medium' ? 'risk-medium' : 'risk-low';
                val = `<span class="risk-badge ${riskClass}">${escapeHtml(String(v))}</span>`;
            } else if (k === 'jurisdiction' && v) {
                val = `<span class="jurisdiction-badge">${escapeHtml(String(v))}</span>`;
            } else if ((k === 'effective_date' || k === 'expiration_date') && v) {
                val = `<span class="prop-val date-val">${escapeHtml(String(v))}</span>`;
            } else if (k === 'reference_verified') {
                val = `<span class="prop-val ${v ? 'bool-true' : 'bool-false'}">${v ? 'verified' : 'unverified'}</span>`;
            } else if (k === 'audit_frequency' && v) {
                val = `<span class="prop-val audit-badge">${escapeHtml(String(v).replace(/_/g, ' '))}</span>`;
            } else {
                val = `<span class="prop-val">${escapeHtml(String(v))}</span>`;
            }
            html += `<div class="prop-key">${escapeHtml(key)}</div><div>${val}</div>`;
        }
        html += `</div></div>`;
    }

    // ── Applicability Scope (v2 KG)
    const scopeRaw = _editedInfo.applicability_scope;
    const scope = _tryParseJson(scopeRaw);
    if (scope && typeof scope === 'object') {
        const hasContent = scope.loan_types?.length || scope.occupancy_types?.length || scope.transaction_types?.length;
        if (hasContent) {
            html += `<div class="detail-section">
                <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="true" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Applicability Scope <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="detail-section-content"><div class="scope-grid">`;
            if (scope.loan_types?.length) {
                html += `<div class="scope-group"><div class="scope-label">Loan Types</div><div class="scope-tags">${scope.loan_types.map(t => `<span class="scope-tag">${escapeHtml(t.replace(/_/g, ' '))}</span>`).join('')}</div></div>`;
            }
            if (scope.occupancy_types?.length) {
                html += `<div class="scope-group"><div class="scope-label">Occupancy</div><div class="scope-tags">${scope.occupancy_types.map(t => `<span class="scope-tag">${escapeHtml(t.replace(/_/g, ' '))}</span>`).join('')}</div></div>`;
            }
            if (scope.transaction_types?.length) {
                html += `<div class="scope-group"><div class="scope-label">Transactions</div><div class="scope-tags">${scope.transaction_types.map(t => `<span class="scope-tag">${escapeHtml(t.replace(/_/g, ' '))}</span>`).join('')}</div></div>`;
            }
            html += `</div></div></div>`;
        }
    }

    // ── Related Rules (v2 KG)
    const relatedRaw = _editedInfo.related_rules;
    const relatedRules = _tryParseJson(relatedRaw);
    if (Array.isArray(relatedRules) && relatedRules.length) {
        html += `<div class="detail-section">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="true" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Related Rules (${relatedRules.length}) <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content"><div style="display:flex;flex-wrap:wrap;gap:4px">`;
        for (const ruleId of relatedRules) {
            html += `<span class="neighbor-chip" tabindex="0" role="button" onclick="navigateToNode('${escapeHtml(String(ruleId)).replace(/'/g, '&#39;')}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">
                <span class="neighbor-chip-dot" style="background:var(--accent-light)"></span>${escapeHtml(String(ruleId))}
            </span>`;
        }
        html += `</div></div></div>`;
    }

    // ── Data Points Required (v2 KG)
    const dpRaw = _editedInfo.data_points_required;
    const dataPoints = _tryParseJson(dpRaw);
    if (Array.isArray(dataPoints) && dataPoints.length) {
        html += `<div class="detail-section">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="true" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Data Points Required (${dataPoints.length}) <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content"><div class="scope-tags">${dataPoints.map(dp => `<span class="scope-tag data-point-tag">${escapeHtml(dp.replace(/_/g, ' '))}</span>`).join('')}</div></div></div>`;
    }

    // ── Confidence Breakdown (v1/v2 KG)
    const cbRaw = _editedInfo.confidence_breakdown;
    const confBreakdown = _tryParseJson(cbRaw);
    if (confBreakdown && typeof confBreakdown === 'object' && Object.keys(confBreakdown).length) {
        html += `<div class="detail-section collapsed">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="false" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Confidence Breakdown <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content"><div class="confidence-breakdown">`;
        for (const [ck, cv] of Object.entries(confBreakdown)) {
            const pct = Number(cv) || 0;
            const barColor = pct >= 80 ? 'var(--emerald)' : pct >= 60 ? 'var(--amber)' : 'var(--rose)';
            html += `<div class="conf-row"><span class="conf-label">${escapeHtml(ck.replace(/_/g, ' '))}</span><div class="conf-bar-track"><div class="conf-bar-fill" style="width:${pct}%;background:${barColor}"></div></div><span class="conf-value">${pct}</span></div>`;
        }
        html += `</div></div></div>`;
    }

    // ── Deduplication Info (v2 KG)
    const ddRaw = _editedInfo.deduplication_info;
    const dedupInfo = _tryParseJson(ddRaw);
    if (dedupInfo && typeof dedupInfo === 'object' && dedupInfo.merged_from?.length) {
        html += `<div class="detail-section collapsed">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="false" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Deduplication Info <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content">
                <div class="dedup-info">
                    <div class="dedup-merged">Merged from: ${dedupInfo.merged_from.map(r => `<span class="scope-tag">${escapeHtml(r)}</span>`).join(' ')}</div>
                    ${dedupInfo.confidence ? `<div class="dedup-meta">Confidence: <strong>${escapeHtml(String(dedupInfo.confidence))}</strong></div>` : ''}
                    ${dedupInfo.similarity_score ? `<div class="dedup-meta">Similarity: <strong>${dedupInfo.similarity_score}</strong></div>` : ''}
                    ${dedupInfo.rationale ? `<div class="dedup-rationale">${escapeHtml(dedupInfo.rationale)}</div>` : ''}
                </div>
            </div></div>`;
    }

    // ── Content / Description (apply edit overlay if present)
    const content = persisted.edits?.content || info.content || info.description;
    if (content) {
        const editedTag = persisted.edits?.content ? ' <span class="edit-overlay-badge">edited</span>' : '';
        html += `<div class="detail-section">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="true" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Content${editedTag} <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content"><div class="detail-content-text">${escapeHtml(String(content))}</div></div></div>`;
    }

    // ── Outgoing Dependencies (depends_on)
    if (info.depends_on?.length) {
        html += `<div class="detail-section${info.depends_on.length > 5 ? ' collapsed' : ''}">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="${info.depends_on.length > 5 ? 'false' : 'true'}" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Depends On (${info.depends_on.length}) <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content">`;
        for (const dep of info.depends_on) {
            const tn = dep.target_name || dep.name || '?';
            const dt = dep.dependency_type || 'unknown';
            const dtClass = TYPE_COLORS[dt] ? `dep-type-${dt}` : 'dep-type-default';
            const safeTarget = escapeHtml(String(dep.target_id || dep.target_name || tn)).replace(/'/g, '&#39;');
            const _depEdgeLabel = escapeHtml(dep.edge_label || 'depends_on').replace(/'/g, '&#39;');
            const _depTargetId  = escapeHtml(String(dep.target_id || '')).replace(/'/g, '&#39;');
            html += `<div class="dep-card" tabindex="0" role="button" onclick="navigateToNode('${safeTarget}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();navigateToNode('${safeTarget}')}" title="Navigate to ${escapeHtml(tn)}">
                <div class="dep-card-name">${escapeHtml(tn)}</div>
                <div class="dep-card-meta">
                    <span class="dep-type-badge ${dtClass}">${escapeHtml(dt)}</span>
                    ${dep.strength ? `<span>strength: ${dep.strength}</span>` : ''}
                    <button class="dep-delete-btn" title="Remove this edge" onclick="event.stopPropagation(); deleteEdgeFromDetail('${nodeId}','${_depTargetId}','${_depEdgeLabel}','outgoing')">&times;</button>
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    // ── Incoming Dependencies (depended_by)
    if (info.depended_by?.length) {
        html += `<div class="detail-section${info.depended_by.length > 5 ? ' collapsed' : ''}">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="${info.depended_by.length > 5 ? 'false' : 'true'}" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Depended By (${info.depended_by.length}) <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content">`;
        for (const dep of info.depended_by) {
            const sn = dep.source_name || dep.name || '?';
            const dt = dep.dependency_type || 'unknown';
            const dtClass = TYPE_COLORS[dt] ? `dep-type-${dt}` : 'dep-type-default';
            const safeSource = escapeHtml(String(dep.source_id || dep.source_name || sn)).replace(/'/g, '&#39;');
            const _depEdgeLabel = escapeHtml(dep.edge_label || 'depends_on').replace(/'/g, '&#39;');
            const _depSourceId  = escapeHtml(String(dep.source_id || '')).replace(/'/g, '&#39;');
            html += `<div class="dep-card" tabindex="0" role="button" onclick="navigateToNode('${safeSource}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();navigateToNode('${safeSource}')}" title="Navigate to ${escapeHtml(sn)}">
                <div class="dep-card-name">${escapeHtml(sn)}</div>
                <div class="dep-card-meta">
                    <span class="dep-type-badge ${dtClass}">${escapeHtml(dt)}</span>
                    ${dep.strength ? `<span>strength: ${dep.strength}</span>` : ''}
                    <button class="dep-delete-btn" title="Remove this edge" onclick="event.stopPropagation(); deleteEdgeFromDetail('${_depSourceId}','${nodeId}','${_depEdgeLabel}','incoming')">&times;</button>
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    // ── Neighbors
    if (info.neighbors?.length) {
        html += `<div class="detail-section${info.neighbors.length > 10 ? ' collapsed' : ''}">
            <div class="detail-section-title collapsible" tabindex="0" role="button" aria-expanded="${info.neighbors.length > 10 ? 'false' : 'true'}" onclick="this.parentElement.classList.toggle('collapsed');this.setAttribute('aria-expanded',!this.parentElement.classList.contains('collapsed'))" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">Connected Nodes (${info.neighbors.length}) <svg class="section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></div>
            <div class="detail-section-content"><div style="display:flex;flex-wrap:wrap;gap:2px">`;
        for (const n of info.neighbors) {
            const c = n.label === 'entity_category' ? 'var(--emerald)' : 'var(--accent-light)';
            const safeNId = escapeHtml(String(n.id)).replace(/'/g, '&#39;');
            html += `<span class="neighbor-chip" tabindex="0" role="button" onclick="navigateToNode('${safeNId}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();navigateToNode('${safeNId}')}">
                <span class="neighbor-chip-dot" style="background:${c}"></span>
                ${escapeHtml(truncate(n.name, 25))}
            </span>`;
        }
        html += `</div></div></div>`;
    }

    if (!html) {
        html = '<div style="color:var(--text-muted);text-align:center;padding:2rem">No details available.</div>';
    }

    body.innerHTML = html;
    updateBackButton();

    // Async-resolve any reference placeholders
    body.querySelectorAll('.ref-resolving').forEach(span => {
        const ref = decodeURIComponent(span.dataset.ref);
        const graph = decodeURIComponent(span.dataset.graph);
        const encodedRef = span.dataset.ref;
        const encodedGraph = span.dataset.graph;
        const srcRef = span.dataset.sourceRef ? decodeURIComponent(span.dataset.sourceRef) : '';
        const encodedSrcRef = srcRef ? encodeURIComponent(srcRef) : '';
        let resolveUrl = `/api/reference/resolve?ref=${encodeURIComponent(ref)}&graph_name=${encodeURIComponent(graph)}`;
        if (srcRef) resolveUrl += `&source_reference=${encodeURIComponent(srcRef)}`;
        fetch(resolveUrl)
            .then(r => r.json())
            .then(data => {
                if (data.matches && data.matches.length > 0) {
                    // Resolvable — render as clickable link (pass source_reference for highlighting)
                    span.outerHTML = `<a class="ref-link" href="javascript:void(0)" onclick="openReference('${encodedRef}','${encodedGraph}','${encodedSrcRef}')" title="Open source document chunk">${span.textContent.trim()} <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" style="vertical-align:middle;opacity:0.6"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>`;
                } else {
                    // Not resolvable — render as plain text with badge
                    span.outerHTML = `<span class="ref-unavailable" title="Source document not found in knowledge base">${span.textContent.trim()} <span class="ref-no-source-badge">source not in KB</span></span>`;
                }
            })
            .catch(() => {
                // On error, keep as plain text
                span.outerHTML = `<span class="ref-unavailable">${span.textContent.trim()}</span>`;
            });
    });
}

function closeDetail() {
    document.getElementById('detailPanel').classList.remove('open');
    d3.selectAll('.graph-node').classed('selected', false);
    selectedNodeId = null;
}

function closeEdgeDetail() {
    document.getElementById('edgeDetailPanel').classList.remove('open');
    if (gRoot) gRoot.selectAll('.graph-link').classed('edge-selected', false);
    selectedEdgeId = null;
}

// ── Edge Detail Rendering ────────────────────
function renderEdgeDetail(d, edgeId, srcId, tgtId, srcName, tgtName) {
    const body = document.getElementById('edgeDetailBody');
    const persisted = getEdgeData(edgeId);
    // Use encodeURIComponent for IDs in onclick attrs — HTML entity escaping
    // fails because the parser decodes &#39; back to ' before JS executes,
    // and JanusGraph edge IDs contain single quotes.
    const encEdgeId = encodeURIComponent(String(edgeId));
    const encSrcId = encodeURIComponent(String(srcId));
    const encTgtId = encodeURIComponent(String(tgtId));
    const edgeLabel = d.dependency_type || d.label || 'Edge';
    // Determine approved button states for edge
    const edgeApprovedYes = persisted.approved === 'yes' ? ' active-yes' : '';
    const edgeApprovedNo = persisted.approved === 'no' ? ' active-no' : (persisted.approved === null ? ' active-no' : '');

    let html = '';

    // ── Direction Indicator ──
    html += `<div class="edge-direction-section">
        <div class="edge-direction-visual">
            <button class="edge-endpoint" onclick="navigateToNode(decodeURIComponent('${encSrcId}'))" title="Go to source node">
                <span class="edge-endpoint-dot" style="background:${_getNodeColor(srcId)}"></span>
                <span class="edge-endpoint-name">${escapeHtml(truncate(String(srcName), 30))}</span>
            </button>
            <div class="edge-direction-arrow" id="edgeDirectionArrow">
                <svg viewBox="0 0 60 24" width="60" height="24">
                    <line x1="4" y1="12" x2="50" y2="12" stroke="var(--accent-light)" stroke-width="2"/>
                    <polygon points="50,6 58,12 50,18" fill="var(--accent-light)"/>
                </svg>
                <span class="edge-direction-label">${escapeHtml(d.label || 'edge')}</span>
            </div>
            <button class="edge-endpoint" onclick="navigateToNode(decodeURIComponent('${encTgtId}'))" title="Go to target node">
                <span class="edge-endpoint-dot" style="background:${_getNodeColor(tgtId)}"></span>
                <span class="edge-endpoint-name">${escapeHtml(truncate(String(tgtName), 30))}</span>
            </button>
        </div>
        <button class="edge-reverse-btn" onclick="handleEdgeAction('reverse',decodeURIComponent('${encEdgeId}'))" title="Reverse edge direction">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
            Reverse Direction
        </button>
    </div>`;

    // ── Action Buttons ──
    html += `<div class="edge-detail-actions">
        <div class="detail-actions-title">Actions</div>
        <div class="edge-actions-grid">
            <button class="action-btn action-btn--edit" onclick="handleEdgeAction('edit',decodeURIComponent('${encEdgeId}'))" title="Edit edge properties">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                Edit
            </button>
            <button class="action-btn action-btn--delete" onclick="handleEdgeAction('delete',decodeURIComponent('${encEdgeId}'))" title="Delete this edge permanently">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                Delete
            </button>

            <div class="approved-toggle">
                <span class="approved-toggle-label">Approved</span>
                <div class="approved-toggle-group">
                    <button class="approved-toggle-btn${edgeApprovedYes}" data-val="yes" title="Approve this edge" onclick="handleEdgeAction('approved_yes',decodeURIComponent('${encEdgeId}'))">Yes</button>
                    <button class="approved-toggle-btn${edgeApprovedNo}" data-val="no" title="Reject edge approval" onclick="handleEdgeAction('approved_no',decodeURIComponent('${encEdgeId}'))">No</button>
                </div>
            </div>
        </div>
    </div>`;

    // ── Properties ──
    const skipKeys = ['source', 'target', 'index', 'x', 'y', 'vx', 'vy', 'fx', 'fy', '_degree'];
    const props = Object.entries(d).filter(([k, v]) =>
        !skipKeys.includes(k) && typeof v !== 'object' && typeof v !== 'function'
    );

    if (props.length) {
        html += `<div class="detail-section"><div class="detail-section-title">Properties</div><div class="prop-grid">`;
        for (const [k, v] of props) {
            const key = k.replace(/_/g, ' ');
            let val;
            if (typeof v === 'boolean') {
                val = `<span class="prop-val ${v ? 'bool-true' : 'bool-false'}">${v}</span>`;
            } else if (v === null || v === undefined || v === '') {
                val = '<span class="prop-val" style="opacity:0.3">\u2014</span>';
            } else {
                // Show edit overlay if property has been edited
                const editedVal = persisted.edits?.[k];
                const display = editedVal !== undefined ? editedVal : v;
                const badge = editedVal !== undefined ? ' <span class="edit-overlay-badge">edited</span>' : '';
                val = `<span class="prop-val">${escapeHtml(String(display))}${badge}</span>`;
            }
            html += `<div class="prop-key">${escapeHtml(key)}</div><div>${val}</div>`;
        }
        html += `</div></div>`;
    }

    // ── Connected Nodes ──
    html += `<div class="detail-section">
        <div class="detail-section-title">Connected Nodes</div>
        <div style="display:flex;flex-direction:column;gap:6px">
            <div class="dep-card" onclick="navigateToNode(decodeURIComponent('${encSrcId}'))" title="Navigate to source">
                <div class="dep-card-name"><span style="color:var(--text-muted);font-size:0.7rem;margin-right:4px">SOURCE</span> ${escapeHtml(String(srcName))}</div>
            </div>
            <div class="dep-card" onclick="navigateToNode(decodeURIComponent('${encTgtId}'))" title="Navigate to target">
                <div class="dep-card-name"><span style="color:var(--text-muted);font-size:0.7rem;margin-right:4px">TARGET</span> ${escapeHtml(String(tgtName))}</div>
            </div>
        </div>
    </div>`;

    if (!html) {
        html = '<div style="color:var(--text-muted);text-align:center;padding:2rem">No details available.</div>';
    }

    body.innerHTML = html;
}

function _getNodeColor(nodeId) {
    if (!currentGraphData) return 'var(--accent)';
    const node = currentGraphData.nodes.find(n => String(n.id) === String(nodeId));
    return node ? nodeColor(node) : 'var(--accent)';
}

/**
 * Resolve a reference string and open the matching chunk document in a new tab.
 * Called from onclick in the detail panel's reference property link.
 * If the current node maps to a task with highlight_terms, those terms are passed along.
 * Word positions (start_word_position / end_word_position) and source_text from
 * the source_reference are passed for precise reference highlighting.
 */
function openReference(encodedRef, encodedGraph, encodedSourceRef) {
    const ref = decodeURIComponent(encodedRef);
    const graphName = decodeURIComponent(encodedGraph);
    const srcRefStr = encodedSourceRef ? decodeURIComponent(encodedSourceRef) : '';

    // Parse source_reference for word positions and source_text
    let srcRefObj = null;
    if (srcRefStr) {
        try { srcRefObj = JSON.parse(srcRefStr); } catch(e) { /* ignore */ }
    }

    // Try to find highlight terms from matching task data
    let highlightTerms = [];
    if (typeof _taskData !== 'undefined' && selectedNodeId) {
        const matchingTask = _taskData.find(t =>
            String(t.node_id) === String(selectedNodeId) && t.highlight_terms
        );
        if (matchingTask) {
            highlightTerms = matchingTask.highlight_terms;
        }
    }

    // Build resolve URL with source_reference for better matching
    let resolveUrl = `/api/reference/resolve?ref=${encodeURIComponent(ref)}&graph_name=${encodeURIComponent(graphName)}`;
    if (srcRefStr) {
        resolveUrl += `&source_reference=${encodeURIComponent(srcRefStr)}`;
    }

    fetch(resolveUrl)
        .then(r => r.json())
        .then(data => {
            if (data.matches && data.matches.length > 0) {
                // Open the best match in a new tab, passing current theme
                const best = data.matches[0];
                const theme = localStorage.getItem('p2k-theme') || 'dark';
                let url = best.url;
                const sep = url.includes('?') ? '&' : '?';
                url += sep + 'theme=' + theme;
                if (highlightTerms.length) {
                    url += '&highlight=' + encodeURIComponent(highlightTerms.join(','));
                }
                // Pass word positions from source_reference for precise highlighting
                const startWord = best.start_word_position ?? (srcRefObj && srcRefObj.start_word_position);
                const endWord = best.end_word_position ?? (srcRefObj && srcRefObj.end_word_position);
                if (startWord != null && endWord != null) {
                    url += '&start_word=' + startWord + '&end_word=' + endWord;
                }
                // Pass source_text for text-based fallback highlighting
                const sourceText = best.source_text || (srcRefObj && srcRefObj.source_text);
                if (sourceText && !highlightTerms.length) {
                    url += '&source_text=' + encodeURIComponent(sourceText);
                }
                window.open(url, '_blank');
            } else {
                // No match found — show a brief toast / alert
                console.warn('No matching chunk found for reference:', ref);
                showToast(`No source document found for reference: "${ref}"`, ICONS.warning);
            }
        })
        .catch(err => {
            console.error('Reference resolution failed:', err);
            showToast('Failed to resolve reference', ICONS.error);
        });
}
// ── Detail Panel Resize Handles ──────────────
(function initDetailResize() {
    document.querySelectorAll('.detail-resize-handle').forEach(handle => {
        const panelId = handle.dataset.panel;
        const panel = document.getElementById(panelId);
        if (!panel) return;

        let startX, startW;

        function onMouseMove(e) {
            // Dragging left edge: new width = startW + (startX - currentX)
            const delta = startX - e.clientX;
            const minW = 280;
            const maxW = panel.parentElement.offsetWidth * 0.85;
            const newW = Math.max(minW, Math.min(maxW, startW + delta));
            panel.style.width = newW + 'px';
        }

        function onMouseUp() {
            handle.classList.remove('active');
            panel.classList.remove('resizing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }

        handle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            startX = e.clientX;
            startW = panel.offsetWidth;
            handle.classList.add('active');
            panel.classList.add('resizing');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    });
})();