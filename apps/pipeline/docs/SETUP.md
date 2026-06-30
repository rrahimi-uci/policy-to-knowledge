# Setup Guide

Local development setup for the **pipeline** app: a FastAPI backend, a React/Vite UI, and a 10-agent OpenAI extraction pipeline.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Backend and CLI |
| Node.js | 20+ | React/Vite UI |
| OpenAI API key | — | Reasoning, optimizer, and embeddings calls |

## 1. Create a Python Environment

The dev scripts resolve a virtual environment automatically: they prefer this app's `.venv`, and fall back to a repo-root `.venv` shared across the monorepo. Create whichever you prefer.

```bash
# App-local environment (from apps/pipeline/)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To install developer tooling (tests, linters) as well:

```bash
pip install -r requirements-dev.txt
```

## 2. Configure Credentials

The pipeline is **OpenAI-only**. Configuration lives in `config.json`, which is gitignored and copied from the committed template.

```bash
# Copy the configuration template
cp config.example.json config.json

# Copy the environment template
cp .env.example .env
```

Edit `.env` and add your key:

```bash
# OpenAI API Key (required)
OPENAI_API_KEY=sk-your-actual-openai-key-here
```

`config.json` references the key via the `${OPENAI_API_KEY}` placeholder, which `utils/config.py` substitutes from the environment at load time. The default models are:

| Role | Model |
|------|-------|
| Reasoning | `gpt-5.2` |
| Optimizer | `gpt-5.2` |
| Embeddings | `text-embedding-ada-002` |

Get an API key from the [OpenAI Platform](https://platform.openai.com/api-keys).

## 3. Add Source Documents

Place the documents you want to process in `compliance-files/` (gitignored). The
CLI discovers these formats: PDF (`.pdf`), text (`.txt`), Markdown (`.md`), and
Word (`.docx`). Agent 1 also bundles CSV and Excel chunkers, but those extensions
are not auto-discovered.

```bash
cp /path/to/your-document.pdf compliance-files/
```

## 4. Verify the Configuration

```bash
python3 -c "
import sys
sys.path.insert(0, 'utils')
from config import get_config
get_config()
print('Configuration loaded successfully')
"
```

## 5. Run

### Extraction pipeline (Agents 1–6)

```bash
# Process all documents in compliance-files/
python cli/extract.py --provider openai

# Process a single file
python cli/extract.py --file compliance-files/my-document.pdf
```

### Comparison pipeline (Agents 7–10)

```bash
# List available graphs (these are extracted document/batch folder names)
python cli/compare.py --list

# Compare two extracted graphs by name
python cli/compare.py --g1 <graphA> --g2 <graphB>
```

### Web UI (backend + frontend)

```bash
./start.sh
```

| Service | URL | Notes |
|---------|-----|-------|
| Backend (FastAPI) | `http://localhost:8000` | API + WebSocket |
| Frontend (Vite) | `http://localhost:5173` | Open this in your browser |

Override ports with `P2K_BACKEND_PORT` / `P2K_FRONTEND_PORT`. Stop both servers with `./stop.sh`.

## Security Notes

> **Never commit** `.env` or `config.json` — they hold (or reference) your API key.

Safe to commit: `.env.example`, `config.example.json`, and the `.gitignore` (already configured to exclude the sensitive files and `compliance-files/`).

## Troubleshooting

### Missing API key

1. Confirm `.env` exists and `OPENAI_API_KEY` is set with no surrounding spaces or quotes.
2. Confirm `config.json` references the key as `${OPENAI_API_KEY}`.

### Configuration not loading

1. Confirm you copied `config.example.json` to `config.json`.
2. Validate the JSON syntax.
3. Confirm the venv is active and dependencies are installed.

## Related Documentation

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | App overview and quick start |
| [DOCKER.md](DOCKER.md) | Container deployment guide |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture |
