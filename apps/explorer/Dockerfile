# ── Stage 1: Build ────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY conf/ conf/
COPY src/ src/
COPY kgs/ kgs/
COPY kbs/ kbs/
COPY ui/ ui/
COPY scripts/ scripts/
COPY logo.svg ./

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=5000 \
    URL_PREFIX=/app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/app/')" || exit 1

CMD ["python", "-m", "src.main", "auto-serve"]
