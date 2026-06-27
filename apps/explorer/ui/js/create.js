/* ── Create Vertex Wizard ──────────────────── */

// Wizard state
let _createWizardStep = 1;
let _createVertexData = {};
let _pendingConnections = [];
let _suggestedConnections = [];
let _schemaCache = null;

// ── Schema Fetch ────────────────────────────

async function _fetchSchema() {
    if (_schemaCache) return _schemaCache;
    try {
        const gn = typeof currentGraphName !== 'undefined' ? currentGraphName : '';
        const resp = await fetch(`/api/vertex/schema?graph_name=${encodeURIComponent(gn)}`);
        if (resp.ok) {
            _schemaCache = await resp.json();
            // Merge live types into the standard lists so UI form options stay adaptive
            if (_schemaCache.live_rule_types?.length) {
                const merged = new Set([..._schemaCache.rule_types, ..._schemaCache.live_rule_types]);
                _schemaCache.rule_types = Array.from(merged).sort();
            }
            if (_schemaCache.live_edge_labels?.length) {
                const merged = new Set([..._schemaCache.edge_labels, ..._schemaCache.live_edge_labels]);
                _schemaCache.edge_labels = Array.from(merged).sort();
            }
        }
    } catch (e) {
        console.warn('Failed to fetch schema:', e);
    }
    return _schemaCache || {
        labels: ['business_rule', 'entity_category'],
        rule_types: ['constraint', 'eligibility', 'process', 'prohibition', 'documentation', 'validation'],
        dependency_types: ['prerequisite', 'complementary', 'conditional', 'sequential', 'override', 'exclusion'],
        edge_labels: ['depends_on', 'belongs_to_category'],
    };
}

// ── Auto-resize helpers ───────────────────────

/**
 * Grow (or shrink) a textarea to exactly fit its content.
 * Caps at 360 px then shows a scrollbar.
 */
function _autoResizeTextarea(ta) {
    ta.style.height = 'auto';
    const h = Math.min(ta.scrollHeight, 360);
    ta.style.height = h + 'px';
    ta.style.overflowY = ta.scrollHeight > 360 ? 'auto' : 'hidden';
}

/** Wire auto-resize on every textarea inside the create wizard. */
function _initAutoResizeTextareas() {
    const wizard = document.querySelector('.create-wizard');
    if (!wizard) return;
    wizard.querySelectorAll('textarea').forEach(ta => {
        _autoResizeTextarea(ta);                        // size for any pre-filled text
        ta.removeEventListener('input', ta._arHandler); // avoid duplicate listeners
        ta._arHandler = () => _autoResizeTextarea(ta);
        ta.addEventListener('input', ta._arHandler);
    });
}

// ── Open / Close ─────────────────────────────

function openCreatePanel() {
    _createWizardStep = 1;
    _createVertexData = {};
    _pendingConnections = [];
    _suggestedConnections = [];
    _renderCreateStep1();
}

function closeCreatePanel() {
    const panel = document.getElementById('detailPanel');
    if (panel) panel.classList.remove('open');
    selectedNodeId = null;
    document.removeEventListener('click', _closeManualDropdown, true);
}

// ── Step 1: Vertex Properties ───────────────

async function _renderCreateStep1() {
    const schema = await _fetchSchema();
    const panel = document.getElementById('detailPanel');
    const title = document.getElementById('detailTitle');
    const badge = document.getElementById('detailBadge');
    const body = document.getElementById('detailBody');

    panel.classList.add('open');
    title.textContent = 'Create New Node';
    badge.textContent = 'new';
    badge.className = 'detail-label-badge badge-rule';

    // Pre-fill from previous data (if user clicked Back)
    const d = _createVertexData;

    const ruleTypeOptions = schema.rule_types.map(t =>
        `<option value="${t}"${d.rule_type === t ? ' selected' : ''}>${t}</option>`
    ).join('');

    // Collect entity categories from current graph data for dropdown
    let entityOptions = '';
    if (currentGraphData?.nodes) {
        const entities = [...new Set(
            currentGraphData.nodes
                .map(n => n.entity_or_relationship)
                .filter(Boolean)
        )].sort();
        entityOptions = entities.map(e =>
            `<option value="${e}"${d.entity_or_relationship === e ? ' selected' : ''}>${e}</option>`
        ).join('');
    }

    body.innerHTML = `
        <div class="create-wizard">
            <div class="create-wizard-progress">
                <div class="wizard-step active">1. Properties</div>
                <div class="wizard-step-separator"></div>
                <div class="wizard-step">2. Connections</div>
            </div>

            <div class="create-form">
                <!-- Label selector -->
                <div class="create-field">
                    <label>Vertex Label *</label>
                    <div class="create-radio-group">
                        <label class="create-radio">
                            <input type="radio" name="createLabel" value="business_rule" ${d.label !== 'entity_category' ? 'checked' : ''} onchange="document.getElementById('createRuleFields').style.display=this.checked?'':'none'">
                            <span>business_rule</span>
                        </label>
                        <label class="create-radio">
                            <input type="radio" name="createLabel" value="entity_category" ${d.label === 'entity_category' ? 'checked' : ''} onchange="document.getElementById('createRuleFields').style.display=this.checked?'none':''">
                            <span>entity_category</span>
                        </label>
                    </div>
                </div>

                <!-- Core fields -->
                <div class="create-field">
                    <label for="createName">Name *</label>
                    <input type="text" id="createName" value="${escapeHtml(d.name || '')}" placeholder="e.g., Minimum Credit Score for ARM Loans" maxlength="200">
                </div>

                <div id="createRuleFields" style="${d.label === 'entity_category' ? 'display:none' : ''}">
                    <div class="create-field-row">
                        <div class="create-field">
                            <label for="createRuleId">Rule ID <button type="button" id="suggestRuleIdBtn" class="ai-rewrite-btn" title="Suggest Rule ID from name" onclick="suggestRuleId()">${_SPARKLE_ICON}</button></label>
                            <input type="text" id="createRuleId" value="${escapeHtml(d.rule_id || '')}" placeholder="e.g., BR_ENTITY_TYPE_001_001">
                        </div>
                        <div class="create-field">
                            <label for="createRuleType">Rule Type</label>
                            <select id="createRuleType">
                                <option value="">— Select —</option>
                                ${ruleTypeOptions}
                            </select>
                        </div>
                    </div>

                    <div class="create-field-row">
                        <div class="create-field">
                            <label for="createEntity">Entity</label>
                            <select id="createEntity">
                                <option value="">— Select —</option>
                                ${entityOptions}
                            </select>
                        </div>
                        <div class="create-field">
                            <label for="createMandatory" class="create-checkbox-label">
                                <input type="checkbox" id="createMandatory" ${d.mandatory ? 'checked' : ''}>
                                Mandatory
                            </label>
                        </div>
                    </div>

                    <div class="create-field">
                        <label for="createDescription">Description ${sparkleBtn('createDescription', 'rule description')}</label>
                        <textarea id="createDescription" rows="2" placeholder="Short description of the rule">${escapeHtml(d.description || '')}</textarea>
                    </div>

                    <!-- Collapsible detail fields -->
                    <details class="create-details" ${d._detailsOpen ? 'open' : ''}>
                        <summary>Additional Fields</summary>
                        <div class="create-details-body">
                            <div class="create-field">
                                <label for="createConditions">Conditions ${sparkleBtn('createConditions', 'conditions')}</label>
                                <textarea id="createConditions" rows="2" placeholder="When does this rule apply?">${escapeHtml(d.conditions || '')}</textarea>
                            </div>
                            <div class="create-field">
                                <label for="createConsequences">Consequences ${sparkleBtn('createConsequences', 'consequences')}</label>
                                <textarea id="createConsequences" rows="2" placeholder="What happens if violated?">${escapeHtml(d.consequences || '')}</textarea>
                            </div>
                            <div class="create-field">
                                <label for="createExceptions">Exceptions ${sparkleBtn('createExceptions', 'exceptions')}</label>
                                <textarea id="createExceptions" rows="2" placeholder="Any exceptions to this rule?">${escapeHtml(d.exceptions || '')}</textarea>
                            </div>
                            <div class="create-field">
                                <label for="createReference">Reference</label>
                                <input type="text" id="createReference" value="${escapeHtml(d.reference || '')}" placeholder="e.g., Selling Guide B3-3.1-09">
                            </div>
                            <div class="create-field-row">
                                <div class="create-field">
                                    <label for="createConfidence">Confidence Score</label>
                                    <div class="create-slider-row">
                                        <input type="range" id="createConfidence" min="0" max="100" step="0.5" value="${d.confidence_score ?? 85}" oninput="document.getElementById('createConfVal').textContent=this.value">
                                        <span id="createConfVal">${d.confidence_score ?? 85}</span>
                                    </div>
                                </div>
                                <div class="create-field">
                                    <label for="createRequiresReview" class="create-checkbox-label">
                                        <input type="checkbox" id="createRequiresReview" ${d.requires_review ? 'checked' : ''}>
                                        Requires Review
                                    </label>
                                </div>
                            </div>
                            <div class="create-field" id="createReviewReasonField" style="${d.requires_review ? '' : 'display:none'}">
                                <label for="createReviewReason">Review Reason</label>
                                <input type="text" id="createReviewReason" value="${escapeHtml(d.review_reason || '')}" placeholder="Why does this need review?">
                            </div>
                        </div>
                    </details>
                </div>

                <!-- Content (always visible) -->
                <div class="create-field">
                    <label for="createContent">Content * <span class="create-hint">(searchable text, min 10 chars)</span> ${sparkleBtn('createContent', 'full content text')}</label>
                    <textarea id="createContent" rows="4" placeholder="Full text content for semantic search indexing...">${escapeHtml(d.content || '')}</textarea>
                </div>

                <!-- Actions -->
                <div class="create-actions">
                    <button class="create-btn create-btn--cancel" title="Cancel and close wizard" onclick="closeCreatePanel()">Cancel</button>
                    <button class="create-btn create-btn--next" title="Continue to connections step" onclick="_goToStep2()">Next: Add Connections →</button>
                </div>
            </div>
        </div>
    `;

    // Wire requires_review toggle
    const reviewCb = document.getElementById('createRequiresReview');
    if (reviewCb) {
        reviewCb.addEventListener('change', () => {
            const field = document.getElementById('createReviewReasonField');
            if (field) field.style.display = reviewCb.checked ? '' : 'none';
        });
    }

    document.getElementById('createName')?.focus();
    _initAutoResizeTextareas();

    // Re-run auto-resize when the "Additional Fields" details section is toggled open
    const detailsEl = document.querySelector('.create-details');
    if (detailsEl) {
        detailsEl.addEventListener('toggle', () => {
            if (detailsEl.open) _initAutoResizeTextareas();
        });
    }

    // Close manual target dropdown on click-outside
    document.addEventListener('click', _closeManualDropdown, true);
}

// ── Collect form data from Step 1 ────────────

function _collectStep1Data() {
    const label = document.querySelector('input[name="createLabel"]:checked')?.value || 'business_rule';
    const data = {
        label,
        name: document.getElementById('createName')?.value?.trim() || '',
        content: document.getElementById('createContent')?.value?.trim() || '',
    };

    if (label === 'business_rule') {
        data.rule_id = document.getElementById('createRuleId')?.value?.trim() || '';
        data.rule_type = document.getElementById('createRuleType')?.value || '';
        data.entity_or_relationship = document.getElementById('createEntity')?.value || '';
        data.mandatory = document.getElementById('createMandatory')?.checked || false;
        data.description = document.getElementById('createDescription')?.value?.trim() || '';
        data.conditions = document.getElementById('createConditions')?.value?.trim() || '';
        data.consequences = document.getElementById('createConsequences')?.value?.trim() || '';
        data.exceptions = document.getElementById('createExceptions')?.value?.trim() || '';
        data.reference = document.getElementById('createReference')?.value?.trim() || '';
        data.confidence_score = parseFloat(document.getElementById('createConfidence')?.value || '85');
        data.requires_review = document.getElementById('createRequiresReview')?.checked || false;
        data.review_reason = document.getElementById('createReviewReason')?.value?.trim() || '';
        data._detailsOpen = document.querySelector('.create-details')?.open || false;
    }

    return data;
}

// ── Validate Step 1 ─────────────────────────

function _validateStep1(data) {
    const errors = [];
    if (!data.name) errors.push('Name is required');
    if (!data.content || data.content.length < 10) errors.push('Content is required (min 10 characters)');
    return errors;
}

// ── Transition to Step 2 ─────────────────────

async function _goToStep2() {
    const data = _collectStep1Data();
    const errors = _validateStep1(data);
    if (errors.length) {
        showToast(errors[0], ICONS.warningRose);
        return;
    }
    _createVertexData = data;
    _createWizardStep = 2;
    await _renderCreateStep2();
}

// ── Step 2: Connections ──────────────────────

async function _renderCreateStep2() {
    const body = document.getElementById('detailBody');
    const title = document.getElementById('detailTitle');
    title.textContent = 'Add Connections';

    // Show loading while fetching suggestions
    body.innerHTML = `
        <div class="create-wizard">
            <div class="create-wizard-progress">
                <div class="wizard-step completed">1. Properties ✓</div>
                <div class="wizard-step-separator done"></div>
                <div class="wizard-step active">2. Connections</div>
            </div>
            <div style="text-align:center;padding:2rem;color:var(--text-muted)">
                <div class="skeleton skeleton-line w-60" style="margin:0 auto 12px"></div>
                <div class="skeleton skeleton-line w-40" style="margin:0 auto"></div>
                <p style="margin-top:12px;font-size:0.82rem">Finding recommended connections...</p>
            </div>
        </div>
    `;

    // Fetch suggestions from backend
    try {
        const resp = await fetch('/api/vertex/suggest-connections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                graph_name: currentGraphName || 'g',
                name: _createVertexData.name,
                content: _createVertexData.content,
                rule_type: _createVertexData.rule_type || '',
                entity_or_relationship: _createVertexData.entity_or_relationship || '',
                category: _createVertexData.rule_type || '',
                top_k: 5,
            }),
        });
        if (resp.ok) {
            const data = await resp.json();
            _suggestedConnections = data.suggestions || [];
        }
    } catch (e) {
        console.warn('Suggestions fetch failed:', e);
    }

    _renderStep2Content();
}

function _renderStep2Content() {
    const body = document.getElementById('detailBody');
    const schema = _schemaCache || {};
    const depTypes = (schema.dependency_types || ['prerequisite', 'complementary', 'conditional', 'sequential', 'override', 'exclusion']);
    const edgeLabels = (schema.edge_labels || ['depends_on', 'belongs_to_category']);

    // Build suggestions HTML
    let suggestionsHTML = '';
    if (_suggestedConnections.length) {
        suggestionsHTML = _suggestedConnections.map((s, i) => {
            const pct = Math.round(s.match_score * 100);
            const alreadyAdded = _pendingConnections.some(p => p.target_id === s.vertex_id || p.source_id === s.vertex_id);
            const acceptLabel = alreadyAdded ? '✓ Added' : 'Accept';
            const acceptClass = alreadyAdded ? 'create-btn--accepted' : 'create-btn--accept';

            const reasonsHTML = s.match_reasons.map(r => `<span class="suggestion-reason">${escapeHtml(r)}</span>`).join('');

            const depTypeOptions = depTypes.map(t =>
                `<option value="${t}"${t === s.suggested_edge.dependency_type ? ' selected' : ''}>${t}</option>`
            ).join('');

            return `
                <div class="suggestion-card" data-idx="${i}">
                    <div class="suggestion-header">
                        <span class="suggestion-score">${pct}%</span>
                        <span class="suggestion-name">${escapeHtml(s.vertex_name)}</span>
                    </div>
                    <div class="suggestion-reasons">${reasonsHTML}</div>
                    <div class="suggestion-edge-config">
                        <div class="create-field-row compact">
                            <div class="create-field">
                                <label>Type</label>
                                <select id="suggestType_${i}" class="create-sm-select">${depTypeOptions}</select>
                            </div>
                            <div class="create-field">
                                <label>Strength</label>
                                <div class="create-slider-row compact">
                                    <input type="range" id="suggestStr_${i}" min="1" max="5" value="${s.suggested_edge.strength}" oninput="document.getElementById('suggestStrVal_${i}').textContent=this.value">
                                    <span id="suggestStrVal_${i}">${s.suggested_edge.strength}</span>
                                </div>
                            </div>
                        </div>
                        <div class="create-field-row compact">
                            <div class="create-field">
                                <label>Direction</label>
                                <div class="create-radio-group compact">
                                    <label class="create-radio"><input type="radio" name="suggestDir_${i}" value="outgoing" ${s.suggested_edge.direction === 'outgoing' ? 'checked' : ''}><span>This → Target</span></label>
                                    <label class="create-radio"><input type="radio" name="suggestDir_${i}" value="incoming" ${s.suggested_edge.direction !== 'outgoing' ? 'checked' : ''}><span>Target → This</span></label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="suggestion-actions">
                        <button class="${acceptClass}" title="Accept this suggested connection" onclick="_acceptSuggestion(${i})" ${alreadyAdded ? 'disabled' : ''}>${acceptLabel}</button>
                        <button class="create-btn--dismiss" title="Dismiss this suggestion" onclick="_dismissSuggestion(${i})">Dismiss</button>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        suggestionsHTML = '<div class="create-empty">No recommendations found. Add connections manually below.</div>';
    }

    // Build pending connections list
    let pendingHTML = '';
    if (_pendingConnections.length) {
        pendingHTML = `<div class="create-section-title">Pending Connections (${_pendingConnections.length})</div>` +
            _pendingConnections.map((c, i) => {
                const arrow = c.direction === 'outgoing' ? '→' : '←';
                return `<div class="pending-connection">
                    <span class="pending-arrow">${arrow}</span>
                    <span class="pending-name">${escapeHtml(c.target_name || c.source_name || '?')}</span>
                    <span class="dep-type-badge dep-type-${c.dependency_type}">${c.dependency_type}</span>
                    <span class="pending-strength">str=${c.strength}</span>
                    <button class="pending-remove" onclick="_removePending(${i})" title="Remove">✕</button>
                </div>`;
            }).join('');
    }

    // Manual connection search
    const depTypeOptionsManual = depTypes.map(t =>
        `<option value="${t}">${t}</option>`
    ).join('');

    // Build edge label options dynamically
    const edgeLabelOptions = edgeLabels.map((l, i) =>
        `<option value="${l}"${i === 0 ? ' selected' : ''}>${l}</option>`
    ).join('');

    // Build node options for search (filter from current graph)
    body.innerHTML = `
        <div class="create-wizard">
            <div class="create-wizard-progress">
                <div class="wizard-step completed">1. Properties ✓</div>
                <div class="wizard-step-separator done"></div>
                <div class="wizard-step active">2. Connections</div>
            </div>

            <!-- System Recommendations -->
            <div class="create-section">
                <div class="create-section-title">Recommended Connections</div>
                <div class="suggestions-list">${suggestionsHTML}</div>
            </div>

            <!-- Manual Connection -->
            <div class="create-section">
                <div class="create-section-title">Manual Connection</div>
                <div class="manual-connection-form">
                    <div class="create-field">
                        <label for="manualTarget">Search target node</label>
                        <input type="text" id="manualTarget" placeholder="Type to search nodes..." autocomplete="off" oninput="_onManualTargetInput(this.value)">
                        <div class="manual-target-results" id="manualTargetResults"></div>
                        <input type="hidden" id="manualTargetId" value="">
                        <input type="hidden" id="manualTargetName" value="">
                    </div>
                    <div class="create-field-row compact">
                        <div class="create-field">
                            <label for="manualEdgeLabel">Edge label</label>
                            <select id="manualEdgeLabel">
                                ${edgeLabelOptions}
                            </select>
                        </div>
                        <div class="create-field">
                            <label for="manualDepType">Dependency type</label>
                            <select id="manualDepType">${depTypeOptionsManual}</select>
                        </div>
                    </div>
                    <div class="create-field-row compact">
                        <div class="create-field">
                            <label>Direction</label>
                            <div class="create-radio-group compact">
                                <label class="create-radio"><input type="radio" name="manualDir" value="outgoing" checked><span>This → Target</span></label>
                                <label class="create-radio"><input type="radio" name="manualDir" value="incoming"><span>Target → This</span></label>
                            </div>
                        </div>
                        <div class="create-field">
                            <label>Strength</label>
                            <div class="create-slider-row compact">
                                <input type="range" id="manualStrength" min="1" max="5" value="3" oninput="document.getElementById('manualStrVal').textContent=this.value">
                                <span id="manualStrVal">3</span>
                            </div>
                        </div>
                    </div>
                    <div class="create-field">
                        <label for="manualRationale">Rationale</label>
                        <input type="text" id="manualRationale" placeholder="Why are these rules related?">
                    </div>
                    <div class="create-field">
                        <label for="manualImpact">Impact if fails</label>
                        <input type="text" id="manualImpact" placeholder="What happens if this dependency breaks?">
                    </div>
                    <button class="create-btn create-btn--add" title="Manually add a connection" onclick="_addManualConnection()">+ Add Connection</button>
                </div>
            </div>

            <!-- Pending -->
            <div class="create-section" id="pendingSection">
                ${pendingHTML}
            </div>

            <!-- Actions -->
            <div class="create-actions">
                <button class="create-btn create-btn--cancel" title="Go back to properties step" onclick="_backToStep1()">← Back</button>
                <button class="create-btn create-btn--submit" title="Create the node and all pending connections" onclick="_submitCreate()">Create Node${_pendingConnections.length ? ` + ${_pendingConnections.length} Connection${_pendingConnections.length > 1 ? 's' : ''}` : ''}</button>
            </div>
        </div>
    `;
}

// ── Manual Target Search ─────────────────────

const _onManualTargetInput = debounce(function (query) {
    const container = document.getElementById('manualTargetResults');
    if (!container) return;
    if (!query || query.length < 2) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }

    const q = query.toLowerCase();
    let matches = [];
    if (currentGraphData?.nodes) {
        matches = currentGraphData.nodes
            .filter(n =>
                (n.name || '').toLowerCase().includes(q) ||
                (n.rule_type || '').toLowerCase().includes(q) ||
                (n.id || '').toLowerCase().includes(q)
            )
            .slice(0, 8);
    }

    if (!matches.length) {
        container.innerHTML = '<div class="manual-target-empty">No matching nodes</div>';
        container.style.display = 'block';
        return;
    }

    container.innerHTML = matches.map(n => {
        const typeColor = TYPE_COLORS[n.rule_type] || TYPE_COLORS[n.label] || DEFAULT_COLOR;
        return `<div class="manual-target-item" onclick="_selectManualTarget('${escapeHtml(String(n.id))}', '${escapeHtml(String(n.name)).replace(/'/g, "&#39;")}')">
            <span class="manual-target-dot" style="background:${typeColor}"></span>
            <span class="manual-target-name">${escapeHtml(truncate(n.name, 40))}</span>
            <span class="manual-target-type">${n.rule_type || n.label}</span>
        </div>`;
    }).join('');
    container.style.display = 'block';
}, 200);

function _selectManualTarget(id, name) {
    document.getElementById('manualTargetId').value = id;
    document.getElementById('manualTargetName').value = name;
    document.getElementById('manualTarget').value = name;
    document.getElementById('manualTargetResults').style.display = 'none';
}

function _closeManualDropdown(e) {
    const results = document.getElementById('manualTargetResults');
    const input = document.getElementById('manualTarget');
    if (results && input && !results.contains(e.target) && e.target !== input) {
        results.style.display = 'none';
    }
}

// ── Connection Management ────────────────────

function _acceptSuggestion(idx) {
    const s = _suggestedConnections[idx];
    if (!s) return;

    const depType = document.getElementById(`suggestType_${idx}`)?.value || s.suggested_edge.dependency_type;
    const strength = parseInt(document.getElementById(`suggestStr_${idx}`)?.value || s.suggested_edge.strength);
    const direction = document.querySelector(`input[name="suggestDir_${idx}"]:checked`)?.value || s.suggested_edge.direction;

    const conn = {
        direction,
        edge_label: 'depends_on',
        dependency_type: depType,
        strength,
        rationale: s.suggested_edge.rationale,
        impact_if_fails: '',
    };

    if (direction === 'outgoing') {
        conn.target_id = s.vertex_id;
        conn.target_name = s.vertex_name;
    } else {
        conn.source_id = s.vertex_id;
        conn.source_name = s.vertex_name;
    }

    _pendingConnections.push(conn);
    _renderStep2Content();
    showToast(`Added: ${s.vertex_name}`, ICONS.success);
}

function _dismissSuggestion(idx) {
    _suggestedConnections.splice(idx, 1);
    _renderStep2Content();
}

function _addManualConnection() {
    const targetId = document.getElementById('manualTargetId')?.value;
    const targetName = document.getElementById('manualTargetName')?.value;
    if (!targetId) {
        showToast('Please select a target node first', ICONS.warningRose);
        return;
    }

    const direction = document.querySelector('input[name="manualDir"]:checked')?.value || 'outgoing';
    const conn = {
        direction,
        edge_label: document.getElementById('manualEdgeLabel')?.value || 'depends_on',
        dependency_type: document.getElementById('manualDepType')?.value || 'complementary',
        strength: parseInt(document.getElementById('manualStrength')?.value || '3'),
        rationale: document.getElementById('manualRationale')?.value?.trim() || '',
        impact_if_fails: document.getElementById('manualImpact')?.value?.trim() || '',
    };

    if (direction === 'outgoing') {
        conn.target_id = targetId;
        conn.target_name = targetName;
    } else {
        conn.source_id = targetId;
        conn.source_name = targetName;
    }

    _pendingConnections.push(conn);
    _renderStep2Content();
    showToast(`Added: ${targetName}`, ICONS.success);
}

function _removePending(idx) {
    const removed = _pendingConnections.splice(idx, 1);
    _renderStep2Content();
    if (removed.length) {
        showToast('Connection removed', ICONS.trashMuted);
    }
}

function _backToStep1() {
    _createWizardStep = 1;
    _renderCreateStep1();
}

// ── Submit Create ────────────────────────────

async function _submitCreate() {
    const submitBtn = document.querySelector('.create-btn--submit');
    const originalBtnText = submitBtn?.textContent || 'Create Node';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating...';
    }

    const d = _createVertexData;
    const graph = currentGraphName || 'g';

    // Build properties
    const properties = { name: d.name, content: d.content };
    const optionalStr = ['rule_id', 'rule_name', 'rule_type', 'description', 'conditions',
        'consequences', 'exceptions', 'reference', 'review_reason',
        'entity_or_relationship', 'entity_type', 'extraction_notes', 'category'];
    for (const f of optionalStr) {
        if (d[f]) properties[f] = d[f];
    }
    if (d.mandatory) properties.mandatory = true;
    if (d.requires_review) properties.requires_review = true;
    if (d.confidence_score !== undefined) properties.confidence_score = d.confidence_score;

    try {
        // 1. Create vertex
        const vResp = await fetch('/api/vertex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                graph_name: graph,
                label: d.label || 'business_rule',
                properties,
            }),
        });

        if (!vResp.ok) {
            const err = await vResp.json();
            const msg = (err.errors || [err.error || 'Unknown error']).join(', ');
            showToast(msg, ICONS.error);
            if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalBtnText; }
            return;
        }

        const created = await vResp.json();
        const newId = created.id;

        // 2. Create edges
        let edgeCount = 0;
        for (const conn of _pendingConnections) {
            const edgeBody = {
                graph_name: graph,
                label: conn.edge_label || 'depends_on',
                properties: {
                    dependency_type: conn.dependency_type,
                    strength: conn.strength,
                    rationale: conn.rationale || '',
                    impact_if_fails: conn.impact_if_fails || '',
                },
            };

            if (conn.direction === 'outgoing') {
                edgeBody.source_id = newId;
                edgeBody.target_id = conn.target_id;
            } else {
                edgeBody.source_id = conn.source_id;
                edgeBody.target_id = newId;
            }

            try {
                const eResp = await fetch('/api/edge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(edgeBody),
                });
                if (eResp.ok) edgeCount++;
            } catch (e) {
                console.warn('Edge creation failed:', e);
            }
        }

        // 3. Refresh graph
        closeCreatePanel();
        const connText = edgeCount > 0 ? ` with ${edgeCount} connection${edgeCount > 1 ? 's' : ''}` : '';
        showToast(`Created "${d.name}"${connText}`, ICONS.success);

        // Reload graph and navigate to new node
        try {
            const graphResp = await fetch(`/api/graph?graph_name=${encodeURIComponent(graph)}`);
            if (graphResp.ok) {
                const graphData = await graphResp.json();
                renderGraph(graphData);
                // Navigate to the new node after a short delay
                setTimeout(() => navigateToNode(newId), 500);
            }
        } catch (e) {
            console.warn('Graph refresh failed:', e);
        }

    } catch (exc) {
        showToast(`Error: ${exc.message}`, ICONS.error);
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalBtnText; }
    }
}
