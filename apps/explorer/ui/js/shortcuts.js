/* ── Keyboard Shortcuts & Deep Linking ──────── */
function copyGremlin(btn) {
    const query = btn.dataset.query;
    navigator.clipboard.writeText(query).then(() => {
        btn.classList.add('copied');
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.classList.remove('copied'); btn.textContent = 'Copy'; }, 1500);
    }).catch(() => {
        showToast('Failed to copy to clipboard', ICONS.warning);
    });
}

// ── Deep Linking via URL Hash ────────────────
function handleHash() {
    const hash = location.hash.replace('#', '');
    if (!hash || !currentGraphData) return;
    const node = currentGraphData.nodes.find(n => n.id === hash);
    if (node) {
        try {
            onNodeClick({ stopPropagation() {}, currentTarget: null }, node);
        } catch (err) {
            console.error('handleHash navigation failed:', err);
        }
    }
}
