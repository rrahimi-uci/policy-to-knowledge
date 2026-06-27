/* ── Utility Functions ──────────────────────── */
function escapeHtml(t) {
    if (!t) return '';
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

/** Escape a value for safe use inside inline onclick="fn('…')" attributes. */
function escapeAttr(v) {
    return escapeHtml(String(v)).replace(/'/g, "&#39;").replace(/"/g, '&quot;');
}

function truncate(s, n) { return s && s.length > n ? s.slice(0, n) + '...' : (s || ''); }

// ── SVG Icon Registry ──────────────────────────
// Eliminates copy-pasted SVG strings across 10+ files.
const ICONS = {
    success:  '<svg class="toast-icon" style="color:var(--emerald)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error:    '<svg class="toast-icon" style="color:var(--rose)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning:  '<svg class="toast-icon" style="color:var(--amber)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    warningRose: '<svg class="toast-icon" style="color:var(--rose)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    edit:     '<svg class="toast-icon" style="color:var(--amber)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    editCyan: '<svg class="toast-icon" style="color:var(--cyan)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    comment:  '<svg class="toast-icon" style="color:var(--cyan)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    trash:    '<svg class="toast-icon" style="color:var(--rose)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    trashMuted: '<svg class="toast-icon" style="color:var(--text-muted)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    download: '<svg class="toast-icon" style="color:var(--emerald)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    plus:     '<svg class="toast-icon" style="color:var(--accent-light)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    info:     '<svg class="toast-icon" style="color:var(--amber)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    locked:   '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    unlock:   '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>',
    camera:   '<svg class="toast-icon" style="color:var(--cyan)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
    search:   '<svg class="toast-icon" style="color:var(--cyan)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    revert:   '<svg class="toast-icon" style="color:var(--accent-light)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>',
    reverse:  '<svg class="toast-icon" style="color:var(--accent-light)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
};

// ── Edge ID Helper ─────────────────────────────
/** Compute a stable edge ID from a link object (works with raw or D3-resolved source/target). */
function makeEdgeId(link) {
    const srcId = typeof link.source === 'object' ? link.source.id : link.source;
    const tgtId = typeof link.target === 'object' ? link.target.id : link.target;
    return link.id || `${srcId}--${link.label}--${tgtId}`;
}

// ── Async Button Loading Wrapper ───────────────
/**
 * Wraps an async operation with button loading state.
 * Disables the button, shows a spinner, re-enables on completion.
 * @param {HTMLElement|string} btnOrId – button element or its ID
 * @param {Function} asyncFn – async function to execute
 * @param {{ label?: string }} opts – optional label to restore
 */
async function withLoading(btnOrId, asyncFn, opts = {}) {
    const btn = typeof btnOrId === 'string' ? document.getElementById(btnOrId) : btnOrId;
    if (!btn) return asyncFn();
    const origHTML = btn.innerHTML;
    const origDisabled = btn.disabled;
    btn.disabled = true;
    btn.classList.add('btn-loading');
    try {
        return await asyncFn();
    } finally {
        btn.disabled = origDisabled;
        btn.classList.remove('btn-loading');
        if (opts.label) {
            btn.textContent = opts.label;
        } else {
            btn.innerHTML = origHTML;
        }
    }
}

// ── Confirmation Dialog ─────────────────────────
/**
 * Show a lightweight confirmation dialog before destructive actions.
 * Returns a Promise<boolean> – true if confirmed, false if cancelled.
 * @param {string} message – HTML-safe message to display
 * @param {{ confirmText?: string, cancelText?: string, danger?: boolean }} opts
 */
function confirmAction(message, opts = {}) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';
        overlay.innerHTML = `
            <div class="confirm-dialog" role="alertdialog" aria-modal="true" aria-label="Confirmation">
                <div class="confirm-message">${message}</div>
                <div class="confirm-actions">
                    <button class="confirm-btn cancel" data-action="cancel">${escapeHtml(opts.cancelText || 'Cancel')}</button>
                    <button class="confirm-btn ${opts.danger ? 'danger' : 'primary'}" data-action="confirm">${escapeHtml(opts.confirmText || 'Confirm')}</button>
                </div>
            </div>`;
        const close = (result) => { overlay.remove(); resolve(result); };
        overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => close(false));
        overlay.querySelector('[data-action="confirm"]').addEventListener('click', () => close(true));
        overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
        overlay.addEventListener('keydown', e => { if (e.key === 'Escape') close(false); });
        document.body.appendChild(overlay);
        overlay.querySelector('[data-action="cancel"]').focus();
    });
}

function formatMarkdown(text) {
    if (!text) return '';
    // Use marked.js if available, otherwise basic fallback
    if (typeof marked !== 'undefined') {
        try {
            return marked.parse(text);
        } catch (e) {
            console.warn('marked.parse error, using fallback', e);
        }
    }
    // Fallback: basic formatting
    text = escapeHtml(text);
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    text = text.replace(/\n/g, '<br>');
    return text;
}

function showToast(message, icon) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `${icon || ''}<span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 250);
    }, 2500);
}

function autoScroll() {
    if (!userScrolledUp) chatMsgs.scrollTop = chatMsgs.scrollHeight;
}

function debounce(fn, delay) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ── AI Rewrite (sparkle button) ─────────────────────────────────

const _SPARKLE_ICON = '<span class="sparkle-icon">✨🖊️</span>';

/**
 * Call /api/rewrite with the text from a textarea/input, replace its value
 * with the AI-rewritten version. Shows a spinner while waiting.
 *
 * @param {string} targetId  – id of the textarea/input element
 * @param {string} [context] – optional field name for prompt context
 */
async function aiRewrite(targetId, context) {
    const el = document.getElementById(targetId);
    if (!el) return;
    const text = el.value.trim();
    if (!text) {
        showToast('Nothing to rewrite', _SPARKLE_ICON);
        return;
    }

    // Find and animate the sparkle button
    const btn = el.parentElement?.querySelector('.ai-rewrite-btn') ||
                el.closest('.create-field, .edit-field, .comment-form')?.querySelector('.ai-rewrite-btn');
    if (btn) {
        btn.classList.add('ai-rewrite-loading');
        btn.disabled = true;
    }

    try {
        const resp = await fetch('/api/rewrite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, context: context || '' }),
        });
        const data = await resp.json();
        if (resp.ok && data.rewritten) {
            el.value = data.rewritten;
            // Trigger input event so any auto-resize or change handlers fire
            el.dispatchEvent(new Event('input', { bubbles: true }));
            showToast('Rewritten by AI', _SPARKLE_ICON);
        } else {
            showToast(data.error || 'Rewrite failed', _SPARKLE_ICON);
        }
    } catch (err) {
        showToast('Rewrite request failed', _SPARKLE_ICON);
    } finally {
        if (btn) {
            btn.classList.remove('ai-rewrite-loading');
            btn.disabled = false;
        }
    }
}

/**
 * Returns an HTML string for the sparkle rewrite button.
 * @param {string} targetId – the textarea/input id to rewrite
 * @param {string} [context] – optional field label for AI context
 */
function sparkleBtn(targetId, context) {
    const ctx = context ? escapeHtml(context) : '';
    return `<button type="button" class="ai-rewrite-btn" title="AI Rewrite" onclick="aiRewrite('${targetId}','${ctx}')">${_SPARKLE_ICON}</button>`;
}

/**
 * Call /api/suggest-rule-id to auto-generate a rule_id from the Name, Entity,
 * and Rule Type fields in the create form.
 */
async function suggestRuleId() {
    const nameEl = document.getElementById('createName');
    const ruleIdEl = document.getElementById('createRuleId');
    if (!nameEl || !ruleIdEl) return;

    const name = nameEl.value.trim();
    if (!name) {
        showToast('Enter a name first', _SPARKLE_ICON);
        return;
    }

    const entity = document.getElementById('createEntity')?.value || '';
    const ruleType = document.getElementById('createRuleType')?.value || '';

    // Animate button
    const btn = document.getElementById('suggestRuleIdBtn');
    if (btn) { btn.classList.add('ai-rewrite-loading'); btn.disabled = true; }

    try {
        const resp = await fetch('/api/suggest-rule-id', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, entity, rule_type: ruleType }),
        });
        const data = await resp.json();
        if (resp.ok && data.rule_id) {
            ruleIdEl.value = data.rule_id;
            ruleIdEl.dispatchEvent(new Event('input', { bubbles: true }));
            showToast('Rule ID suggested', _SPARKLE_ICON);
        } else {
            showToast(data.error || 'Suggestion failed', _SPARKLE_ICON);
        }
    } catch (err) {
        showToast('Suggestion request failed', _SPARKLE_ICON);
    } finally {
        if (btn) { btn.classList.remove('ai-rewrite-loading'); btn.disabled = false; }
    }
}
