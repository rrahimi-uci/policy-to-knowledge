"""The report's colour system, validated rather than chosen by eye.

Every palette below was checked with the data-viz validator against the surfaces the
report actually renders on, in both modes. The results are recorded so nobody has to
re-derive them, and so a change is visibly a change:

* **Modality (5 categorical, adjacent pairs — bar chart).** Light: PASS, worst adjacent
  CVD ΔE 9.1, normal-vision 19.6; three slots fall below 3:1 on the light surface, so the
  relief rule applies and every bar carries a visible direct label. Dark: PASS on all
  five checks.
* **Graph node types (3 categorical, ALL pairs — a node-link diagram compares
  everything to everything).** Light PASS (worst all-pairs CVD ΔE 9.2, normal-vision
  24.0), dark PASS. Capped at three slots because the documented palette clears the
  all-pairs floors only for its first three; anything else folds into neutral, and node
  *shape* carries identity as a second channel so colour never carries it alone.
* **Funnel and blockers.** One measure, one series, so one hue. Order is carried by bar
  length, which is what position is for; a ramp here would encode the ordering twice and
  failed the adjacent-lightness gate anyway.
* **Coverage.** The fixed status palette, never themed. ``warning`` is sub-3:1 on the
  light surface by design, so it always ships with an icon and a label.
"""

from __future__ import annotations

# -- surfaces (the validator's reference surfaces, so its results apply directly) ----
SURFACE_LIGHT = "#fcfcfb"
SURFACE_DARK = "#1a1a19"

INK_LIGHT = "#0b0b0b"
INK_DARK = "#ffffff"
MUTED_LIGHT = "#52514e"
MUTED_DARK = "#c3c2b7"

# -- categorical: modality (slots 1-5 of the documented order) ----------------------
MODALITY_ORDER = ("obligation", "prohibition", "permission", "recommendation", "definition")
MODALITY_LIGHT = {
    "obligation": "#2a78d6",
    "prohibition": "#eb6834",
    "permission": "#1baf7a",
    "recommendation": "#eda100",
    "definition": "#e87ba4",
}
MODALITY_DARK = {
    "obligation": "#3987e5",
    "prohibition": "#d95926",
    "permission": "#199e70",
    "recommendation": "#c98500",
    "definition": "#d55181",
}

# -- categorical: graph node types (first three slots only; rest fold to neutral) ----
NODE_LIGHT = {"clause": "#2a78d6", "section": "#eb6834", "document": "#1baf7a"}
NODE_DARK = {"clause": "#3987e5", "section": "#d95926", "document": "#199e70"}
NODE_NEUTRAL_LIGHT = "#8a8984"
NODE_NEUTRAL_DARK = "#6f6e69"

#: Shape is the second identity channel, so colour never carries type alone.
NODE_SHAPES = {"clause": "dot", "section": "square", "document": "diamond", "other": "triangle"}

# -- single-series hue (funnel, blockers) -------------------------------------------
SERIES_LIGHT = "#2a78d6"
SERIES_DARK = "#3987e5"

# -- status palette (fixed, never themed) -------------------------------------------
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

#: Coverage states, each with the icon that carries its meaning without colour.
COVERAGE_STATES = (
    ("candidates_emitted", "Clauses extracted", STATUS["good"], "●"),
    ("no_policy_semantics_found", "No requirement stated", STATUS["warning"], "◐"),
    ("extraction_failed", "No extractable text", STATUS["critical"], "▲"),
    ("processed", "Read, not yet extracted", "#8a8984", "○"),
    ("intentionally_excluded", "Excluded", "#8a8984", "—"),
    ("unresolved", "Unresolved", STATUS["serious"], "◆"),
)

GRID_LIGHT = "#e7e6e2"
GRID_DARK = "#33322f"
