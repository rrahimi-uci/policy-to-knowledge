#!/usr/bin/env python3
"""Download and extract the legal/privacy benchmark corpora listed in datasets.json.

Usage:
    python3 scripts/download_benchmarks.py             # all datasets
    python3 scripts/download_benchmarks.py cuad mapp   # a subset
    python3 scripts/download_benchmarks.py --force     # re-download even if present
    python3 scripts/download_benchmarks.py --verify    # checksum/size check only

Archives land in raw/, extracted trees in data/<id>/. Both are git-ignored: the
manifest and this script are the reproducible artifacts, not the corpora.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "datasets.json"
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text())["datasets"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # curl handles the redirects/TLS these hosts use more reliably than urllib.
    subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-delay", "5", "-o", str(tmp), url],
        check=True,
    )
    tmp.replace(dest)


def extract(archive: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            # Reject absolute paths and ../ traversal before writing anything.
            resolved = (target / member.filename).resolve()
            if not str(resolved).startswith(str(target.resolve())):
                raise RuntimeError(f"unsafe path in {archive.name}: {member.filename}")
        zf.extractall(target)


def tree_stats(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="dataset ids (default: all)")
    parser.add_argument("--force", action="store_true", help="re-download existing archives")
    parser.add_argument("--verify", action="store_true", help="report status without downloading")
    args = parser.parse_args()

    datasets = load_manifest()
    if args.ids:
        known = {d["id"] for d in datasets}
        unknown = set(args.ids) - known
        if unknown:
            parser.error(f"unknown dataset id(s): {', '.join(sorted(unknown))}")
        datasets = [d for d in datasets if d["id"] in args.ids]

    failures = []
    for spec in datasets:
        archive = RAW_DIR / spec["archive"]
        target = DATA_DIR / spec["id"]
        print(f"\n=== {spec['id']}: {spec['name']}")

        if args.verify:
            state = "missing"
            if archive.exists():
                state = f"{archive.stat().st_size} bytes, sha256={sha256(archive)[:16]}…"
            count, size = tree_stats(target) if target.exists() else (0, 0)
            print(f"  archive: {state}")
            print(f"  extracted: {count} files, {size / 1e6:.1f} MB")
            continue

        try:
            if archive.exists() and not args.force:
                print(f"  archive present ({archive.stat().st_size / 1e6:.1f} MB), skipping download")
            else:
                print(f"  downloading {spec['url']}")
                download(spec["url"], archive)

            expected = spec.get("bytes")
            actual = archive.stat().st_size
            if expected and actual != expected:
                print(f"  WARNING: size {actual} != manifest {expected} (upstream may have republished)")

            print(f"  extracting -> {target.relative_to(ROOT)}")
            extract(archive, target)
            count, size = tree_stats(target)
            print(f"  done: {count} files, {size / 1e6:.1f} MB, sha256={sha256(archive)}")
        except Exception as exc:  # noqa: BLE001 - report and continue to next dataset
            print(f"  FAILED: {exc}")
            failures.append(spec["id"])

    if failures:
        print(f"\nfailed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
