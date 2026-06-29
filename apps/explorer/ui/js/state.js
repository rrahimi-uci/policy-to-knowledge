/* ── State ──────────────────────────────────── */

// ── API routing ──────────────────────────────
// The same frontend can talk to either backend.  By default it calls the
// backend that served the page; set window.P2K_CONFIG.apiBaseUrl or
// localStorage.p2k-api-base-url to point this UI at another service.
const _queryParams = new URLSearchParams(window.location.search);
window.P2K_CONFIG = window.P2K_CONFIG || {};
if (_queryParams.get('apiBaseUrl') !== null) {
    const apiBaseUrl = _queryParams.get('apiBaseUrl').trim();
    if (apiBaseUrl) localStorage.setItem('p2k-api-base-url', apiBaseUrl);
    else localStorage.removeItem('p2k-api-base-url');
}
if (_queryParams.get('backendMode')) {
    localStorage.setItem('p2k-backend-mode', _queryParams.get('backendMode').trim());
}
const _apiBaseUrl = (
    window.P2K_CONFIG.apiBaseUrl ||
    localStorage.getItem('p2k-api-base-url') ||
    ''
).replace(/\/+$/, '');
window.P2K_CONFIG.backendMode = (
    window.P2K_CONFIG.backendMode ||
    localStorage.getItem('p2k-backend-mode') ||
    'janusgraph'
);
window.P2K_CONFIG.apiBaseUrl = _apiBaseUrl;

// Derive the URL prefix from the page's own path so same-origin fetch() calls
// to absolute paths like '/api/...' are rewritten to '<prefix>/api/...'.
const _urlPrefix = (() => {
    if (window.P2K_CONFIG.urlPrefix) {
        return String(window.P2K_CONFIG.urlPrefix).replace(/\/+$/, '');
    }
    const scriptEl = document.currentScript || document.querySelector('script[src$=\"state.js\"]');
    if (scriptEl) {
        // state.js is loaded as '<prefix>/js/state.js'
        const src = new URL(scriptEl.src, location.href);
        const idx = src.pathname.indexOf('/js/state.js');
        if (idx > 0) return src.pathname.substring(0, idx);
    }
    const knownPrefixes = ['/p2k-postgres', '/app'];
    const matched = knownPrefixes.find(prefix => location.pathname === prefix || location.pathname.startsWith(prefix + '/'));
    if (matched) return matched;
    return '';
})();

const _originalFetch = window.fetch;
window.fetch = function (resource, init) {
    if (typeof resource === 'string' && resource.startsWith('/')) {
        if (_apiBaseUrl && (resource.startsWith('/api/') || resource === '/api/' || resource.startsWith('/logo.svg'))) {
            resource = _apiBaseUrl + resource;
        } else if (_urlPrefix) {
            resource = _urlPrefix + resource;
        }
    }
    return _originalFetch.call(this, resource, init);
};

let conversationHistory = [];
let currentGraphData = null;
let currentGraphName = 'g'; // Track which graph is currently displayed
let simulation = null;
let svg = null, gRoot = null, zoomBehavior = null;
let selectedNodeId = null;
let selectedEdgeId = null;
let isStreaming = false;
let streamingNodeRefs = null;  // node references for current streaming response
let navHistory = [];  // navigation history stack for detail panel back button
let _skipNavPush = false;  // flag to prevent history push during goBack
let userScrolledUp = false; // auto-scroll lock flag
let activeLegendFilter = null; // currently active legend filter type
let lastUserMessage = ''; // last user message for retry
let showAllLabels = false; // whether all node labels are visible

const chatInput = document.getElementById('chatInput');
const sendBtn   = document.getElementById('sendBtn');
const chatMsgs  = document.getElementById('chatMessages');

// ── Color mapping for rule_type ───────────────
const TYPE_COLORS = {
    constraint:    '#6366f1',
    eligibility:   '#22d3ee',
    process:       '#fbbf24',
    prohibition:   '#fb7185',
    documentation: '#a78bfa',
    validation:    '#f97316',
    entity_category: '#34d399',
};
const DEFAULT_COLOR = '#64748b';

// Extra palette for rule_types not in the base map
const _EXTRA_PALETTE = [
    '#e879f9', '#38bdf8', '#4ade80', '#facc15', '#f87171',
    '#a3e635', '#2dd4bf', '#818cf8', '#fb923c', '#c084fc',
];
let _extraColorIdx = 0;

/** Return a consistent color for any rule_type, assigning new colors as needed. */
function nodeColor(d) {
    if (d.label === 'entity_category') return TYPE_COLORS.entity_category;
    const rt = d.rule_type || d.category || '';
    if (!rt) return DEFAULT_COLOR;
    if (!TYPE_COLORS[rt]) {
        TYPE_COLORS[rt] = _EXTRA_PALETTE[_extraColorIdx % _EXTRA_PALETTE.length];
        _extraColorIdx++;
    }
    return TYPE_COLORS[rt];
}

function nodeColorByType(ruleType) {
    if (!ruleType) return DEFAULT_COLOR;
    if (!TYPE_COLORS[ruleType]) {
        TYPE_COLORS[ruleType] = _EXTRA_PALETTE[_extraColorIdx % _EXTRA_PALETTE.length];
        _extraColorIdx++;
    }
    return TYPE_COLORS[ruleType];
}
