"""
Read-only safety guard for the raw Gremlin execution endpoint.

Kept in its own module (no Flask/JanusGraph imports) so it is cheap to unit-test
and reuse from both the HTTP endpoint and the chat tool executor.
"""

import re

# Mutating graph *steps* — only dangerous when invoked as a call, e.g. `.drop()`
# or `.property(k, v)`. We require a trailing `(` so a read query that merely
# references one of these words as a string key (e.g. has("property", x)) is allowed.
_GREMLIN_MUTATION_STEPS = ("drop", "addv", "adde", "property", "remove")

# Host-level / scripting tokens that must never appear in a read query.
_GREMLIN_HOST_TOKENS = (
    "system", "thread", "runtime", "process", "file",
    "import", "new ", "evaluate", "java.", "groovy.", "execfile", "exec(",
)


def gremlin_safety_violation(query_str):
    """Return the first blocked token found in a query, or None if it looks safe.

    String literals are stripped before matching so that blocklisted words used
    purely as data (e.g. a property key named "process") don't trip the guard.
    """
    lowered = (query_str or "").lower()
    # Remove quoted string literals so data values/keys are not inspected.
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", lowered)

    for token in _GREMLIN_MUTATION_STEPS:
        if re.search(r"\b" + re.escape(token) + r"\s*\(", stripped):
            return token
    for token in _GREMLIN_HOST_TOKENS:
        pattern = re.escape(token) if token.endswith((" ", "(")) else r"\b" + re.escape(token) + r"\b"
        if re.search(pattern, stripped):
            return token.strip()
    return None
