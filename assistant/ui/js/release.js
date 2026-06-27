/* ── Release & Lock ──────────────────────────── */

// ── SVG icon constants (use central ICONS registry) ──
const _ICON_LOCKED  = ICONS.locked;
const _ICON_UNLOCK  = ICONS.unlock;

// ── State ────────────────────────────────────
let graphLocked = false;
let currentRelease = null;   // { id, version, title, ... }

// ── DOM helpers ──────────────────────────────
const _relOverlay = () => document.getElementById('releaseOverlay');
const _relForm    = () => document.getElementById('releaseForm');
const _lockBadge  = () => document.getElementById('lockBadge');
const _graphPanel = () => document.querySelector('.graph-panel');

// ══════════════════════════════════════════════
//  Graph-status check (called after every renderGraph)
// ══════════════════════════════════════════════
async function fetchGraphStatus() {
    if (!currentGraphName) return;
    try {
        const r = await fetch(`/api/graph/status?graph_name=${encodeURIComponent(currentGraphName)}`);
        if (!r.ok) return;
        const d = await r.json();
        applyLockState(d.locked, d.current_release_version, d);
    } catch { /* silently ignore – server may not support this yet */ }
}

function applyLockState(locked, version, detail) {
    graphLocked = locked;
    currentRelease = locked ? detail : null;
    const badge = _lockBadge();
    const panel = _graphPanel();

    if (badge) {
        if (locked) {
            badge.className = 'lock-badge locked';
            badge.innerHTML = '<span class="lock-badge-icon">' + _ICON_LOCKED + '</span> ' + _escVer(version);
            badge.title = 'Graph is locked at ' + _escVer(version) + ' — click to unlock';
        } else {
            badge.className = 'lock-badge unlocked';
            badge.innerHTML = '<span class="lock-badge-icon">' + _ICON_UNLOCK + '</span> Draft';
            badge.title = 'Graph is editable — click to view releases';
        }
    }

    // Add/remove `graph-locked` class on the panel to hide mutation UI via CSS
    if (panel) {
        panel.classList.toggle('graph-locked', !!locked);
    }

    // Enable/disable the release button
    const relBtn = document.getElementById('releaseBtn');
    if (relBtn) relBtn.disabled = locked;
}

function _escVer(v) { return v ? String(v).replace(/</g, '&lt;') : ''; }

// ══════════════════════════════════════════════
//  Release modal
// ══════════════════════════════════════════════
async function openReleaseModal() {
    if (graphLocked) { 
        showToast('Graph is locked — unlock first', _ICON_LOCKED); 
        return; 
    }

    const overlay = _relOverlay();
    if (!overlay) return;

    // Pre-fill stats
    const nc = document.getElementById('nodeCount')?.textContent || '0';
    const lc = document.getElementById('linkCount')?.textContent || '0';
    document.getElementById('releaseStats').textContent =
        `${nc} nodes · ${lc} edges will be snapshot`;

    // Auto-suggest next version
    await _suggestVersion();

    overlay.classList.add('open');
    setTimeout(() => document.getElementById('releaseVersion')?.focus(), 120);
}

function closeReleaseModal() {
    const overlay = _relOverlay();
    if (overlay) overlay.classList.remove('open');
}

async function _suggestVersion() {
    const inp = document.getElementById('releaseVersion');
    if (!inp) return;
    try {
        const r = await fetch(`/api/graph/releases?graph_name=${encodeURIComponent(currentGraphName)}`);
        if (!r.ok) { inp.value = 'v1.0.0'; return; }
        const d = await r.json();
        const releases = Array.isArray(d) ? d : (d.releases || []);
        if (!releases.length) { inp.value = 'v1.0.0'; return; }
        // Increment patch from latest
        const latest = releases[0].version || 'v0.0.0';
        const m = latest.match(/v?(\d+)\.(\d+)\.(\d+)/);
        if (m) {
            inp.value = 'v' + m[1] + '.' + m[2] + '.' + (parseInt(m[3]) + 1);
        } else {
            inp.value = 'v1.0.0';
        }
    } catch { inp.value = 'v1.0.0'; }
}

async function submitRelease(e) {
    if (e) e.preventDefault();
    const version = document.getElementById('releaseVersion')?.value.trim();
    const title   = document.getElementById('releaseTitle')?.value.trim();
    const notes   = document.getElementById('releaseNotes')?.value.trim() || '';

    if (!version || !title) {
        showToast('Version and title are required', ICONS.warning);
        return;
    }

    const btn = document.getElementById('releaseSubmitBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }

    try {
        const r = await fetch('/api/graph/release', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                graph_name: currentGraphName,
                version, title, notes
            })
        });
        const d = await r.json();
        if (!r.ok) {
            showToast(d.error || 'Release failed', ICONS.error);
            return;
        }
        closeReleaseModal();
        showToast(`Released ${version} — graph is now locked`, _ICON_LOCKED);
        fetchGraphStatus();
    } catch (err) {
        showToast('Network error: ' + err.message, ICONS.error);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = _ICON_LOCKED + ' Create Release'; }
    }
}

// ══════════════════════════════════════════════
//  Unlock
// ══════════════════════════════════════════════
function onLockBadgeClick() {
    if (graphLocked) {
        openUnlockConfirm();
    } else {
        openReleaseHistory();
    }
}

function openUnlockConfirm() {
    const overlay = _relOverlay();
    if (!overlay) return;

    const modal = overlay.querySelector('.release-modal');
    if (!modal) return;

    const ver = currentRelease?.current_release_version || '';
    modal.innerHTML = `
        <div class="release-modal-header">
            <h2><span class="release-icon">${_ICON_UNLOCK}</span> Unlock Graph</h2>
            <button class="release-modal-close" onclick="closeReleaseModal()">&times;</button>
        </div>
        <div class="release-modal-body">
            <div class="unlock-confirm-body">
                <p>This graph is locked at version <span class="unlock-version">${_escVer(ver)}</span>.</p>
                <p>Unlocking allows editing the graph. The chat remains available at all times.</p>
                <p class="unlock-warning">Changes after unlocking won't be part of the released version.</p>
            </div>
            <div class="release-modal-actions">
                <button class="release-cancel-btn" onclick="closeReleaseModal()">Cancel</button>
                <button class="release-submit-btn" onclick="doUnlock()">${_ICON_UNLOCK} Unlock for Editing</button>
            </div>
        </div>
    `;
    overlay.classList.add('open');
}

async function doUnlock() {
    try {
        const r = await fetch('/api/graph/unlock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graph_name: currentGraphName })
        });
        if (!r.ok) {
            const d = await r.json();
            showToast(d.error || 'Unlock failed', ICONS.error);
            return;
        }
        closeReleaseModal();
        _restoreReleaseModalHTML();
        showToast('Graph unlocked — you can now edit', _ICON_UNLOCK);
        fetchGraphStatus();
    } catch (err) {
        showToast('Network error: ' + err.message, ICONS.error);
    }
}

// ══════════════════════════════════════════════
//  Release history
// ══════════════════════════════════════════════
async function openReleaseHistory() {
    const overlay = _relOverlay();
    if (!overlay) return;

    const modal = overlay.querySelector('.release-modal');
    if (!modal) return;

    modal.innerHTML = `
        <div class="release-modal-header">
            <h2><span class="release-icon">📋</span> Release History</h2>
            <button class="release-modal-close" onclick="closeReleaseModal(); _restoreReleaseModalHTML();">&times;</button>
        </div>
        <div class="release-history-list" id="releaseHistoryList">
            <div style="color:var(--text-muted);text-align:center;padding:2rem">Loading…</div>
        </div>
    `;
    overlay.classList.add('open');

    try {
        const r = await fetch(`/api/graph/releases?graph_name=${encodeURIComponent(currentGraphName)}`);
        if (!r.ok) throw new Error('fetch failed');
        const d = await r.json();
        const releases = Array.isArray(d) ? d : (d.releases || []);
        const list = document.getElementById('releaseHistoryList');
        if (!list) return;

        if (!releases.length) {
            list.innerHTML = '<div class="release-history-empty">No releases yet. Create the first one!</div>';
            return;
        }

        list.innerHTML = releases.map((rel, i) => `
            <div class="release-history-item">
                <div class="release-history-dot"></div>
                <div class="release-history-info">
                    <div class="release-history-version">${_escVer(rel.version)}</div>
                    <div class="release-history-title">${escapeHtml(rel.title)}</div>
                    <div class="release-history-meta">
                        <span>${_fmtDate(rel.released_at)}</span>
                        <span>${rel.node_count} nodes · ${rel.edge_count} edges</span>
                    </div>
                </div>
                <div class="release-history-actions">
                    <button onclick="loadReleaseSnapshot('${rel.id}')" title="View this release's snapshot">View</button>
                </div>
            </div>
        `).join('');
    } catch {
        const list = document.getElementById('releaseHistoryList');
        if (list) list.innerHTML = '<div class="release-history-empty">Failed to load releases.</div>';
    }
}

async function loadReleaseSnapshot(releaseId) {
    closeReleaseModal();
    _restoreReleaseModalHTML();

    try {
        const r = await fetch(`/api/graph/release/${encodeURIComponent(releaseId)}`);
        if (!r.ok) { showToast('Failed to load snapshot', ICONS.error); return; }
        const d = await r.json();
        const release = d.release || d;  // handle both wrapped and unwrapped
        if (!release?.snapshot) { showToast('No snapshot in this release', ICONS.warning); return; }

        const snap = typeof release.snapshot === 'string' ?
            JSON.parse(release.snapshot) : release.snapshot;

        if (snap.nodes && snap.links) {
            snap.graph_name = currentGraphName;
            renderGraph(snap);
            showToast(`Viewing snapshot ${_escVer(release.version)}`, ICONS.camera);
        } else {
            showToast('Snapshot has no graph data', ICONS.warning);
        }
    } catch (err) {
        showToast('Error loading snapshot: ' + err.message, ICONS.error);
    }
}

// ── Utility ──────────────────────────────────
function _fmtDate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) +
               ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
}

// Store the original modal HTML so we can restore after unlock/history views
let _releaseModalOriginalHTML = null;

function _restoreReleaseModalHTML() {
    const overlay = _relOverlay();
    if (!overlay || !_releaseModalOriginalHTML) return;
    const modal = overlay.querySelector('.release-modal');
    if (modal) modal.innerHTML = _releaseModalOriginalHTML;
}

// ── Init: cache original modal HTML ──────────
document.addEventListener('DOMContentLoaded', () => {
    const overlay = _relOverlay();
    if (overlay) {
        const modal = overlay.querySelector('.release-modal');
        if (modal) _releaseModalOriginalHTML = modal.innerHTML;
    }
});

// ── Hook into renderGraph ────────────────────
// After renderGraph runs, the graphNameBadge text updates. We use a
// MutationObserver on it to trigger fetchGraphStatus.
(function hookRenderGraph() {
    const badge = document.getElementById('graphNameBadge');
    if (!badge) return;
    const obs = new MutationObserver(() => {
        fetchGraphStatus();
    });
    obs.observe(badge, { childList: true, characterData: true, subtree: true });
})();
