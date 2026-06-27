"""
Shared JSON logging utility for Explorer.

All microservice logs are single-line JSON with these fields:
  t, severity, message, error, stack_trace
"""

import json
import time
from typing import Optional


def log(severity: str, message: str, *, error: Optional[str] = None,
        stack_trace: Optional[str] = None) -> None:
    """Emit a single-line JSON log entry to stdout."""
    print(
        json.dumps({
            "t": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "severity": severity,
            "message": message,
            "error": error,
            "stack_trace": stack_trace,
        }),
        flush=True,
    )
