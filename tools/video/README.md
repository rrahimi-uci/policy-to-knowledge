# Policy to Knowledge — Video Production Package

Automated video generation for the Policy to Knowledge enterprise presentation.

## Files

| File | Purpose |
|---|---|
| `presentation.html` | Self-contained animated HTML presentation (1920×1080) |
| `narration_script.md` | Full narration script with timing and visual notes |
| `generate_video.py` | Python pipeline: TTS audio → browser recording → MP4 |
| `requirements.txt` | Python dependencies for video generation |

## Quick Preview

Open the presentation directly in a browser — no install needed:

```bash
open video/presentation.html          # macOS
xdg-open video/presentation.html      # Linux
start video/presentation.html         # Windows
```

**Keyboard controls:** Space = play/pause, ←→ = prev/next scene, R = restart.

Or use the CLI preview:

```bash
python video/generate_video.py --preview
```

## Generate Video with AI Narration

### Prerequisites

1. **Python 3.10+**
2. **ffmpeg** on PATH:
   ```bash
   brew install ffmpeg        # macOS
   sudo apt install ffmpeg    # Ubuntu
   ```
3. **Install Python packages:**
   ```bash
   pip install -r video/requirements.txt
   playwright install chromium
   ```

### Run

```bash
# Full pipeline (audio + recording + merge → MP4)
python video/generate_video.py

# Audio narration only
python video/generate_video.py --audio-only

# Record presentation only (no audio)
python video/generate_video.py --record-only

# Use a different voice
python video/generate_video.py --voice en-US-GuyNeural

# List available voices
python video/generate_video.py --list-voices
```

### Output

```
video/output/
├── policy-to-knowledge.mp4   # Final video with narration
├── narration.mp3                   # Combined audio track
├── presentation.webm               # Raw video recording
└── audio_segments/                 # Per-scene audio files
```

## Customization

- **Edit narration**: Update `SCENES` array in `generate_video.py` and corresponding text in `narration_script.md`
- **Edit visuals**: Modify `presentation.html` — all CSS/JS is inline for portability
- **Scene timings**: The `SCENE_TIMINGS` array in `presentation.html` must match `duration` values in `generate_video.py`
- **Voice selection**: Run `--list-voices` to see all Microsoft Edge TTS voices

## Recommended Voices

| Voice | Style |
|---|---|
| `en-US-AndrewMultilingualNeural` | Professional, authoritative (default) |
| `en-US-GuyNeural` | Warm, conversational |
| `en-US-JennyNeural` | Clear, professional female |
| `en-US-AriaNeural` | Versatile, natural |

## Scenes (15 total, ~7:02)

| # | Title | Duration |
|---|---|---|
| 1 | Title & Hook | 23s |
| 2 | The Mortgage Compliance Challenge | 28s |
| 3 | The Compliance Lifecycle | 23s |
| 4 | Introducing Policy to Knowledge | 30s |
| 5 | Unified Dashboard | 29s |
| 6 | Knowledge Extraction | 30s |
| 7 | KG Extraction Pipeline | 33s |
| 8 | Compare Knowledge Graphs | 35s |
| 9 | Knowledge Graph & Assistant | 31s |
| 10 | Graph Analytics | 29s |
| 11 | Impact Analysis | 29s |
| 12 | Obligation Register | 24s |
| 13 | Graph Editor & Collaborative Review | 26s |
| 14 | Versioning & Audit Trail | 30s |
| 15 | Platform Vision | 22s |
