"""Strict mapping helpers shared by the Policy IR record parsers.

Every parser rejects unknown keys. The plan is explicit that "no prompt-level
self-check substitutes for schema validation": silently dropping a field the
model invented would hide exactly the drift the gate is meant to catch.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

T = TypeVar("T")


class SchemaError(ValueError):
    """Raised when a record does not match the Policy IR contract."""


def check_keys(
    data: Mapping[str, Any],
    record: str,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> None:
    """Reject unknown and missing keys for a record type."""
    if not isinstance(data, Mapping):
        raise SchemaError(f"{record} must be an object, got {type(data).__name__}")
    allowed = {*required, *optional}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SchemaError(f"{record}: unknown key(s) {unknown}")
    missing = sorted(k for k in required if k not in data)
    if missing:
        raise SchemaError(f"{record}: missing key(s) {missing}")


def as_str(value: Any, record: str, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{record}.{key} must be a non-empty string, got {value!r}")
    return value


def as_int(value: Any, record: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{record}.{key} must be an integer, got {value!r}")
    return value


def as_tuple_of_str(value: Any, record: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaError(f"{record}.{key} must be a list of strings, got {value!r}")
    return tuple(as_str(v, record, key) for v in value)


def as_tuple(
    value: Any, record: str, key: str, builder: Callable[[Mapping[str, Any]], T]
) -> tuple[T, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SchemaError(f"{record}.{key} must be a list of objects, got {value!r}")
    return tuple(builder(v) for v in value)


def as_enum(enum_cls: Any, value: Any, record: str, key: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = sorted(m.value for m in enum_cls)
        raise SchemaError(f"{record}.{key}: {value!r} is not one of {allowed}") from exc


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    """Remove ``None`` values so serialised records stay minimal and stable."""
    return {k: v for k, v in data.items() if v is not None}
