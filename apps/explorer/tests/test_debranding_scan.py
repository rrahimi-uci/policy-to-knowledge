import base64
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
    # Gitignored generated artifacts and user-supplied proprietary inputs.
    # These never enter the public repo, so they are out of scope for the
    # branding scan (which guards what is actually committed).
    "coverage-html",
    "htmlcov",
    "allure-results",
    "pipeline-output",
    "pipeline-data",
    "pipeline-logs",
    "compliance-files",
    "kbs",
    "kgs",
}
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
PLAIN_FILENAMES = {"Dockerfile", "Makefile", "README", "README.md"}


def _legacy_markers() -> list[str]:
    encoded = (
        "amF6eng=",
        "Y29ydGV4",
        "Y29waWxvdA==",
        "Y29waWxvdGtpdA==",
        "a2VybmVsLWxhYg==",
        "eW91ci1vcmc=",
        "ZmFubmll",
        "ZnJlZGRpZQ==",
        "Zm5tYQ==",
        "ZmhsbWM=",
        "Zm1uYQ==",
        "YmFyY2xheXM=",
        "YWJzYQ==",
        "cmV2b2x1dGlvbg==",
        "cHJtaQ==",
    )
    return [base64.b64decode(item).decode("utf-8") for item in encoded]


def _should_scan(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix in TEXT_SUFFIXES or path.name in PLAIN_FILENAMES


def test_repo_is_debranded():
    markers = _legacy_markers()
    matches: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or not _should_scan(path):
            continue

        rel = path.relative_to(REPO_ROOT)
        rel_text = str(rel).lower()
        for marker in markers:
            if marker in rel_text:
                matches.append(f"{rel}: path contains '{marker}'")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        lower = content.lower()
        for marker in markers:
            if marker in lower:
                matches.append(f"{rel}: content contains '{marker}'")

    assert not matches, "Legacy branding markers remain:\n" + "\n".join(matches[:100])
