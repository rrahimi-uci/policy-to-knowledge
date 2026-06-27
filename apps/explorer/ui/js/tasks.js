/* ── Task Box Logic ─────────────────────────── */

let _taskData = [];
let _taskFilter = 'all';

const GRAPH_DISPLAY = {
    fannie_mae_g: 'Fannie Mae',
    sample_guidelines_g: 'Policy to Knowledge Guidelines',
    overlays_g: 'Example Overlays',
};

/* ── Fetch and render tasks ─────────────────── */
async function loadTasks() {
    try {
        const res = await fetch('/api/tasks');
        const data = await res.json();
        _taskData = data.tasks || [];
        renderTaskList();
        updateTaskBadge();
    } catch (err) {
        console.error('Failed to load tasks:', err);
        showToast('Failed to load tasks', ICONS.warning);
    }
}

/* ── Render task list ───────────────────────── */
function renderTaskList() {
    const list = document.getElementById('taskList');
    if (!list) return;

    const filtered = _taskFilter === 'all'
        ? _taskData
        : _taskData.filter(t => t.type === _taskFilter);

    if (!filtered.length) {
        list.innerHTML = `<div class="task-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            <p>No ${_taskFilter} task alerts</p>
        </div>`;
        return;
    }

    list.innerHTML = filtered.map(task => {
        const typeClass = task.type === 'review' ? 'task-badge-review' : 'task-badge-approval';
        const typeIcon = task.type === 'review'
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
        const priorityClass = task.priority === 'high' ? 'high' : task.priority === 'medium' ? 'medium' : '';
        const graphLabel = GRAPH_DISPLAY[task.graph_name] || task.graph_name;
        const completedClass = task.status === 'completed' ? ' completed' : '';
        const statusBadge = task.status === 'completed'
            ? '<span class="task-badge task-badge-completed">✓ Done</span>'
            : '';

        // Format due date
        const due = task.due_date || '';
        const dueFormatted = due ? new Date(due + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';

        return `<div class="task-card${completedClass}" data-type="${task.type}" data-task-id="${task.id}" onclick="handleTaskClick('${task.id}')">
            <div class="task-card-header">
                <span class="task-badge ${typeClass}">${typeIcon} ${task.type}</span>
                <span class="task-badge task-badge-priority ${priorityClass}">${task.priority}</span>
                ${statusBadge}
            </div>
            <div class="task-node-target">
                <div class="task-node-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8" stroke-dasharray="4 3"/></svg>
                </div>
                <div class="task-node-info">
                    <div class="task-node-name">${escapeHtml(task.node_name)}</div>
                    <div class="task-node-graph">${escapeHtml(graphLabel)}</div>
                </div>
                <span class="task-node-arrow">→</span>
            </div>
            <div class="task-card-desc">${escapeHtml(task.description)}</div>
            <div class="task-card-footer">
                <span class="task-card-due">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                    ${dueFormatted}
                </span>
                <span class="task-card-title">${escapeHtml(task.title)}</span>
            </div>
        </div>`;
    }).join('');

    // Update summary
    updateTaskSummary();
}

/* ── Handle task click ──────────────────────── */
async function handleTaskClick(taskId) {
    const task = _taskData.find(t => t.id === taskId);
    if (!task) return;

    // Mark task as completed to reduce the badge count immediately
    if (task.status !== 'completed') {
        task.status = 'completed';
        updateTaskBadge();
        renderTaskList();
        // Persist to server in background
        fetch(`/api/tasks/${taskId}/complete`, { method: 'POST' }).catch(() => {});
    }

    // Close the task panel
    closeTaskPanel();

    // Show toast about navigating
    showToast(`Opening ${task.type}: ${task.title}`, task.type === 'review' ? ICONS.search : ICONS.success);

    // Load the graph if different from current
    if (task.graph_name !== currentGraphName || !currentGraphData) {
        try {
            const res = await fetch(`/api/graph?graph_name=${encodeURIComponent(task.graph_name)}`);
            const graphData = await res.json();
            renderGraph(graphData);
            // Wait for the force simulation to settle before navigating
            await new Promise(r => setTimeout(r, 2400));
        } catch (err) {
            console.error('Failed to load graph for task:', err);
            showToast('Failed to load graph', ICONS.warning);
            return;
        }
    }

    // Navigate to the specific node
    navigateToNode(task.node_id);

    // Wait for D3 zoom animation to finish before opening subpanel
    await new Promise(r => setTimeout(r, 900));
}

/* ── Toggle task panel open/close ───────────── */
function toggleTaskPanel() {
    const panel = document.getElementById('taskPanel');
    const overlay = document.getElementById('taskOverlay');
    if (!panel) return;

    if (panel.classList.contains('open')) {
        closeTaskPanel();
    } else {
        panel.classList.add('open');
        if (overlay) overlay.classList.add('open');
        loadTasks();
    }
}

function closeTaskPanel() {
    const panel = document.getElementById('taskPanel');
    const overlay = document.getElementById('taskOverlay');
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
}

/* ── Filter logic ───────────────────────────── */
function setTaskFilter(filter) {
    _taskFilter = filter;

    // Update active states
    document.querySelectorAll('.task-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });

    renderTaskList();
}

/* ── Update badge count ─────────────────────── */
function updateTaskBadge() {
    const badge = document.getElementById('taskBadgeCount');
    if (!badge) return;
    const pending = _taskData.filter(t => t.status === 'pending').length;
    badge.textContent = pending;
    badge.style.display = pending > 0 ? '' : 'none';
}

/* ── Update summary bar ─────────────────────── */
function updateTaskSummary() {
    const summary = document.getElementById('taskSummary');
    if (!summary) return;

    const total = _taskData.length;
    const completed = _taskData.filter(t => t.status === 'completed').length;
    const reviews = _taskData.filter(t => t.type === 'review').length;
    const approvals = _taskData.filter(t => t.type === 'approval').length;

    summary.innerHTML = `
        <span class="task-summary-stat">
            <span class="task-summary-dot" style="background:var(--cyan)"></span>
            ${reviews} review${reviews !== 1 ? 's' : ''}
        </span>
        <span class="task-summary-stat">
            <span class="task-summary-dot" style="background:var(--emerald)"></span>
            ${approvals} approval${approvals !== 1 ? 's' : ''}
        </span>
        <span class="task-summary-stat">
            ${completed}/${total} done
        </span>
    `;
}

/* ── Open reference with highlighting ─────── */
function openReferenceWithHighlight(encodedRef, encodedGraph, highlightTerms) {
    const ref = decodeURIComponent(encodedRef);
    const graphName = decodeURIComponent(encodedGraph);
    const terms = highlightTerms || [];

    fetch(`/api/reference/resolve?ref=${encodeURIComponent(ref)}&graph_name=${encodeURIComponent(graphName)}`)
        .then(r => r.json())
        .then(data => {
            if (data.matches && data.matches.length > 0) {
                const best = data.matches[0];
                const theme = localStorage.getItem('p2k-theme') || 'dark';
                let url = best.url;
                const sep = url.includes('?') ? '&' : '?';
                url += sep + 'theme=' + theme;
                if (terms.length) {
                    url += '&highlight=' + encodeURIComponent(terms.join(','));
                }
                window.open(url, '_blank');
            } else {
                showToast('No source document found for this reference', ICONS.warning);
            }
        })
        .catch(err => {
            console.error('Reference resolution failed:', err);
            showToast('Failed to resolve reference', ICONS.warning);
        });
}

/* ── Mark task complete from detail panel ───── */
function completeCurrentTask(taskId) {
    fetch(`/api/tasks/${taskId}/complete`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                const task = _taskData.find(t => t.id === taskId);
                if (task) task.status = 'completed';
                renderTaskList();
                updateTaskBadge();
                showToast('Task marked as completed', ICONS.success);
            }
        })
        .catch(() => showToast('Failed to complete task', ICONS.warning));
}

/* ── Load tasks on startup ──────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
});
