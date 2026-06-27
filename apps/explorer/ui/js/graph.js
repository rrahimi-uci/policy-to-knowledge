/* ── Graph Visualization ───────────────────── */
const tooltip = document.getElementById('tooltip');

// ── Minimap Setup ─────────────────────────────
const minimapCanvas = document.getElementById('minimap');
const minimapCtx = minimapCanvas ? minimapCanvas.getContext('2d') : null;
const MINIMAP_W = 160, MINIMAP_H = 120;
let _minimapRAF = null;
let _minimapBounds = null;

(function initMinimapCanvas() {
    if (!minimapCanvas || !minimapCtx) return;
    const dpr = window.devicePixelRatio || 1;
    minimapCanvas.width = MINIMAP_W * dpr;
    minimapCanvas.height = MINIMAP_H * dpr;
    minimapCtx.scale(dpr, dpr);

    // Click on minimap to pan the main view
    minimapCanvas.addEventListener('click', (e) => {
        if (!_minimapBounds || !svg || !zoomBehavior) return;
        const rect = minimapCanvas.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (MINIMAP_W / rect.width);
        const my = (e.clientY - rect.top) * (MINIMAP_H / rect.height);
        const { minX, minY, scale, ox, oy } = _minimapBounds;
        const gx = (mx - ox) / scale + minX;
        const gy = (my - oy) / scale + minY;
        const container = document.getElementById('graphContainer');
        const W = container.clientWidth;
        const H = container.clientHeight;
        const t = d3.zoomTransform(svg.node());
        svg.transition().duration(300).call(
            zoomBehavior.transform,
            d3.zoomIdentity.translate(W / 2 - gx * t.k, H / 2 - gy * t.k).scale(t.k)
        );
    });
})();

function initSvg() {
    const container = document.getElementById('graphContainer');
    document.getElementById('graphEmpty')?.remove();

    svg = d3.select('#graphContainer')
        .append('svg')
        .attr('width', '100%')
        .attr('height', '100%');

    // Arrow markers (created dynamically per edge type in _ensureArrowMarker)
    svg.append('defs').attr('id', 'arrowDefs');

    zoomBehavior = d3.zoom()
        .scaleExtent([0.05, 6])
        .on('zoom', e => {
            gRoot.attr('transform', e.transform);
            scheduleMinimapUpdate();
        });

    svg.call(zoomBehavior);
    gRoot = svg.append('g');

    // Click on background dismisses any emphasized edge label
    svg.on('click', () => {
        closeEdgeDetail();
        gRoot.selectAll('.graph-link-label.emphasized').classed('emphasized', false);
    });
}

// ── Edge color mapping ────────────────────────
const _EDGE_COLORS = {
    depends_on: 'rgba(99,102,241,0.35)',
    belongs_to_category: 'rgba(52,211,153,0.25)',
};
const _EDGE_PALETTE = [
    'rgba(251,191,36,0.35)', 'rgba(251,113,133,0.35)',
    'rgba(167,139,250,0.35)', 'rgba(56,189,248,0.35)',
    'rgba(163,230,53,0.35)', 'rgba(249,115,22,0.35)',
];
let _edgeColorIdx = 0;

function _edgeColor(label) {
    if (!_EDGE_COLORS[label]) {
        _EDGE_COLORS[label] = _EDGE_PALETTE[_edgeColorIdx % _EDGE_PALETTE.length];
        _edgeColorIdx++;
    }
    return _EDGE_COLORS[label];
}

const _createdMarkers = new Set();

function _ensureArrowMarker(edgeLabel) {
    if (_createdMarkers.has(edgeLabel)) return;
    const defs = d3.select('#arrowDefs');
    if (defs.empty()) return;
    const fill = _edgeColor(edgeLabel).replace(/0\.\d+\)$/, '0.5)');
    defs.append('marker')
        .attr('id', `arrow-${edgeLabel}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 20).attr('refY', 0)
        .attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4Z')
        .attr('class', 'graph-arrow')
        .attr('fill', fill);
    _createdMarkers.add(edgeLabel);
}

// ── Dynamic Legend Builder ────────────────────
function _buildLegend(data) {
    // Collect node types from data
    const nodeTypes = new Set();
    let hasCategory = false;
    data.nodes.forEach(n => {
        if (n.label === 'entity_category') {
            hasCategory = true;
        } else if (n.rule_type) {
            nodeTypes.add(n.rule_type);
        }
    });

    // Collect edge types from data
    const edgeTypes = new Set();
    data.links.forEach(l => { if (l.label) edgeTypes.add(l.label); });

    // Build node type legend rows
    const ntContainer = document.getElementById('legendNodeTypes');
    if (ntContainer) {
        ntContainer.innerHTML = '';
        Array.from(nodeTypes).sort().forEach(type => {
            const color = nodeColorByType(type);
            const row = document.createElement('div');
            row.className = 'legend-row';
            row.dataset.filter = type;
            row.onclick = function () { toggleLegendFilter(this, type); };
            row.innerHTML = `<div class="legend-dot" style="background:${color}"></div> ${type}`;
            ntContainer.appendChild(row);
        });
        if (hasCategory) {
            const row = document.createElement('div');
            row.className = 'legend-row';
            row.dataset.filter = 'category';
            row.onclick = function () { toggleLegendFilter(this, 'category'); };
            row.innerHTML = `<div class="legend-dot" style="background:${TYPE_COLORS.entity_category}"></div> category`;
            ntContainer.appendChild(row);
        }
    }

    // Build edge type legend rows
    const etContainer = document.getElementById('legendEdgeTypes');
    if (etContainer) {
        etContainer.innerHTML = '';
        Array.from(edgeTypes).sort().forEach(label => {
            const color = _edgeColor(label);
            const row = document.createElement('div');
            row.className = 'legend-row';
            row.innerHTML = `<div class="legend-edge-line" style="background:${color}; opacity:0.7"></div> ${label}`;
            etContainer.appendChild(row);
        });
    }
}

function renderGraph(data) {
    if (!data?.nodes?.length) return;
    currentGraphData = data;
    // Track which graph we're viewing
    if (data.graph_name) {
        currentGraphName = data.graph_name;
        // Invalidate schema cache so create-form picks up new graph's types
        if (typeof _schemaCache !== 'undefined') _schemaCache = null;
    }

    document.getElementById('nodeCount').textContent = data.nodes.length;
    document.getElementById('linkCount').textContent = data.links.length;
    document.getElementById('graphLegend').hidden = false;

    // Build legend dynamically from graph data
    _buildLegend(data);

    // Show active graph name badge
    const gBadge = document.getElementById('graphNameBadge');
    if (gBadge) {
        gBadge.textContent = currentGraphName;
        gBadge.classList.add('visible');
    }

    if (!svg) initSvg();

    gRoot.selectAll('*').remove();

    const container = document.getElementById('graphContainer');
    const W = container.clientWidth;
    const H = container.clientHeight;

    // Calculate node degrees for sizing
    const degreeMap = {};
    data.links.forEach(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        degreeMap[s] = (degreeMap[s] || 0) + 1;
        degreeMap[t] = (degreeMap[t] || 0) + 1;
    });
    data.nodes.forEach(n => { n._degree = degreeMap[n.id] || 0; });

    simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(d => d.label === 'entity_category' ? -600 : -120))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collision', d3.forceCollide().radius(d => dynRadius(d) + 4))
        .force('x', d3.forceX(W / 2).strength(0.03))
        .force('y', d3.forceY(H / 2).strength(0.03));

    // Links – ensure arrow markers exist for all edge types
    const edgeLabels = new Set(data.links.map(l => l.label).filter(Boolean));
    edgeLabels.forEach(lbl => _ensureArrowMarker(lbl));

    const linkGroup = gRoot.append('g');
    const link = linkGroup
        .selectAll('line')
        .data(data.links)
        .join('line')
        .attr('class', d => `graph-link ${d.label}`)
        .attr('stroke', d => _edgeColor(d.label))
        .attr('stroke-width', d => d.label === 'depends_on' ? 1.2 : 0.8)
        .attr('marker-end', d => `url(#arrow-${d.label})`);

    // Invisible wider hit-area for edge clicking
    const linkHit = linkGroup
        .selectAll('.graph-link-hit')
        .data(data.links)
        .join('line')
        .attr('class', 'graph-link-hit')
        .attr('stroke', 'transparent')
        .attr('stroke-width', 12)
        .style('cursor', 'pointer')
        .on('click', onEdgeClick)
        .on('mouseover', onEdgeHover)
        .on('mouseout', onEdgeOut);

    // Edge labels (show dependency_type on depends_on edges)
    const edgeLabel = gRoot.append('g')
        .selectAll('text')
        .data(data.links.filter(d => d.label === 'depends_on' && d.dependency_type))
        .join('text')
        .attr('class', 'graph-link-label')
        .text(d => d.dependency_type)
        .on('click', function (event, d) {
            event.stopPropagation();
            onEdgeClick(event, d);
        });

    // Nodes – invisible larger hit circle underneath for easier clicking
    const nodeGroup = gRoot.append('g');
    nodeGroup.selectAll('.graph-node-hit')
        .data(data.nodes)
        .join('circle')
        .attr('class', 'graph-node-hit')
        .attr('r', d => dynRadius(d) + 6)
        .attr('fill', 'transparent')
        .style('cursor', 'pointer')
        .on('mouseover', onNodeHover)
        .on('mouseout', onNodeOut)
        .on('click', onNodeClick)
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );
    const node = nodeGroup
        .selectAll('.graph-node')
        .data(data.nodes)
        .join('circle')
        .attr('class', 'graph-node')
        .attr('r', d => dynRadius(d))
        .attr('fill', d => nodeColor(d))
        .attr('stroke', d => d3.color(nodeColor(d)).darker(0.8))
        .on('mouseover', onNodeHover)
        .on('mouseout', onNodeOut)
        .on('click', onNodeClick)
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    // Labels — show all or filtered based on toggle
    const labelFilter = showAllLabels
        ? data.nodes
        : data.nodes.filter(d => d.label === 'entity_category' || d._degree >= 5);
    const label = gRoot.append('g').attr('class', 'graph-labels-group')
        .selectAll('text')
        .data(labelFilter)
        .join('text')
        .attr('class', 'graph-node-label')
        .attr('dy', d => dynRadius(d) + 12)
        .attr('text-anchor', 'middle')
        .text(d => truncate(d.name, 22));

    simulation.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

        linkHit.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

        edgeLabel.attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);

        nodeGroup.selectAll('.graph-node-hit').attr('cx', d => d.x).attr('cy', d => d.y);
        node.attr('cx', d => d.x).attr('cy', d => d.y);
        gRoot.selectAll('.graph-node-label').attr('x', d => d.x).attr('y', d => d.y);
        scheduleMinimapUpdate();
    });

    // Auto fit after a moment
    setTimeout(() => fitView(), 1500);
}

function dynRadius(d) {
    if (d.label === 'entity_category') return 14;
    const base = 5;
    return base + Math.min(d._degree || 0, 12) * 0.8;
}

// ── Tooltip ───────────────────────────────────
function onNodeHover(event, d) {
    let html = `<div class="tooltip-name">${escapeHtml(d.name || d.id)}</div>`;
    html += `<div class="tooltip-meta">`;
    html += `Type: <span>${d.label}</span>`;
    if (d.rule_type) html += ` &middot; ${d.rule_type}`;
    if (d.category) html += `<br>Category: <span>${d.category}</span>`;
    if (d.mandatory) html += `<br><span style="color:var(--amber)">Mandatory</span>`;
    html += `<br>Connections: <span>${d._degree || 0}</span>`;
    html += `</div>`;
    tooltip.innerHTML = html;
    tooltip.style.left = (event.clientX + 12) + 'px';
    tooltip.style.top = (event.clientY + 12) + 'px';
    tooltip.classList.add('show');
}

function onNodeOut() { tooltip.classList.remove('show'); }

// ── Node Click -> Detail Panel ────────────────
async function onNodeClick(event, d) {
    event.stopPropagation();
    tooltip.classList.remove('show');

    // Close edge detail if open
    closeEdgeDetail();

    pushNavHistory();

    // Highlight selected
    d3.selectAll('.graph-node').classed('selected', false);
    if (event.currentTarget) d3.select(event.currentTarget).classed('selected', true);
    selectedNodeId = d.id;

    // Update URL hash for deep linking
    history.replaceState(null, '', '#' + d.id);

    const panel = document.getElementById('detailPanel');
    const body = document.getElementById('detailBody');
    const title = document.getElementById('detailTitle');
    const badge = document.getElementById('detailBadge');

    title.textContent = d.name || d.id;
    badge.textContent = d.label;
    badge.className = 'detail-label-badge ' +
        (d.label === 'entity_category' ? 'badge-category' : 'badge-rule');

    body.innerHTML = showDetailSkeleton();
    panel.classList.add('open');

    try {
        const res = await fetch(`/api/vertex/${d.id}?graph_name=${currentGraphName}`);
        const info = await res.json();
        if (!res.ok) throw new Error(info.error || 'Failed to load');
        renderDetail(info);
    } catch (err) {
        body.innerHTML = `<div style="color:var(--rose);text-align:center;padding:2rem">Error: ${escapeHtml(err.message)}</div>`;
    }
}

// ── Edge Hover / Click ────────────────────────
function onEdgeHover(event, d) {
    const srcName = typeof d.source === 'object' ? (d.source.name || d.source.id) : d.source;
    const tgtName = typeof d.target === 'object' ? (d.target.name || d.target.id) : d.target;
    let html = `<div class="tooltip-name" style="font-size:0.72rem">${escapeHtml(String(d.label || 'edge'))}</div>`;
    html += `<div class="tooltip-meta">`;
    html += `${escapeHtml(truncate(String(srcName), 28))} → ${escapeHtml(truncate(String(tgtName), 28))}`;
    if (d.dependency_type) html += `<br>Type: <span>${escapeHtml(d.dependency_type)}</span>`;
    if (d.strength) html += `<br>Strength: <span>${d.strength}</span>`;
    html += `<br><span style="color:var(--accent-light);font-size:0.65rem">Click for details</span>`;
    html += `</div>`;
    tooltip.innerHTML = html;
    tooltip.style.left = (event.clientX + 12) + 'px';
    tooltip.style.top = (event.clientY + 12) + 'px';
    tooltip.classList.add('show');

    // Highlight the edge
    if (gRoot) {
        gRoot.selectAll('.graph-link').classed('edge-hover', false);
        gRoot.selectAll('.graph-link').filter(l => l === d).classed('edge-hover', true);
    }
}

function onEdgeOut(event, d) {
    tooltip.classList.remove('show');
    if (gRoot) gRoot.selectAll('.graph-link').classed('edge-hover', false);
}

function onEdgeClick(event, d) {
    event.stopPropagation();
    tooltip.classList.remove('show');

    // Deselect any node selection
    d3.selectAll('.graph-node').classed('selected', false);
    selectedNodeId = null;
    document.getElementById('detailPanel').classList.remove('open');

    // Highlight the clicked edge
    gRoot.selectAll('.graph-link').classed('edge-selected', false);
    gRoot.selectAll('.graph-link').filter(l => l === d).classed('edge-selected', true);

    // Build edge identifier
    const srcId = typeof d.source === 'object' ? d.source.id : d.source;
    const tgtId = typeof d.target === 'object' ? d.target.id : d.target;
    const edgeId = d.id || `${srcId}--${d.label}--${tgtId}`;
    selectedEdgeId = edgeId;

    // Open edge detail panel
    const panel = document.getElementById('edgeDetailPanel');
    const title = document.getElementById('edgeDetailTitle');
    const badge = document.getElementById('edgeDetailBadge');
    const body = document.getElementById('edgeDetailBody');

    const srcName = typeof d.source === 'object' ? (d.source.name || srcId) : srcId;
    const tgtName = typeof d.target === 'object' ? (d.target.name || tgtId) : tgtId;

    title.textContent = d.dependency_type || d.label || 'Edge';
    badge.textContent = d.label;
    badge.className = 'detail-label-badge badge-edge';

    renderEdgeDetail(d, edgeId, srcId, tgtId, srcName, tgtName);
    panel.classList.add('open');
}

function navigateToNode(nodeId) {
    if (!currentGraphData) return;
    const node = currentGraphData.nodes.find(n => n.id === String(nodeId));
    if (node) {
        // Zoom close to the node
        const container = document.getElementById('graphContainer');
        const cx = container.clientWidth / 2;
        const cy = container.clientHeight / 2;
        const scale = 3.5;
        const tx = cx - node.x * scale;
        const ty = cy - node.y * scale;
        svg.transition().duration(800).call(
            zoomBehavior.transform,
            d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
        // Show detail panel
        onNodeClick({ stopPropagation: () => { }, currentTarget: null, clientX: cx, clientY: cy }, node);
        // Highlight (select) the target node
        d3.selectAll('.graph-node').classed('selected', n => n.id === String(nodeId));
        // 3-blink effect: pulse radius + glow stroke to visually identify the node
        // NOTE: .graph-node elements ARE the circles (not wrappers), so no .select('circle')
        const _blinkTarget = d3.selectAll('.graph-node')
            .filter(n => n.id === String(nodeId));
        if (!_blinkTarget.empty()) {
            const _origR = +_blinkTarget.attr('r');
            const _origStroke = _blinkTarget.style('stroke') || '';
            _blinkTarget
                .style('stroke', '#facc15').style('stroke-width', '4px')
                .transition().duration(160).attr('r', _origR * 2.1)
                .transition().duration(160).attr('r', _origR)
                .transition().duration(160).attr('r', _origR * 2.1)
                .transition().duration(160).attr('r', _origR)
                .transition().duration(160).attr('r', _origR * 2.1)
                .transition().duration(300).attr('r', _origR)
                .on('end', () => {
                    _blinkTarget.style('stroke', _origStroke).style('stroke-width', null);
                });
        }
    }
}

// ── Graph Controls ────────────────────────────
function zoomIn() {
    if (!svg) return;
    svg.transition().duration(300).call(zoomBehavior.scaleBy, 1.4);
}

function zoomOut() {
    if (!svg) return;
    svg.transition().duration(300).call(zoomBehavior.scaleBy, 0.7);
}

function resetView() {
    if (!svg) return;
    fitView();
}

function fitView() {
    if (!svg || !currentGraphData?.nodes?.length) return;
    const container = document.getElementById('graphContainer');
    const W = container.clientWidth;
    const H = container.clientHeight;

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    currentGraphData.nodes.forEach(n => {
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
    });

    const gW = maxX - minX || 1;
    const gH = maxY - minY || 1;
    const pad = 60;
    const scale = Math.min((W - pad * 2) / gW, (H - pad * 2) / gH, 3);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;

    svg.transition().duration(750).call(
        zoomBehavior.transform,
        d3.zoomIdentity
            .translate(W / 2, H / 2)
            .scale(scale)
            .translate(-cx, -cy)
    );
}

// ── Minimap Rendering ────────────────────────
function scheduleMinimapUpdate() {
    if (_minimapRAF) return;
    _minimapRAF = requestAnimationFrame(() => {
        _minimapRAF = null;
        renderMinimap();
    });
}

function renderMinimap() {
    if (!minimapCtx || !currentGraphData?.nodes?.length) {
        if (minimapCanvas) minimapCanvas.style.display = 'none';
        return;
    }
    if (currentGraphData.nodes.length < 20) {
        minimapCanvas.style.display = 'none';
        return;
    }
    minimapCanvas.style.display = 'block';

    const nodes = currentGraphData.nodes;
    const links = currentGraphData.links;
    const ctx = minimapCtx;

    // Compute bounds
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of nodes) {
        if (n.x == null) continue;
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
    }
    if (minX === Infinity) return; // no positioned nodes yet

    const gW = (maxX - minX) || 1;
    const gH = (maxY - minY) || 1;
    const pad = 8;
    const scale = Math.min((MINIMAP_W - pad * 2) / gW, (MINIMAP_H - pad * 2) / gH);
    const ox = (MINIMAP_W - gW * scale) / 2;
    const oy = (MINIMAP_H - gH * scale) / 2;
    _minimapBounds = { minX, minY, scale, ox, oy };

    ctx.clearRect(0, 0, MINIMAP_W, MINIMAP_H);

    // Edges (faint lines)
    ctx.strokeStyle = 'rgba(99,102,241,0.12)';
    ctx.lineWidth = 0.5;
    for (const l of links) {
        const s = typeof l.source === 'object' ? l.source : null;
        const t = typeof l.target === 'object' ? l.target : null;
        if (!s || !t || s.x == null || t.x == null) continue;
        ctx.beginPath();
        ctx.moveTo((s.x - minX) * scale + ox, (s.y - minY) * scale + oy);
        ctx.lineTo((t.x - minX) * scale + ox, (t.y - minY) * scale + oy);
        ctx.stroke();
    }

    // Nodes
    ctx.globalAlpha = 0.85;
    for (const n of nodes) {
        if (n.x == null) continue;
        ctx.fillStyle = nodeColor(n);
        ctx.beginPath();
        ctx.arc(
            (n.x - minX) * scale + ox,
            (n.y - minY) * scale + oy,
            Math.max(1.5, dynRadius(n) * scale * 0.5),
            0, Math.PI * 2
        );
        ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Viewport rectangle
    if (svg) {
        const container = document.getElementById('graphContainer');
        const W = container.clientWidth;
        const H = container.clientHeight;
        const t = d3.zoomTransform(svg.node());
        const vx = ((-t.x) / t.k - minX) * scale + ox;
        const vy = ((-t.y) / t.k - minY) * scale + oy;
        const vw = (W / t.k) * scale;
        const vh = (H / t.k) * scale;
        ctx.fillStyle = 'rgba(99,102,241,0.08)';
        ctx.fillRect(vx, vy, vw, vh);
        ctx.strokeStyle = 'rgba(255,255,255,0.5)';
        ctx.lineWidth = 1;
        ctx.strokeRect(vx, vy, vw, vh);
    }
}

function clearGraphSearch() {
    const graphSearchInput = document.getElementById('graphSearchInput');
    const graphSearchClear = document.getElementById('graphSearchClear');
    graphSearchInput.value = '';
    graphSearchClear.style.display = 'none';
    d3.selectAll('.graph-node').classed('search-dim', false);
    d3.selectAll('.graph-node-label').classed('search-dim', false);
    d3.selectAll('.graph-link').classed('search-dim', false);
    const countEl = document.getElementById('searchMatchCount');
    if (countEl) countEl.classList.remove('visible');
    const emptyEl = document.getElementById('graphSearchEmpty');
    if (emptyEl) { emptyEl.classList.remove('visible'); emptyEl.innerHTML = ''; }
}

// ── Toggle All Node Labels ───────────────────
function toggleAllLabels() {
    showAllLabels = !showAllLabels;
    const btn = document.getElementById('toggleLabelsBtn');
    if (btn) btn.classList.toggle('labels-active', showAllLabels);
    if (!currentGraphData || !gRoot) return;
    // Remove existing labels and re-draw
    gRoot.select('.graph-labels-group').remove();
    const data = currentGraphData;
    const labelFilter = showAllLabels
        ? data.nodes
        : data.nodes.filter(d => d.label === 'entity_category' || d._degree >= 5);
    gRoot.append('g').attr('class', 'graph-labels-group')
        .selectAll('text')
        .data(labelFilter)
        .join('text')
        .attr('class', 'graph-node-label')
        .attr('dy', d => dynRadius(d) + 12)
        .attr('text-anchor', 'middle')
        .text(d => truncate(d.name, 22))
        .attr('x', d => d.x)
        .attr('y', d => d.y);
}

// ── Graph Export ─────────────────────────────
function toggleExportMenu() {
    const menu = document.getElementById('exportMenu');
    if (menu) menu.classList.toggle('open');
}

// ── Global: close any open dropdown on outside click ──
document.addEventListener('click', function (e) {
    document.querySelectorAll('.tb-dropdown-menu.open').forEach(menu => {
        if (!e.target.closest('.tb-dropdown')) {
            menu.classList.remove('open');
        }
    });
});

function exportGraphSVG() {
    if (!svg) return;
    document.getElementById('exportMenu')?.classList.remove('open');
    const serializer = new XMLSerializer();
    const svgStr = serializer.serializeToString(svg.node());
    const blob = new Blob([svgStr], { type: 'image/svg+xml' });
    _downloadBlob(blob, `p2k-graph-${currentGraphName}.svg`);
    showToast('SVG downloaded', ICONS.download);
}

function exportGraphPNG() {
    if (!svg) return;
    document.getElementById('exportMenu')?.classList.remove('open');
    try {
        const serializer = new XMLSerializer();
        const svgStr = serializer.serializeToString(svg.node());
        const canvas = document.createElement('canvas');
        const container = document.getElementById('graphContainer');
        const dpr = window.devicePixelRatio || 1;
        canvas.width = container.clientWidth * dpr;
        canvas.height = container.clientHeight * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const img = new Image();
        img.onerror = () => showToast('PNG export failed', ICONS.error);
        img.onload = () => {
            ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--bg-primary') || '#050816';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0, container.clientWidth, container.clientHeight);
            canvas.toBlob(blob => {
                _downloadBlob(blob, `p2k-graph-${currentGraphName}.png`);
                showToast('PNG downloaded', ICONS.download);
            }, 'image/png');
        };
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgStr);
    } catch (err) {
        console.error('PNG export failed:', err);
        showToast('PNG export failed', ICONS.error);
    }
}

function exportGraphJSON() {
    if (!currentGraphData) return;
    document.getElementById('exportMenu')?.classList.remove('open');
    // Skip D3 internal / simulation properties
    const _skipExport = new Set(['x', 'y', 'vx', 'vy', 'fx', 'fy', 'index', '_degree', '__proto__']);
    const exportData = {
        meta: {
            graph_name: currentGraphName,
            exported_at: new Date().toISOString(),
            exported_by: 'Assistant',
            node_count: currentGraphData.nodes.length,
            edge_count: currentGraphData.links.length,
        },
        nodes: currentGraphData.nodes.map(n => {
            const node = {};
            for (const [k, v] of Object.entries(n)) {
                if (_skipExport.has(k) || typeof v === 'function') continue;
                // Keep ALL values — objects, arrays, primitives
                node[k] = v;
            }
            // Merge persisted annotations
            const persisted = getNodeData(String(n.id));
            if (persisted.reviewed) node.review_status = persisted.reviewed;
            if (persisted.reviewHistory?.length) node.review_history = persisted.reviewHistory;
            if (persisted.versionHistory?.length) node.version_history = persisted.versionHistory;
            if (persisted.deleted) node.flagged_for_deletion = true;
            if (persisted.edits && Object.keys(persisted.edits).length) node.local_edits = persisted.edits;
            return node;
        }),
        edges: currentGraphData.links.map(l => {
            const edge = {};
            for (const [k, v] of Object.entries(l)) {
                if (_skipExport.has(k) || typeof v === 'function') continue;
                if (k === 'source' || k === 'target') {
                    edge[k] = typeof v === 'object' ? v.id : v;
                    continue;
                }
                // Keep ALL values — objects, arrays, primitives
                edge[k] = v;
            }
            return edge;
        }),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    _downloadBlob(blob, `p2k-graph-${currentGraphName}.json`);
    showToast('JSON exported with full details', ICONS.download);
}

function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

// ── Legend Filter ────────────────────────────
function clearLegendFilter() {
    activeLegendFilter = null;
    document.querySelectorAll('.legend-row').forEach(r => {
        r.classList.remove('active', 'dimmed');
    });
    const resetBtn = document.getElementById('legendResetBtn');
    if (resetBtn) resetBtn.hidden = true;
    d3.selectAll('.graph-node').classed('search-dim', false);
    d3.selectAll('.graph-node-label').classed('search-dim', false);
    d3.selectAll('.graph-link').classed('search-dim', false);
}

function toggleLegendFilter(el, type) {
    if (activeLegendFilter === type) {
        clearLegendFilter();
        return;
    }

    activeLegendFilter = type;
    document.querySelectorAll('.legend-row').forEach(r => {
        if (r.dataset.filter === type) {
            r.classList.add('active');
            r.classList.remove('dimmed');
        } else if (r.dataset.filter) {
            r.classList.remove('active');
            r.classList.add('dimmed');
        }
    });
    const resetBtn = document.getElementById('legendResetBtn');
    if (resetBtn) resetBtn.hidden = false;

    if (svg && currentGraphData) {
        const matchIds = new Set();
        currentGraphData.nodes.forEach(n => {
            const rt = n.rule_type || '';
            const lb = n.label || '';
            // Match by rule_type first; for 'category' match entity_category label
            if (rt === type || lb === type ||
                (type === 'category' && lb === 'entity_category')) {
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
    }
}
