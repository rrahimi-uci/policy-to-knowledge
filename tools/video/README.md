# Policy to Knowledge — Demo Video Generator

A self-contained tool that turns the Policy to Knowledge presentation deck into
a narrated demo video. The deck (`presentation.html`) is recorded with
Playwright, AI narration is synthesized with [edge-tts][edge-tts], and the two
are merged with `ffmpeg` into `output/policy-to-knowledge.mp4`.

All commands below are run from this directory (`tools/video/`).

## Files

| File | Purpose |
| --- | --- |
| `presentation.html` | Self-contained animated HTML deck (1920×1080) |
| `narration_script.md` | Full narration script with timing and visual notes |
| `generate_video.py` | Pipeline: TTS audio → browser recording → MP4 |
| `requirements.txt` | Python dependencies (`edge-tts`, `playwright`) |

## Quick preview

Open the deck directly in a browser — no install required:

```bash
open presentation.html          # macOS
xdg-open presentation.html      # Linux
start presentation.html         # Windows
```

**Keyboard controls:** `Space` = play/pause, `←` / `→` = previous/next scene,
`R` = restart.

You can also launch the preview through the CLI:

```bash
python generate_video.py --preview
```

## Generating the video

### Prerequisites

1. **Python 3.10+**
2. **ffmpeg** on your `PATH`:

   ```bash
   brew install ffmpeg        # macOS
   sudo apt install ffmpeg    # Ubuntu
   choco install ffmpeg       # Windows
   ```

3. **Python packages** and the Playwright Chromium browser:

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

### Usage

```bash
# Full pipeline (audio + recording + merge → MP4)
python generate_video.py

# Narration audio only
python generate_video.py --audio-only

# Record the presentation only (no audio)
python generate_video.py --record-only

# Use a different voice
python generate_video.py --voice en-US-GuyNeural

# List available voices
python generate_video.py --list-voices
```

### Output

```text
output/
├── policy-to-knowledge.mp4   # Final video with narration
├── narration.mp3             # Combined audio track
├── presentation.webm         # Raw screen recording
└── audio_segments/           # Per-scene audio files
```

## Customization

- **Narration text** — update the `SCENES` array in `generate_video.py` and the
  matching text in `narration_script.md`.
- **Visuals** — edit `presentation.html`; all CSS and JS are inline for
  portability.
- **Scene timings** — the `SCENE_TIMINGS` array in `presentation.html` must
  match the `duration` values in `generate_video.py`.
- **Voice** — run `--list-voices` to see all Microsoft Edge TTS voices.

## Recommended voices

| Voice | Style |
| --- | --- |
| `en-US-AndrewMultilingualNeural` | Professional, authoritative (default) |
| `en-US-GuyNeural` | Warm, conversational |
| `en-US-JennyNeural` | Clear, professional |
| `en-US-AriaNeural` | Versatile, natural |

## Scenes (15 total, ~7:02)

| # | Title | Duration |
| --- | --- | --- |
| 1 | Title & Hook | 23s |
| 2 | The Mortgage Compliance Challenge | 28s |
| 3 | The Compliance Lifecycle | 23s |
| 4 | Introducing Policy to Knowledge | 30s |
| 5 | Unified Dashboard | 29s |
| 6 | Knowledge Extraction | 30s |
| 7 | Knowledge Graph Extraction Pipeline | 33s |
| 8 | Compare Knowledge Graphs | 35s |
| 9 | Knowledge Graph & Assistant | 31s |
| 10 | Graph Analytics | 29s |
| 11 | Impact Analysis | 29s |
| 12 | Obligation Register | 24s |
| 13 | Graph Editor & Collaborative Review | 26s |
| 14 | Versioning & Audit Trail | 30s |
| 15 | Platform Vision | 22s |

[edge-tts]: https://github.com/rany2/edge-tts
