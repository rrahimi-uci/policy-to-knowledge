#!/usr/bin/env python3
"""Download and hash-verify the normative OMG schemas.

The schemas are not committed: they are OMG documents, and the plan is explicit
that source and specification rights need an explicit ledger rather than casual
redistribution. ``schemas/PINNED.json`` records the URL and SHA-256 of every file
this compiler validates against, so a fetch either reproduces exactly those bytes
or fails.

CI does not run this. Unit tests are offline and use the structural validators in
:mod:`compilers.verify`; XSD validation is an explicit, network-dependent step::

    python scripts/fetch_schemas.py --into schemas/omg
    python -m pytest tests/ -m xsd --xsd-dir schemas/omg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PINNED = _ROOT / "schemas" / "PINNED.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(into: Path, *, timeout: float = 30.0, verify_only: bool = False) -> int:
    pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    failures = 0
    for family in ("dmn", "bpmn"):
        for relative, record in sorted(pinned[family]["files"].items()):
            target = into / relative
            expected = record["sha256"]
            if target.exists():
                actual = _sha256(target.read_bytes())
                if actual == expected:
                    print(f"ok       {relative}")
                    continue
                print(f"MISMATCH {relative}: have {actual[:12]}…, expected {expected[:12]}…")
                failures += 1
                continue
            if verify_only:
                print(f"MISSING  {relative}")
                failures += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"fetch    {relative} <- {record['url']}")
            with urllib.request.urlopen(record["url"], timeout=timeout) as response:
                data = response.read()
            actual = _sha256(data)
            if actual != expected:
                print(f"MISMATCH {relative}: downloaded {actual[:12]}…, expected {expected[:12]}…")
                failures += 1
                continue
            target.write_bytes(data)
    if failures:
        print(f"\n{failures} file(s) did not match the pinned hashes", file=sys.stderr)
    else:
        print("\nall pinned schemas present and verified")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--into",
        type=Path,
        default=_ROOT / "schemas" / "omg",
        help="Directory to download into (default: schemas/omg).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check existing files against the pinned hashes without downloading.",
    )
    args = parser.parse_args(argv)
    return fetch(args.into, verify_only=args.verify_only)


if __name__ == "__main__":
    raise SystemExit(main())
