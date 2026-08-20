"""Chart marks, built in plain HTML so every one can carry a visible label.

Bars are ``div`` widths rather than SVG. That is deliberate: a labelled bar is the
relief the palette's contrast warnings require, and a DOM bar can hold its own label,
its own tooltip and its own ``aria`` text without a text-measurement pass.

Mark specs applied throughout: data-ends rounded 4px and anchored to the baseline, a 2px
surface gap between adjacent fills so touching segments stay separable, recessive
gridlines, and no number printed on every element where one label per row will do.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class Slice:
    """One labelled quantity."""

    label: str
    value: float
    colour: str
    icon: str = ""
    note: str = ""


def _pct(value: float, total: float) -> float:
    return (value / total * 100.0) if total else 0.0


def stat_tile(label: str, value: str, note: str = "") -> str:
    """A hero number. No plot, so no tooltip — the number *is* the answer."""
    return (
        '<div class="tile">'
        f'<div class="tile-value">{escape(value)}</div>'
        f'<div class="tile-label">{escape(label)}</div>'
        + (f'<div class="tile-note">{escape(note)}</div>' if note else "")
        + "</div>"
    )


def stacked_bar(slices: list[Slice], *, total: float | None = None) -> str:
    """One horizontal bar of mutually exclusive parts, with an icon+label legend.

    Segments are separated by a 2px surface gap so neighbouring fills never appear to
    merge, and each carries its icon in the legend so the categories remain
    distinguishable without colour.
    """
    present = [s for s in slices if s.value > 0]
    denominator = total if total is not None else sum(s.value for s in present)
    if not present or denominator <= 0:
        return '<p class="empty">No coverage recorded.</p>'
    segments = "".join(
        f'<span class="seg" style="width:{_pct(s.value, denominator):.4f}%;background:{s.colour}" '
        f'title="{escape(s.label)}: {s.value:,.0f} ({_pct(s.value, denominator):.1f}%)" '
        f'aria-label="{escape(s.label)}: {s.value:,.0f}"></span>'
        for s in present
    )
    legend = "".join(
        '<li><span class="chip" style="background:%s" aria-hidden="true"></span>'
        '<span class="chip-icon" aria-hidden="true">%s</span>'
        '<span class="chip-label">%s</span>'
        '<span class="chip-value">%s <span class="chip-pct">%.1f%%</span></span></li>'
        % (s.colour, escape(s.icon), escape(s.label), f"{s.value:,.0f}", _pct(s.value, denominator))
        for s in present
    )
    return f'<div class="stack" role="img">{segments}</div><ul class="legend">{legend}</ul>'


def bar_rows(
    slices: list[Slice],
    *,
    max_value: float | None = None,
    unit: str = "",
    keep_zeros: bool = False,
) -> str:
    """Horizontal bars, one row per category, every bar directly labelled.

    Rows are ordered by the caller. Where a single measure is being compared the caller
    passes one colour for every slice, because one series needs one hue — the ordering is
    already carried by row position.

    ``keep_zeros`` decides what a zero means, which depends on the vocabulary:

    * listing what was *observed* — blockers raised, fields missing — a zero row is
      noise, so zeros are dropped by default;
    * listing a *fixed* set — the six statuses — a zero is the finding. Dropping
      "DMN eligible: 0" made the status look like it did not exist, when it was the
      most important number on the page.
    """
    present = [s for s in slices if keep_zeros or s.value > 0]
    if not present:
        return '<p class="empty">Nothing to show.</p>'
    ceiling = max_value if max_value is not None else max(s.value for s in present)
    rows = []
    for s in present:
        width = _pct(s.value, ceiling)
        # The floor keeps a small non-zero value visible; a true zero must draw nothing,
        # or the bar contradicts the number printed beside it.
        width = max(width, 0.6) if s.value > 0 else 0.0
        rows.append(
            '<div class="row">'
            f'<div class="row-label" title="{escape(s.note or s.label)}">{escape(s.label)}</div>'
            '<div class="row-track">'
            f'<div class="row-fill" style="width:{width:.4f}%;background:{s.colour}" '
            f'title="{escape(s.label)}: {s.value:,.0f}{escape(unit)}"></div>'
            "</div>"
            f'<div class="row-value">{s.value:,.0f}{escape(unit)}</div>'
            "</div>"
        )
    return f'<div class="bars">{"".join(rows)}</div>'
