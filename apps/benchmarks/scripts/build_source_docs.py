#!/usr/bin/env python3
"""Materialize `<benchmark>-source-docs/` folders of pipeline-ready plaintext.

Each benchmark ships its documents in a different shape — plaintext, `|||`-segmented
HTML, or embedded in the annotation JSON. This normalizes all four to `.txt` (one of
the pipeline's supported extensions) in a flat folder per benchmark, so each can be
run through the extraction pipeline into its own knowledge graph:

    python3 scripts/build_source_docs.py
    python3 scripts/build_source_docs.py cuad --limit 20    # small pilot run
    cd ../pipeline && python3 cli/extract.py --source ../benchmarks/cuad-source-docs

For every benchmark the text emitted is the exact text the gold annotations index
into, so extracted rules stay alignable with the gold labels. Each folder gets a
`_manifest.json` mapping the emitted filename back to its annotation key; the
pipeline ignores it, since it only globs supported document extensions.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The pipeline names output directories after the document stem, so leave headroom
# under the 255-byte filesystem limit for its suffixes. CUAD stems reach 165 chars.
MAX_STEM = 120


def safe_stem(name: str) -> str:
    """Filesystem-safe, length-capped stem. Collisions are resolved by the caller."""
    stem = unicodedata.normalize("NFKD", unquote(name))
    stem = re.sub(r"[^\w\-. ]+", "_", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)
    return stem[:MAX_STEM].strip(" .") or "document"


class Writer:
    """Writes .txt documents into a target folder, keeping stems unique."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.seen: dict[str, int] = {}
        self.entries: list[dict] = []

    def add(self, stem: str, text: str, origin: dict) -> None:
        stem = safe_stem(stem)
        count = self.seen.get(stem, 0)
        self.seen[stem] = count + 1
        if count:
            stem = f"{stem}__{count + 1}"
        path = self.target / f"{stem}.txt"
        path.write_text(text, encoding="utf-8")
        self.entries.append({"document": path.name, "chars": len(text), **origin})


def build_cuad(w: Writer) -> None:
    """510 commercial contracts — already plaintext, and the text CUAD_v1.json quotes."""
    src = DATA / "cuad/CUAD_v1/full_contract_txt"
    for path in sorted(src.glob("*.txt")):
        w.add(path.stem, path.read_text(encoding="utf-8", errors="replace"),
              {"source_file": path.name, "annotation_key": path.stem})


def build_opp_115(w: Writer) -> None:
    """115 privacy policies. Sanitized HTML is `|||`-segmented with <br> as the only tag;
    annotations reference the zero-indexed segment, so segment order is preserved and
    each block is emitted in order with its index recorded."""
    src = DATA / "opp-115/OPP-115/sanitized_policies"
    for path in sorted(src.glob("*.html")):
        raw = path.read_text(encoding="utf-8", errors="replace")
        segments = []
        for segment in raw.split("|||"):
            segment = re.sub(r"<br\s*/?>", "\n", segment, flags=re.I)
            segment = re.sub(r"<[^>]+>", "", segment)
            segment = html.unescape(segment)
            segment = re.sub(r"[ \t]+", " ", segment)
            segment = re.sub(r"\n{3,}", "\n\n", segment).strip()
            segments.append(segment)
        w.add(path.stem, "\n\n".join(segments) + "\n",
              {"source_file": path.name, "annotation_key": path.stem,
               "annotations": f"data/opp-115/OPP-115/annotations/{path.stem}.csv",
               "segments": len(segments)})


def build_contract_nli(w: Writer) -> None:
    """607 NDAs. The split JSONs carry the canonical `text` that every span offset and
    NLI label indexes into — truer to the gold than re-extracting the raw PDFs/HTML."""
    src = DATA / "contract-nli/contract-nli"
    for split in ("train", "dev", "test"):
        payload = json.loads((src / f"{split}.json").read_text(encoding="utf-8"))
        for doc in payload["documents"]:
            stem = Path(unquote(doc["file_name"])).stem
            w.add(f"{split}_{doc['id']}_{stem}", doc["text"],
                  {"source_file": doc["file_name"], "annotation_key": doc["id"],
                   "split": split, "spans": len(doc.get("spans", [])),
                   "document_type": doc.get("document_type")})


def build_mapp(w: Writer) -> None:
    """64 English + 91 German mobile-app policies. Already plaintext; the language prefix
    keeps both halves in one flat folder without colliding."""
    for lang, folder in (("en", "English_sanitized_policies"), ("de", "German_sanitized_policies")):
        src = DATA / "mapp/MAPP_Corpus" / folder
        consolidation = f"{'English' if lang == 'en' else 'German'}_consolidation"
        for path in sorted(src.glob("*.txt")):
            w.add(f"{lang}_{path.stem}", path.read_text(encoding="utf-8", errors="replace"),
                  {"source_file": path.name, "annotation_key": path.stem, "language": lang,
                   "annotations": f"data/mapp/MAPP_Corpus/{consolidation}/{path.stem}.csv"})


BUILDERS = {
    "cuad": ("data/cuad", build_cuad),
    "opp-115": ("data/opp-115", build_opp_115),
    "contract-nli": ("data/contract-nli", build_contract_nli),
    "mapp": ("data/mapp", build_mapp),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", choices=list(BUILDERS), default=list(BUILDERS),
                        metavar="ID", help="benchmark ids to build (default: all)")
    parser.add_argument("--limit", type=int, default=None,
                        help="keep only the first N documents — for cheap pilot runs")
    args = parser.parse_args()

    ids = args.ids or list(BUILDERS)
    missing = [i for i in ids if not (ROOT / BUILDERS[i][0]).exists()]
    if missing:
        print(f"corpora not downloaded: {', '.join(missing)}")
        print("run: python3 scripts/download_benchmarks.py " + " ".join(missing))
        return 1

    for benchmark_id in ids:
        _, builder = BUILDERS[benchmark_id]
        target = ROOT / f"{benchmark_id}-source-docs"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        writer = Writer(target)
        builder(writer)

        if args.limit is not None:
            for entry in writer.entries[args.limit:]:
                (target / entry["document"]).unlink()
            writer.entries = writer.entries[: args.limit]

        total = sum(e["chars"] for e in writer.entries)
        (target / "_manifest.json").write_text(json.dumps({
            "benchmark": benchmark_id,
            "documents": len(writer.entries),
            "total_chars": total,
            "note": "Plaintext derived from the gold-annotated text; see ../datasets.json.",
            "files": writer.entries,
        }, indent=2) + "\n", encoding="utf-8")

        print(f"{benchmark_id + '-source-docs':<28} {len(writer.entries):>4} docs  "
              f"{total / 1e6:>6.1f} M chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
