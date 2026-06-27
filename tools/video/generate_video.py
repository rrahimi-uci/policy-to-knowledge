#!/usr/bin/env python3
"""
Generate Policy to Knowledge video with AI narration.

Usage:
    python generate_video.py                    # Full pipeline: audio + video + merge
    python generate_video.py --audio-only       # Generate narration audio only
    python generate_video.py --record-only      # Record presentation only (no audio)
    python generate_video.py --voice en-US-JennyNeural   # Use a different voice
    python generate_video.py --preview          # Open presentation in browser for preview

Prerequisites:
    pip install -r requirements.txt
    playwright install chromium
    ffmpeg must be on PATH
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

# ── Scene definitions ─────────────────────────────────────────────────────
# Each scene has: id, title, duration (seconds), narration text.
# Durations must match SCENE_TIMINGS in presentation.html.

SCENES = [
    {
        "id": 1,
        "title": "Title & Hook",
        "duration": 23,
        "narration": (
            "In mortgage lending, regulatory compliance is not optional. It is operational. "
            "Sample Guidelines, Example Policies, and federal agencies issue hundreds of updates every year. "
            "Policy to Knowledge transforms that complexity into structured, actionable intelligence."
        ),
    },
    {
        "id": 2,
        "title": "The Mortgage Compliance Challenge",
        "duration": 28,
        "narration": (
            "Consider the scale of the challenge. "
            "Mortgage lenders face over three hundred regulatory updates per year. "
            "Each major update takes an average of seventy-two hours of manual impact analysis. "
            "And audit preparation overhead multiplies five times across siloed teams. "
            "The result? Compliance teams buried in documents, struggling to keep pace."
        ),
    },
    {
        "id": 3,
        "title": "The Compliance Lifecycle",
        "duration": 23,
        "narration": (
            "That burden spans an entire lifecycle, from regulatory monitoring and "
            "document ingestion, through knowledge extraction and change detection, "
            "to impact analysis, obligation management, and audit defense. "
            "Today, most teams handle this entire cycle with spreadsheets and manual reviews."
        ),
    },
    {
        "id": 4,
        "title": "Introducing Policy to Knowledge",
        "duration": 30,
        "narration": (
            "Policy to Knowledge is a regulatory intelligence platform for highly regulated "
            "enterprises. It consumes compliance documents, including policies, "
            "standards, regulatory rules, and legal overlays, and transforms them into "
            "structured knowledge. From document ingestion to obligation management, Policy to Knowledge "
            "replaces manual processes with an intelligent, auditable system."
        ),
    },
    {
        "id": 5,
        "title": "Unified Dashboard",
        "duration": 29,
        "narration": (
            "Everything starts here, with the Policy to Knowledge dashboard. "
            "Policy to Knowledge has created seven knowledge graphs spanning high-compliance domains, "
            "including Sample Guidelines and Example Policies in mortgage, Anti-Money Laundering, "
            "commercial lending, and healthcare. "
            "Fifty-three source documents ingested, over two thousand rules extracted "
            "across these enterprise domains, and the compliance assistant connected and ready."
        ),
    },
    {
        "id": 6,
        "title": "Knowledge Extraction",
        "duration": 30,
        "narration": (
            "Upload any compliance document, selling guides, regulatory handbooks, "
            "policy standards, or legal overlays, and Policy to Knowledge processes them through "
            "its extraction engine. The Run History tracks every pipeline execution "
            "across domains: mortgage, healthcare, AML, and commercial lending. "
            "Each run records domain, duration, and status, providing full traceability "
            "from document ingestion to knowledge graph creation."
        ),
    },
    {
        "id": 7,
        "title": "KG Extraction Pipeline",
        "duration": 33,
        "narration": (
            "Behind every extraction is a seven-step AI pipeline. "
            "Document Segmentation organizes raw documents into semantic chunks. "
            "Entity Discovery identifies key domain concepts and relationships. "
            "Business Rules Extraction captures every rule using parallel reasoning models. "
            "Quality Validation ensures accuracy. Entity Integration links rules to entities. "
            "Finally, Deduplication and Graph Visualization produce the optimized knowledge graph. "
            "Here, a mortgage extraction completed all seven steps in just under twenty minutes, "
            "with full cost and duration captured for every step."
        ),
    },
    {
        "id": 8,
        "title": "Compare Knowledge Graphs",
        "duration": 35,
        "narration": (
            "Policy to Knowledge lets you compare any two knowledge graphs side by side using AI-powered "
            "semantic analysis. Here, the Sample Guidelines Selling Guide with three hundred fifty-two rules "
            "is compared against Example Policies with three hundred eighty-three rules. "
            "The comparison reveals sixteen shared rules, three hundred thirty-six unique to Sample Guidelines, "
            "three hundred sixty-seven unique to Example Policies, and fourteen semantic contradictions. "
            "Each contradiction includes a detailed AI analysis explaining the conflict and its implications. "
            "This is then reviewed by human experts and used to refine the extraction and comparison models for even deeper insights over time."
        ),
    },
    {
        "id": 9,
        "title": "Knowledge Graph & Assistant",
        "duration": 31,
        "narration": (
            "Here is what extraction produces: a living knowledge graph with two hundred "
            "ninety-nine nodes and three hundred sixty-six edges, color-coded across eleven "
            "node types. The integrated Assistant lets you query eligibility "
            "requirements, trace dependencies, and get citation-backed answers grounded "
            "in your regulatory knowledge. It also helps compliance teams edit, share, "
            "and refine the extracted rules."
        ),
    },
    {
        "id": 10,
        "title": "Graph Analytics",
        "duration": 29,
        "narration": (
            "Policy to Knowledge provides deep analytics on every knowledge graph. For example, the Sample Guidelines "
            "Selling Guide analysis shows three hundred fifty-two rules, thirteen "
            "dependencies, and forty-three entity types. The risk breakdown reveals "
            "two hundred three high-risk and one hundred twenty-eight critical rules, "
            "with an average confidence of eighty-eight point six percent."
        ),
    },
    {
        "id": 11,
        "title": "Impact Analysis",
        "duration": 29,
        "narration": (
            "When regulations change, Impact Analysis lets you upload old and new versions "
            "of any regulatory document against your knowledge graph. The agentic AI engine "
            "classifies every change by severity: breaking, material, or cosmetic. "
            "It maps each change to affected rules, generates an executive summary, "
            "priority recommendations, and a full risk assessment, all in a single automated run."
        ),
    },
    {
        "id": 12,
        "title": "Obligation Register",
        "duration": 24,
        "narration": (
            "Every extracted rule becomes a trackable obligation. The Obligation Register "
            "lets teams auto-import from the graph, map controls, identify gaps, and "
            "track compliance scores through heatmaps. AI-powered suggestions recommend "
            "controls based on risk level. Everything is exportable for audit and exam."
        ),
    },
    {
        "id": 13,
        "title": "Graph Editor & Collaborative Review",
        "duration": 26,
        "narration": (
            "The Graph Editor enables collaborative knowledge refinement. Compliance "
            "teams can edit node properties, add rules with AI-suggested connections, "
            "and use AI-powered rewriting. Every node supports formal review workflows "
            "with reviewed and approved status, team comments, and full version history "
            "with diffs and one-click revert."
        ),
    },
    {
        "id": 14,
        "title": "Versioning & Audit Trail",
        "duration": 30,
        "narration": (
            "The Versions and Releases module creates frozen snapshots of the entire graph "
            "under semantic version tags. Released graphs are automatically locked. "
            "The release timeline preserves every version for comparison. For regulated "
            "institutions, this creates a complete audit trail, every edit, review, and "
            "approval is timestamped and serves as defensible evidence."
        ),
    },
    {
        "id": 15,
        "title": "Platform Vision",
        "duration": 22,
        "narration": (
            "Policy to Knowledge is not just a mortgage tool. It is a platform service. The same "
            "knowledge graph engine and AI pipeline apply to any regulatory domain. "
            "Mortgage and banking compliance today. Anti-money laundering and insurance compliance next. "
            "One intelligent engine, every enterprise domain."
        ),
    },
]

TOTAL_DURATION = sum(s["duration"] for s in SCENES)
HERE = Path(__file__).resolve().parent
HTML_PATH = HERE / "presentation.html"
OUTPUT_DIR = HERE / "output"

# Timing parameters — controls the gap between scenes
INTER_SCENE_BUFFER = 3  # seconds of silence after narration ends
INTER_SCENE_DELAY = 250  # milliseconds of silence before each scene (except first)


# ── Audio generation ──────────────────────────────────────────────────────


async def generate_audio(voice: str, rate: str = "+0%") -> tuple[Path, list[int]]:
    """Generate narration audio using edge-tts — one segment per scene.

    Returns (audio_path, computed_scene_durations).
    """
    try:
        import edge_tts
    except ImportError:
        print("ERROR: edge-tts not installed. Run: pip install edge-tts")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_dir = OUTPUT_DIR / "audio_segments"
    audio_dir.mkdir(exist_ok=True)

    concat_list: list[str] = []
    computed_durations: list[int] = []

    for scene in SCENES:
        seg_path = audio_dir / f"scene_{scene['id']:02d}.mp3"
        print(f"  Generating audio: Scene {scene['id']} — {scene['title']}...")

        communicate = edge_tts.Communicate(
            text=scene["narration"],
            voice=voice,
            rate=rate,
        )
        await communicate.save(str(seg_path))

        # Measure actual narration duration to avoid cropping and tighten gaps.
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(seg_path),
            ],
            capture_output=True,
            text=True,
        )
        actual_dur = float(probe.stdout.strip())
        effective_dur = math.ceil(actual_dur) + INTER_SCENE_BUFFER
        computed_durations.append(effective_dur)
        print(f"    Narration: {actual_dur:.1f}s → scene: {effective_dur}s")

        # Pad narration to computed duration (narration + buffer).
        padded_path = audio_dir / f"scene_{scene['id']:02d}_padded.mp3"
        if scene["id"] == 1:
            af = f"apad=pad_dur={effective_dur},atrim=0:{effective_dur}"
        else:
            af = f"adelay={INTER_SCENE_DELAY}|{INTER_SCENE_DELAY},apad=pad_dur={effective_dur},atrim=0:{effective_dur}"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(seg_path),
                "-af",
                af,
                "-ar",
                "44100",
                "-ac",
                "1",
                str(padded_path),
            ],
            capture_output=True,
        )
        concat_list.append(f"file '{padded_path}'")

    # Concatenate all segments
    concat_file = audio_dir / "concat.txt"
    concat_file.write_text("\n".join(concat_list))

    combined = OUTPUT_DIR / "narration.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(combined),
        ],
        capture_output=True,
        check=True,
    )
    print(f"  Audio saved: {combined}")
    return combined, computed_durations


# ── Prepare HTML with computed timings ────────────────────────────────────


def prepare_html(durations: list[int]) -> Path:
    """Create a copy of presentation.html with updated SCENE_TIMINGS.

    The patched file is written next to the original so that relative asset
    paths (screenshots/, fonts, etc.) resolve correctly under file:// without
    hitting Chromium's cross-directory sandbox restrictions.
    """
    html_text = HTML_PATH.read_text()
    patched = re.sub(
        r"var SCENE_TIMINGS\s*=\s*\[[\d\s,]+\]",
        f"var SCENE_TIMINGS = {durations}",
        html_text,
    )
    patched_path = HERE / "presentation_timed.html"
    patched_path.write_text(patched)
    print(f"  Patched HTML timings: {durations}")
    return patched_path


# ── Video recording ───────────────────────────────────────────────────────


async def record_video(
    html_path: Path | None = None, total_duration: int | None = None
) -> Path:
    """Record the HTML presentation using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_dir = OUTPUT_DIR / "raw_video"
    video_dir.mkdir(exist_ok=True)

    effective_html = html_path or HTML_PATH
    wait_total = total_duration or TOTAL_DURATION
    print(f"  Recording presentation ({wait_total}s)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Load presentation with autoplay
        await page.goto(f"file://{effective_html}?autoplay=true")

        # Wait for total duration plus buffer
        wait_ms = (wait_total + 5) * 1000
        await page.wait_for_timeout(wait_ms)

        # Finalize the video file before closing
        video_path_playwright = await page.video.path()
        await page.close()
        await context.close()
        await browser.close()

    # The video file is finalized after page.close() + context.close()
    output_video = OUTPUT_DIR / "presentation.webm"
    if video_path_playwright and Path(video_path_playwright).exists():
        shutil.move(str(video_path_playwright), str(output_video))
    else:
        # Fallback: find any webm in raw_video dir
        video_files = list(video_dir.glob("*.webm"))
        if not video_files:
            print("ERROR: No video file was recorded.")
            sys.exit(1)
        shutil.move(str(video_files[0]), str(output_video))
    print(f"  Video saved: {output_video}")
    return output_video


# ── Merge audio + video ──────────────────────────────────────────────────


def merge(video_path: Path, audio_path: Path) -> Path:
    """Merge video and audio into final MP4."""
    output = OUTPUT_DIR / "policy-to-knowledge.mp4"
    print("  Merging video + audio...")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
    )
    print(f"\n  Final video: {output}")
    print("  Resolution: 1920x1080")
    return output


# ── Preview mode ──────────────────────────────────────────────────────────


def preview():
    """Open presentation in the default browser."""
    url = f"file://{HTML_PATH}?autoplay=false"
    print(f"  Opening: {url}")
    print("  Controls: Space = play/pause, →/← = next/prev scene, R = restart")
    webbrowser.open(url)


# ── CLI ───────────────────────────────────────────────────────────────────


def check_ffmpeg():
    """Ensure ffmpeg is available."""
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found on PATH.")
        print("  macOS:   brew install ffmpeg")
        print("  Ubuntu:  sudo apt install ffmpeg")
        print("  Windows: choco install ffmpeg")
        sys.exit(1)


def list_voices():
    """List available edge-tts voices."""

    async def _list():
        import edge_tts

        voices = await edge_tts.list_voices()
        en_voices = [v for v in voices if v["Locale"].startswith("en-")]
        print(f"\nAvailable English voices ({len(en_voices)}):\n")
        for v in sorted(en_voices, key=lambda x: x["ShortName"]):
            gender = v.get("Gender", "?")
            print(f"  {v['ShortName']:40s} {gender}")

    asyncio.run(_list())


async def main():
    parser = argparse.ArgumentParser(
        description="Generate Policy to Knowledge presentation video"
    )
    parser.add_argument(
        "--voice",
        default="en-US-AndrewMultilingualNeural",
        help="Edge TTS voice name (default: en-US-AndrewMultilingualNeural)",
    )
    parser.add_argument(
        "--rate",
        default="+5%",
        help="Speech rate adjustment (default: +5%% for slightly faster)",
    )
    parser.add_argument(
        "--audio-only", action="store_true", help="Generate narration audio only"
    )
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="Record presentation video only (no audio)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Open presentation in browser for preview",
    )
    parser.add_argument(
        "--list-voices", action="store_true", help="List available TTS voices"
    )
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return

    if args.preview:
        preview()
        return

    check_ffmpeg()

    print("\n╔══════════════════════════════════════════════════╗")
    print("║   Policy to Knowledge — Video Generation Pipeline       ║")
    print("╚══════════════════════════════════════════════════╝\n")
    print(f"  Scenes:   {len(SCENES)}")
    print(f"  Duration: ~{TOTAL_DURATION // 60}m {TOTAL_DURATION % 60}s (estimated)")
    print(f"  Voice:    {args.voice}")
    print(f"  Output:   {OUTPUT_DIR}\n")

    if args.audio_only:
        print("── Step 1/1: Generating narration audio ──")
        audio_path, durations = await generate_audio(args.voice, args.rate)
        total = sum(durations)
        print(f"\nDone! Audio saved to {audio_path}")
        print(f"Duration: ~{total // 60}m {total % 60}s")
        return

    if args.record_only:
        print("── Step 1/1: Recording presentation ──")
        await record_video()
        print("\nDone! Video saved to video/output/presentation.webm")
        return

    # Full pipeline
    print("── Step 1/3: Generating narration audio ──")
    audio_path, durations = await generate_audio(args.voice, args.rate)

    print("\n── Step 2/3: Recording presentation ──")
    timed_html = prepare_html(durations)
    total = sum(durations)
    video_path = await record_video(timed_html, total)

    print("\n── Step 3/3: Compositing final video ──")
    final = merge(video_path, audio_path)

    print(f"\n{'═' * 50}")
    print(f"  Video ready: {final}")
    print(f"  Duration: ~{total // 60}m {total % 60}s")
    print(f"{'═' * 50}\n")


if __name__ == "__main__":
    asyncio.run(main())
