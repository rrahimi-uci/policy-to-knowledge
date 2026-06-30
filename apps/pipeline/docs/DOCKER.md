# Docker Deployment Guide

How to build and run the **pipeline** app with Docker: a batch extraction CLI and a containerized FastAPI + React UI.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker | 20.10+ | [Install Docker](https://docs.docker.com/get-docker/) |
| Docker Compose | 2.0+ | Bundled with Docker Desktop |
| OpenAI API key | — | Set in `.env` |
| Source documents | — | Placed in `compliance-files/` |

## Images and Services

The app ships two images, built from two Dockerfiles and wired up in `docker-compose.yml`.

| Service | Image | Dockerfile | Base | Purpose | Port |
|---------|-------|------------|------|---------|------|
| `p2k` | `p2k:latest` | `Dockerfile.cli` | `python:3.11-slim` | Batch extraction runner; entrypoint `cli/extract.py` | — |
| `p2k-ui` | `p2k-ui:latest` | `Dockerfile.api` | `python:3.12-slim` | FastAPI backend + built React UI | `8000` |

`Dockerfile.api` is a multi-stage build: it compiles the React/Vite frontend, installs the FastAPI backend, and serves the bundled UI from FastAPI on a single port.

> The repo-root `docker-compose.yml` builds the pipeline backend (`kg-backend`) from this app's `Dockerfile.api` as part of the full monorepo stack. This guide covers the app-local `docker-compose.yml`.

## Quick Start

### Run the extraction pipeline

```bash
docker compose run --rm p2k --provider openai
```

### Run the web UI

```bash
docker compose up -d p2k-ui

# Open the app
open http://localhost:8000
```

The `p2k-ui` service builds the React frontend into the API image and serves it from FastAPI, so document upload and extraction run from a single container on port `8000`.

## Full Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Set your key in `.env`:

```bash
OPENAI_API_KEY=sk-your-actual-key-here
```

### 2. Configuration

```bash
cp config.example.json config.json
```

`config.json` is gitignored. The images seed a default `config.json` from `config.example.json` at build time, and runtime environment variables (such as `OPENAI_API_KEY`) are substituted by the app when the config is loaded.

### 3. Add source documents

```bash
cp /path/to/your-document.pdf compliance-files/
```

### 4. Build and run

```bash
# Build both images
docker compose build

# Start the web UI/API
docker compose up -d p2k-ui

# Run the batch pipeline on demand
docker compose run --rm p2k --provider openai
```

### 5. View results

```bash
ls -lh pipeline-output/

# Open the generated knowledge-graph visualization
open pipeline-output/*/agent-6-visualization-and-report/*_knowledge_graph.html
```

## Architecture

### CLI image layout (`Dockerfile.cli`)

```text
p2k:latest  (python:3.11-slim)
├── agents/          # 10-agent pipeline
├── prompts/         # production prompts
├── utils/           # config, LLM client, helpers
├── cli/
│   ├── extract.py   # entrypoint — Agents 1–6
│   └── compare.py   # set operations — Agents 7–10
├── config.json      # seeded from config.example.json
└── non-root user (appuser)
```

### Volume mounts (`p2k` service)

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `./compliance-files/` | `/app/compliance-files` | ro | Input documents |
| `./pipeline-output/` | `/app/pipeline-output` | rw | Pipeline results |
| `./config.json` | `/app/config.json` | rw | Configuration |

### Volume mounts (`p2k-ui` service)

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `./compliance-files/` | `/app/compliance-files` | rw | Uploaded documents |
| `./pipeline-output/` | `/app/pipeline-output` | rw | Pipeline results |
| `./pipeline-logs/` | `/app/pipeline-logs` | rw | Backend run logs |
| `./config.json` | `/app/config.json` | rw | Configuration |

## Usage Examples

### Run the full extraction pipeline

```bash
docker compose run --rm p2k --provider openai
```

### Run a single agent step

```bash
# Agent 1 — Document Organizer
docker compose run --rm p2k --step 1

# Agent 2 — Entity Extractor
docker compose run --rm p2k --step 2

# Agent 6 — Visualization
docker compose run --rm p2k --step 6
```

### Compare two graphs (Agents 7–10)

```bash
# List available graphs (extracted document/batch folder names)
docker compose run --rm --entrypoint python p2k cli/compare.py --list

# Compare two extracted graphs by name
docker compose run --rm --entrypoint python p2k cli/compare.py --g1 <graphA> --g2 <graphB>
```

> The `p2k` entrypoint is `cli/extract.py`. To run `cli/compare.py`, override the entrypoint as shown above.

### View logs and status

```bash
# Follow UI logs
docker compose logs -f p2k-ui

# Last 100 lines
docker compose logs --tail=100 p2k-ui

# Container status
docker compose ps
```

### Clean up

```bash
# Stop and remove containers
docker compose down

# Remove volumes (WARNING: deletes named-volume data)
docker compose down -v

# Remove images
docker rmi p2k:latest p2k-ui:latest
```

## Advanced Configuration

### Resource limits

The `p2k` service defines limits in `docker-compose.yml`. Adjust for larger documents:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 8G
    reservations:
      cpus: '2'
      memory: 4G
```

### Development mode (hot reload)

Mount source code as volumes so changes take effect without rebuilding:

```yaml
# Add under the service's volumes:
volumes:
  - ./agents:/app/agents:rw
  - ./utils:/app/utils:rw
  - ./cli/extract.py:/app/cli/extract.py:rw
```

## Troubleshooting

### "Permission denied" when writing output

User ID mismatch between host and container. Run as your host user:

```bash
docker compose run --rm --user $(id -u):$(id -g) p2k
```

Or fix ownership on the host:

```bash
sudo chown -R $USER pipeline-output/
```

### "API key not found"

The environment was not loaded. Confirm `.env` exists with a valid `OPENAI_API_KEY`, then recreate the containers:

```bash
docker compose down
docker compose up -d p2k-ui
```

### Container runs out of memory

Increase the memory limit for the `p2k` service in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      memory: 16G
```

### Build fails: "No space left on device"

```bash
docker system prune -a
docker volume prune
```

### "Module not found" errors

Rebuild without cache:

```bash
docker compose build --no-cache
```

## Security Best Practices

### API key management

- **Do not** commit `.env` or `config.json` with a real key — both are gitignored.
- Use Docker secrets for production:

  ```bash
  echo "your-api-key" | docker secret create openai_key -
  ```

### Non-root user

The CLI image runs as a non-root user (`appuser`).

### Read-only inputs

For the batch runner, source documents are mounted read-only:

```yaml
volumes:
  - ./compliance-files:/app/compliance-files:ro
```

## Production Deployment

### Push to a registry

```bash
# Tag and push the API image
docker tag p2k-ui:latest registry.example.com/p2k-ui:1.0.0
docker push registry.example.com/p2k-ui:1.0.0
```

### Kubernetes batch job (example)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: p2k-pipeline
spec:
  template:
    spec:
      containers:
      - name: p2k
        image: registry.example.com/p2k:1.0.0
        args: ["--provider", "openai"]
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: llm-credentials
              key: openai-key
        volumeMounts:
        - name: compliance-docs
          mountPath: /app/compliance-files
        - name: output
          mountPath: /app/pipeline-output
      restartPolicy: OnFailure
      volumes:
      - name: compliance-docs
        persistentVolumeClaim:
          claimName: compliance-pvc
      - name: output
        persistentVolumeClaim:
          claimName: output-pvc
```

## Related Documentation

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | App overview |
| [SETUP.md](SETUP.md) | Local environment setup |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture |
