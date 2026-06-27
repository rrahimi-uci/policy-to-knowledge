# Docker Deployment Guide

This guide explains how to build and run the Policy to Knowledge using Docker.

---

## ⚡ Quick Start (View Existing Reports)

If you just want to view existing reports without rerunning the pipeline:

```bash
# Open visualization directly
open pipeline-output/*/agent-6-visualization-and-report/*_knowledge_graph.html
```

---

## 📋 Prerequisites

- **Docker**: Version 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: Version 2.0+ (included with Docker Desktop)
- **API Keys**: an OpenAI API key
- **Input Files**: Compliance documents in `compliance-files/` directory

## 🚀 Run the Pipeline (Generate New Reports)

To run the complete pipeline and generate new reports:

```bash
docker compose run --rm p2k --provider openai
```

## 🌐 Run the Web UI

To start the containerized FastAPI + React UI stack:

```bash
docker compose up -d p2k-ui

# Open the app
open http://localhost:8000
```

The `p2k-ui` service builds the React frontend into the API image and serves it from FastAPI, so the document upload flow and extraction handoff run from a single container on port `8000`.

---

## 🛠️ Full Setup

### 1. Set Up Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your API keys
nano .env  # or use your preferred editor
```

**Required in .env**:
```bash
OPENAI_API_KEY=sk-proj-your-actual-key-here
```

### 2. Prepare Configuration

```bash
# Copy the example configuration
cp config.example.json config.json

# (Optional) Customize config.json for your needs
```

### 3. Add Compliance Documents

```bash
# Place your PDF files in compliance-files/
cp /path/to/FMNA.pdf compliance-files/
```

### 4. Build and Run

```bash
# Build the Docker images
docker compose build

# Start the web UI/API
docker compose up -d p2k-ui

# Run the batch pipeline on demand
docker compose run --rm p2k --provider openai
```

### 5. View Results

```bash
# Check output
ls -lh pipeline-output/

# View HTML visualization
open pipeline-output/*/agent-6-visualization-and-report/*_knowledge_graph.html
```

---

## 🏗️ Docker Architecture

### Image Structure

```
p2k:latest
├── Python 3.11 (slim base)
├── Application code
│   ├── agents/ (7 agents)
│   ├── prompts/ (production prompts)
│   ├── utils/ (utilities)
│   └── knowledge_graph_generation.py (orchestrator)
├── Dependencies (from requirements.txt)
└── Non-root user (appuser)
```

**Image Size**: ~500MB (with dependencies)

### Volume Mounts

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `./compliance-files/` | `/app/compliance-files` | ro | Input documents |
| `./pipeline-output/` | `/app/pipeline-output` | rw | Pipeline results |
| `./config.json` | `/app/config.json` | ro/rw | Configuration |
| `./pipeline-logs/` | `/app/pipeline-logs` | rw | Backend run logs |

## 🧩 Services

| Service | Purpose | Port |
|---------|---------|------|
| `p2k` | Batch extraction runner (`knowledge_graph_generation.py`) | none |
| `p2k-ui` | FastAPI backend + built React frontend | `8000` |

---

## 📖 Usage Examples

### Run Full Pipeline (Default)

```bash
docker compose run --rm p2k
```

### Run Full Pipeline with Report Viewing

```bash
# Run pipeline
docker compose run --rm p2k

# Open results directly
open pipeline-output/*/agent-6-visualization-and-report/*_knowledge_graph.html
```

**Output provides:**
- 📊 OpenAI GPT pipeline results
- 📁 All outputs in `pipeline-output/` directory

### Run Specific Agent (Single Step)

```bash
# Run only Agent 1 (Document Organizer)
docker compose run --rm p2k --step 1

# Run only Agent 2 (Entity Extractor)
docker compose run --rm p2k --step 2

# Run only Agent 6 (Visualization)
docker compose run --rm p2k --step 6
```

### Interactive Shell

```bash
# Access container shell for debugging
```

### Clean Up

### View Logs

```bash
# Follow logs in real-time
docker compose logs -f p2k-ui

# View last 100 lines
docker compose logs --tail=100 p2k-ui

# Check container status
docker compose ps
```

### Clean Up

```bash
# Stop and remove containers
docker compose down

# Remove volumes (WARNING: deletes output!)
docker compose down -v

# Remove images
docker rmi p2k:latest
```

---

## 🔧 Advanced Configuration

### Resource Limits

Edit `docker-compose.yml` to adjust resources:

```yaml
deploy:
  resources:
    limits:
      cpus: '8'      # Increase for faster processing
      memory: 16G    # Increase for large documents
    reservations:
      cpus: '4'
      memory: 8G
```

### Custom Dockerfile Build Args

```bash
# Build with custom Python version
docker build --build-arg PYTHON_VERSION=3.12 -t p2k-builder:custom .
```

### Development Mode (Hot Reload)

Mount source code as volume for development:

```yaml
# Add to docker-compose.yml under volumes:
volumes:
  - ./agents:/app/agents:rw
  - ./utils:/app/utils:rw
  - ./knowledge_graph_generation.py:/app/knowledge_graph_generation.py:rw
```

---

## 🐛 Troubleshooting

### Issue: "Permission denied" when writing output

**Cause**: User ID mismatch between host and container

**Solution**: Run with host user ID
```bash
docker-compose run --rm --user $(id -u):$(id -g) p2k
```

Or fix permissions on host:
```bash
sudo chown -R $USER:$USER pipeline-output/
```

### Issue: "API key not found"

**Cause**: Environment variables not loaded

**Solution**: 
1. Check `.env` file exists and has correct keys
2. Restart Docker Compose to reload environment
```bash
docker-compose down
docker-compose up
```

### Issue: Container runs out of memory

**Cause**: Large document processing exceeds memory limit

**Solution**: Increase memory in `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      memory: 16G  # Increase from 8G
```

### Issue: Build fails with "No space left on device"

**Cause**: Docker ran out of disk space

**Solution**: Clean up Docker resources
```bash
docker system prune -a
docker volume prune
```

### Issue: Slow performance in Docker

**Causes & Solutions**:

1. **Volume performance (macOS/Windows)**: Use named volumes instead of bind mounts
```yaml
volumes:
  - kg-output:/app/pipeline-output  # Named volume (faster)
```

2. **CPU limits too low**: Increase CPU allocation
```yaml
deploy:
  resources:
    limits:
      cpus: '8'  # Use more cores
```

3. **I/O bottleneck**: Use SSD for Docker storage, avoid network drives

### Issue: "Module not found" errors

**Cause**: Dependencies not installed or Python path issue

**Solution**: Rebuild image
```bash
docker-compose build --no-cache
```

---

## 🔒 Security Best Practices

### 1. API Key Management

**❌ Don't**:
- Commit `.env` or `config.json` with API keys to Git
- Hard-code API keys in Dockerfile

**✅ Do**:
- Use `.env` file (gitignored)
- Use Docker secrets for production
```bash
echo "your-api-key" | docker secret create openai_key -
```

### 2. Non-Root User

The Dockerfile already creates a non-root user (`appuser`) for security.

### 3. Read-Only Mounts

Input files are mounted read-only:
```yaml
volumes:
  - ./compliance-files:/app/compliance-files:ro  # :ro = read-only
```

### 4. Network Isolation

For production, use custom networks:
```yaml
networks:
  kg-network:
    driver: bridge
    internal: true  # No external access
```

---

## 📊 Performance Benchmarks

### FMNA.pdf (547 pages) Processing Time

| Environment | Agents 1-2 | Agent 3 | Agents 4-6 | **Total** |
|-------------|-----------|---------|------------|-----------|
| Native (M1 Mac) | 8 min | 15 min | 5 min | **28 min** |
| Docker (M1 Mac, 4 CPU) | 9 min | 16 min | 6 min | **31 min** |
| Docker (Linux, 8 CPU) | 7 min | 12 min | 4 min | **23 min** |
| Docker (Windows WSL2) | 11 min | 19 min | 7 min | **37 min** |

**Docker Overhead**: ~10% slower than native (due to virtualization)

---

## 🚢 Production Deployment

### Using Docker Hub

```bash
# Tag image
docker tag p2k:latest <dockerhub-user>/p2k-builder:1.0.0

# Push to Docker Hub
docker push <dockerhub-user>/p2k-builder:1.0.0

# Pull on production server
docker pull <dockerhub-user>/p2k-builder:1.0.0
```

### Using Private Registry

```bash
# Tag for private registry
docker tag p2k:latest registry.company.com/p2k-builder:latest

# Push
docker push registry.company.com/p2k-builder:latest
```

### Kubernetes Deployment (Example)

```yaml
apiVersion: apps/v1
kind: Job
metadata:
  name: p2k-pipeline
spec:
  template:
    spec:
      containers:
      - name: kg-builder
        image: <dockerhub-user>/p2k-builder:1.0.0
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

---

## 📚 Related Documentation

- [Main README](../README.md) - Project overview
- [SETUP.md](SETUP.md) - Native setup instructions
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical architecture
- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)

---

## 🆘 Support

For Docker-specific issues:
1. Check [Troubleshooting](#troubleshooting) section above
2. Review Docker logs: `docker compose logs p2k-ui`
3. Verify `.env` file has correct API keys
4. Ensure compliance files are in `compliance-files/` directory

For pipeline issues, see [agents/README.md](../agents/README.md)

---

**Last Updated**: December 21, 2025  
**Docker Version**: 24.0+  
**Compose Version**: 2.0+  
**Status**: ✅ Production-ready
