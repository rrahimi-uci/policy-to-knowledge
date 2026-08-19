"""A tiny deterministic XML writer.

``xml.etree`` would serialise these documents, but the compilers need three
guarantees it does not make cheaply: exact child order (both DMN and BPMN declare
``xsd:sequence`` content models, so order is validity, not style), stable
attribute order, and byte-identical output for identical input. The last one is a
requirement, not a nicety — the plan asks that compiling the same admitted IR
twice produce matching hashes.

All text and attribute values are escaped as data. Source text containing
``<foo>`` or ``&`` or a FEEL fragment is therefore inert content, never markup:
the "XML injection" row of the stress matrix is handled here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_TEXT_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
_ATTR_ESCAPES = _TEXT_ESCAPES + (('"', "&quot;"), ("\n", "&#10;"), ("\r", "&#13;"), ("\t", "&#9;"))


def escape_text(value: str) -> str:
    for needle, replacement in _TEXT_ESCAPES:
        value = value.replace(needle, replacement)
    return value


def escape_attribute(value: str) -> str:
    for needle, replacement in _ATTR_ESCAPES:
        value = value.replace(needle, replacement)
    return value


@dataclass
class Element:
    """One XML element. Children keep insertion order, which is content-model order."""

    tag: str
    attrib: dict[str, str] = field(default_factory=dict)
    text: str | None = None
    children: list["Element"] = field(default_factory=list)

    def child(self, tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> "Element":
        """Append a child and return it, so callers can nest fluently."""
        element = Element(tag, dict(attrib or {}), text)
        self.children.append(element)
        return element

    def append(self, element: "Element") -> "Element":
        self.children.append(element)
        return element


def _render(element: Element, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    attributes = "".join(
        f' {name}="{escape_attribute(value)}"' for name, value in element.attrib.items()
    )
    if not element.children and element.text is None:
        out.append(f"{pad}<{element.tag}{attributes}/>")
        return
    if not element.children and element.text is not None:
        out.append(f"{pad}<{element.tag}{attributes}>{escape_text(element.text)}</{element.tag}>")
        return
    out.append(f"{pad}<{element.tag}{attributes}>")
    if element.text is not None:
        out.append(f"{pad}  {escape_text(element.text)}")
    for child in element.children:
        _render(child, depth + 1, out)
    out.append(f"{pad}</{element.tag}>")


def serialize(root: Element) -> str:
    """Serialise a tree with an XML declaration, two-space indent and a final LF."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    _render(root, 0, lines)
    return "\n".join(lines) + "\n"
