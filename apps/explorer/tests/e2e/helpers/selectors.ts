/**
 * Shared CSS / element selectors for Explorer Playwright tests.
 *
 * Keeping selectors in one place makes maintenance easy when the UI
 * markup changes.
 */

/* ── Chat panel ───────────────────────────────────────────────── */

export const CHAT = {
  input: "#chatInput",
  sendBtn: "#sendBtn",
  messages: "#chatMessages",
  /** Last assistant bubble (streaming finishes when cursor class removed) */
  lastBubble: ".message.assistant:last-child .msg-bubble",
  /** Node result cards returned by the LLM */
  nodeCard: ".node-card",
  nodeCardName: ".node-card-name",
  /** "Show on Graph" button inside a vertex-detail-card */
  showOnGraph: ".vertex-detail-show-btn",
  /** Welcome section visible on fresh page */
  welcome: ".welcome-heading",
  /** Quick-action chips */
  chip: ".chip",
  /** Streaming cursor class (removed when done) */
  streamingCursor: ".streaming-cursor",
  /** Retry button on error */
  retryBtn: ".retry-btn",
} as const;

/* ── Graph panel ──────────────────────────────────────────────── */

export const GRAPH = {
  container: "#graphContainer",
  empty: "#graphEmpty",
  searchInput: "#graphSearchInput",
  searchClear: "#graphSearchClear",
  searchMatchCount: "#searchMatchCount",
  searchEmpty: "#graphSearchEmpty",
  nodeCount: "#nodeCount",
  linkCount: "#linkCount",
  graphNameBadge: "#graphNameBadge",
  /** SVG circle elements representing nodes */
  node: ".graph-node",
  /** SVG text labels */
  nodeLabel: ".graph-node-label",
  /** SVG line elements representing edges */
  link: ".graph-link",
  /** Wider invisible hit-area for edges */
  linkHit: ".graph-link-hit",
  /** Edge label text */
  linkLabel: ".graph-link-label",
  /** Create Node button in toolbar */
  createNodeBtn: ".create-node-btn",
  /** Legend rows with data-filter */
  legendRow: ".legend-row",
  /** Tooltip on hover */
  tooltip: "#tooltip",
  /** Dimmed class applied by search / legend filter */
  dimClass: "search-dim",
} as const;

/* ── Detail panel (node) ──────────────────────────────────────── */

export const DETAIL = {
  panel: "#detailPanel",
  title: "#detailTitle",
  badge: "#detailBadge",
  body: "#detailBody",
  closeBtn: "#detailPanel .detail-close",
  backBtn: "#detailBackBtn",

  /* Action buttons rendered inside the detail body */
  actionGrid: ".detail-actions-grid",
  commentBtn: 'button:has-text("Comment"):not(:has-text("History"))',
  editBtn: 'button:has-text("Edit")',
  deleteBtn: 'button:has-text("Delete")',
  shareBtn: 'button:has-text("Share")',
  historyBtn: 'button:has-text("Comment History")',
  versionBtn: 'button:has-text("Version History")',

  /* Reviewed / Approved toggles */
  reviewedYes: '.reviewed-toggle-btn[data-val="yes"]',
  reviewedNo: '.reviewed-toggle-btn[data-val="no"]',
  approvedYes: '.approved-toggle-btn[data-val="yes"]',
  approvedNo: '.approved-toggle-btn[data-val="no"]',

  /* Properties */
  propGrid: ".prop-grid",
  propKey: ".prop-key",
  propVal: ".prop-val",
  refLink: ".ref-link",
  depCard: ".dep-card",
  neighborChip: ".neighbor-chip",

  /* Sub-panel (comment / edit / delete) */
  subPanel: "#actionSubPanel",
  subPanelClose: ".action-subpanel-close",
  commentInput: "#commentInput",
  commentAuthor: "#commentAuthor",
  commentSubmit: ".comment-submit",
  commentList: "#commentList",
  commentItem: ".comment-item",

  editName: "#editName",
  editContent: "#editContent",
  editSave: ".edit-save",
  editCancel: ".edit-cancel",

  deleteConfirm: ".delete-confirm",
  deleteCancelBtn: ".delete-confirm-btn.cancel",
  deleteDangerBtn: ".delete-confirm-btn.danger",
  deletedBanner: "#deletedBanner",
  undoDeleteBtn: "#deletedBanner button",

  /* Skeleton loading */
  skeleton: ".skeleton",
} as const;

/* ── Edge detail panel ────────────────────────────────────────── */

export const EDGE = {
  panel: "#edgeDetailPanel",
  title: "#edgeDetailTitle",
  body: "#edgeDetailBody",
  closeBtn: ".edge-detail-panel .detail-close",
  reverseBtn: ".edge-reverse-btn",
  endpoint: ".edge-endpoint",
} as const;

/* ── Create wizard ────────────────────────────────────────────── */

export const CREATE = {
  /* Step 1 – vertex properties */
  nameInput: "#createName",
  ruleIdInput: "#createRuleId",
  ruleTypeSelect: "#createRuleType",
  entitySelect: "#createEntity",
  mandatoryCheckbox: "#createMandatory",
  descriptionInput: "#createDescription",
  contentInput: "#createContent",
  conditionsInput: "#createConditions",
  consequencesInput: "#createConsequences",
  exceptionsInput: "#createExceptions",
  referenceInput: "#createReference",
  confidenceSlider: "#createConfidence",
  confidenceVal: "#createConfVal",
  requiresReviewCheckbox: "#createRequiresReview",
  reviewReasonInput: "#createReviewReason",
  labelRadio: 'input[name="createLabel"]',

  /* Navigation */
  nextBtn: ".create-btn--next",
  cancelBtn: ".create-btn--cancel",
  submitBtn: ".create-btn--submit",

  /* Step 2 – connections */
  targetSearch: "#manualTarget",
  targetResults: "#manualTargetResults",
  targetItem: ".manual-target-item",
  targetId: "#manualTargetId",
  edgeLabelSelect: "#manualEdgeLabel",
  depTypeSelect: "#manualDepType",
  directionRadio: 'input[name="manualDir"]',
  strengthSlider: "#manualStrength",
  rationaleInput: "#manualRationale",
  impactInput: "#manualImpact",
  addConnectionBtn: ".create-btn--add",
  pendingSection: "#pendingSection",
  pendingConnection: ".pending-connection",
  pendingRemove: ".pending-remove",

  /* Suggestions */
  suggestionCard: ".suggestion-card",
  acceptBtn: ".create-btn--accept",
  dismissBtn: ".create-btn--dismiss",

  /* AI assist buttons */
  /** ✨🖊️ sparkle button next to the Rule ID input */
  suggestRuleIdBtn: "#suggestRuleIdBtn",
  /** ✨🖊️ sparkle button next to the Content textarea */
  contentSparkleBtn: 'label[for="createContent"] .ai-rewrite-btn',
} as const;

/* ── Toast notifications ──────────────────────────────────────── */

export const TOAST = {
  container: "#toastContainer",
  toast: ".toast",
} as const;
