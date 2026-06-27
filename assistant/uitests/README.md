# Explorer — UI End-to-End Tests

Playwright-based E2E tests that exercise the main user flows of the
Explorer compliance-graph UI.

---

## Prerequisites

| Service             | Port  | How to start                                                   |
|---------------------|-------|---------------------------------------------------------------|
| Flask server        | 5001  | `cd .. && PYTHONPATH=. SERVER_PORT=5001 .venv/bin/python src/server.py` |
| JanusGraph + Cass.  | 8182  | `cd .. && docker-compose up -d`                                |

The tests expect at least the **fannie_mae_g** graph to be loaded with
data. They also need OpenAI credentials in the environment for the chat
tests (the LLM is called live via the `/api/chat/stream` endpoint).

---

## Running

```bash
# Install dependencies (first time only)
npm install
node_modules/.bin/playwright install chromium

# Run all tests
npm test

# Run a specific flow
node_modules/.bin/playwright test tests/01-graph-discovery.spec.ts

# Headed mode (watch the browser)
node_modules/.bin/playwright test --headed

# Debug mode (step through)
node_modules/.bin/playwright test --debug
```

> **Note:** Use the local binary (`node_modules/.bin/playwright`) or `npm test` rather than
> `npx playwright` to avoid version-mismatch errors caused by `npx` installing a different
> global version.

---

## Test Plan

### Flow 1 — Graph Discovery (`01-graph-discovery.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Types _"How many graphs are available?"_ in chat | Copilot responds with the number of configured graphs |
| 2 | Types _"Show me one of the graphs"_ | A graph renders in the right panel with nodes & edges |
| 3 | Verify graph element counts | `#nodeCount` and `#linkCount` show non-zero values |
| 4 | Verify graph name badge visible | `#graphNameBadge` shows the traversal source name |

### Flow 2 — Low-Confidence Review (`02-low-confidence-review.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Types _"Show me 10 rules with the lowest confidence score"_ | Copilot returns node cards with low scores |
| 2 | Clicks a random node card | Detail panel opens with node info |
| 3 | Checks the reference link | Opens in new tab, page loads with chunk content |
| 4 | Adds a comment and assigns to a person from the list | Comment appears in the comment list |
| 5 | Clicks a different node card | Second detail panel opens |
| 6 | Edits the node name & content, then saves | Version history records the change |

### Flow 3 — Node Creation & Edge Connection (`03-node-creation.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Clicks "Create Node" in graph toolbar | Create wizard opens (step 1) |
| 2 | Fills in node properties (name, content, rule_type, etc.) | Fields accept input |
| 3 | Clicks "Next: Add Connections →" | Step 2 shows suggested connections |
| 4 | Searches for a target node and adds a connection | Connection appears in pending list |
| 5 | Selects edge label, direction, dependency type | Edge config populated |
| 6 | Clicks "Create Node" (submit) | Node created, graph refreshes with new node |

### Flow 4 — Graph Search (`04-graph-search.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Types _"Show me the full graph"_ via chat to load graph | Graph renders |
| 2 | Types _"credit"_ in the graph search bar | Matching nodes remain bright, others dim |
| 3 | Verifies match count is > 0 | `#searchMatchCount` shows count |
| 4 | Clears the search | All nodes return to normal |

### Flow 5 — Node Deletion (`05-node-deletion.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Loads the graph and clicks a random node | Detail panel opens |
| 2 | Clicks the "Delete" action button | Confirmation dialog appears |
| 3 | Cancels the delete | Dialog closes, node unchanged |
| 4 | Clicks "Delete" again, confirms by clicking "Flag for Deletion" | Node dimmed (opacity), deleted banner shown |
| 5 | Verifies deleted banner text | Banner states the node is flagged |
| 6 | Clicks "Undo" to reverse the deletion flag | Node restored to full opacity |

### Flow 6 — Task Box (`06-task-box.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|-----------------|
| 1 | Clicks the task toggle button | Task panel slides in with 6 task cards (4 review, 2 approval), badge shows pending count, summary bar visible |
| 2 | Clicks "Review" filter | Only 4 review cards shown, each with `data-type="review"` |
| 3 | Clicks "Approval" filter | Only 2 approval cards shown, each with `data-type="approval"` |
| 4 | Clicks "All" filter | All 6 cards restored |
| 5 | Clicks the close button (✕) | Panel and overlay lose the `open` class |
| 6 | Clicks a review task card | Panel closes, toast appears, graph renders, detail panel opens for the target node |
| 7 | Clicks an approval task card | Same as review, plus the comment input auto-opens and is pre-filled with approval text (> 10 chars) |

### Flow 7 — Approval & Review Toggles (`07-approval-toggle.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|------------------|
| 1 | Loads the graph and clicks a random node | Detail panel opens |
| 2 | Clicks "Reviewed: Yes" toggle | Toggle gains `active` class; toast contains "review" |
| 3 | Clicks "Approved: Yes" toggle | Toggle gains `active` class; toast contains "approv" |
| 4 | Verifies both toggles active in sequence | Both Yes buttons active; both No buttons inactive |

### Flow 8 — Edge Detail Panel (`08-edge-detail.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|------------------|
| 1 | Loads the graph | D3 force graph renders with edges |
| 2 | Clicks a `.graph-link-hit` edge element | Edge detail panel opens |
| 3 | Inspects panel content | Title non-empty; at least one endpoint chip shown; Reverse button visible |
| 4 | Clicks the close button | Panel loses `open` class and slides out |

### Flow 9 — AI Rewrite Sparkle Button (`09-ai-rewrite.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|------------------|
| 1 | Opens Create Node wizard | Wizard step 1 visible |
| 2 | Fills Content field with seed text | Field contains seed value |
| 3 | Clicks ✨🖊️ sparkle button next to Content | Button gains `ai-rewrite-loading` class; API call made |
| 4 | Waits for button to re-enable | `ai-rewrite-loading` class removed within 30 s |
| 5 | Inspects Content field | Value differs from seed text (rewritten by GPT-4o-mini) |
| 6 | Checks toast | Toast says "Rewritten by AI" |

### Flow 10 — Rule ID Suggestion (`10-rule-id-suggest.spec.ts`)

| Step | User Action | Expected Result |
|------|-------------|------------------|
| 1 | Opens Create Node wizard, fills Name field | Name = "Capital Reserve Requirement" |
| 2 | Selects Entity and Rule Type | Dropdowns populated |
| 3 | Clicks ✨🖊️ next to Rule ID | `#suggestRuleIdBtn` calls `/api/suggest-rule-id` |
| 4 | Waits for button to re-enable | Response received within 30 s |
| 5 | Inspects Rule ID field | Value starts with `BR_` |
| 6 | Guard test: empty Name → click suggest | Toast says "name"; Rule ID field stays empty |

```
uitests/
├── README.md                          # This file
├── package.json
├── playwright.config.ts
├── tsconfig.json
└── tests/
    ├── helpers/
    │   ├── selectors.ts               # Shared CSS/ID selectors
    │   ├── chat.ts                    # Chat interaction helpers
    │   └── graph.ts                   # Graph interaction helpers
    ├── 01-graph-discovery.spec.ts
    ├── 02-low-confidence-review.spec.ts
    ├── 03-node-creation.spec.ts
    ├── 04-graph-search.spec.ts
    ├── 05-node-deletion.spec.ts
    ├── 06-task-box.spec.ts
    ├── 07-approval-toggle.spec.ts
    ├── 08-edge-detail.spec.ts
    ├── 09-ai-rewrite.spec.ts
    └── 10-rule-id-suggest.spec.ts
```
