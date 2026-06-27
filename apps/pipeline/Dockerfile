# Multi-stage build for Policy to Knowledge

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install OCR runtime dependencies in builder (needed for pip install)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

LABEL maintainer="policy-to-knowledge"
LABEL description="Policy to Knowledge - 7-Agent Compliance Pipeline"
LABEL version="1.0.0"

# Install OCR runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/compliance-files /app/pipeline-output && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser agents/ ./agents/
COPY --chown=appuser:appuser prompts/ ./prompts/
COPY --chown=appuser:appuser utils/ ./utils/
COPY --chown=appuser:appuser knowledge_graph_generation.py .
# Seed config.json from the committed example (config.json is gitignored and not
# in the build context). Runtime env vars are substituted by the app at load time.
COPY --chown=appuser:appuser config.example.json config.json
COPY --chown=appuser:appuser README.md .
COPY --chown=appuser:appuser logo.svg .

# Set Python path
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER appuser

# Health check (optional - checks if Python imports work)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.path.insert(0, 'agents'); from agent_1_document_organizer import *" || exit 1

# Default command
ENTRYPOINT ["python", "knowledge_graph_generation.py"]
CMD []
