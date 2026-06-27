"""
Shared configuration loaded from .env / environment variables.

Every tuneable parameter in the project is surfaced here so that
operators can override behaviour via a .env file or shell exports
without touching source code.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ── Infrastructure hosts / ports ──────────────────────────────────

JANUSGRAPH_HOST: str = os.getenv("JANUSGRAPH_HOST", "localhost")
JANUSGRAPH_PORT: int = int(os.getenv("JANUSGRAPH_PORT", "8182"))
CASSANDRA_HOST: str = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_PORT: int = int(os.getenv("CASSANDRA_PORT", "9042"))
OPENSEARCH_HOST: str = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT: int = int(os.getenv("OPENSEARCH_PORT", "9200"))

# Hostnames as seen *from inside the jg-server container* (used when this
# process injects values into Groovy scripts that run server-side).  When
# CASSANDRA_HOST / OPENSEARCH_HOST point at "localhost" (i.e. this process
# runs on the host), those names are meaningless inside the container — so
# fall back to the docker-network service names.
CASSANDRA_HOST_INTERNAL: str = os.getenv(
    "CASSANDRA_HOST_INTERNAL",
    CASSANDRA_HOST if CASSANDRA_HOST not in ("localhost", "127.0.0.1") else "cassandra",
)
OPENSEARCH_HOST_INTERNAL: str = os.getenv(
    "OPENSEARCH_HOST_INTERNAL",
    OPENSEARCH_HOST if OPENSEARCH_HOST not in ("localhost", "127.0.0.1") else "opensearch",
)

# ── Redis ─────────────────────────────────────────────────────────

REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
CACHE_TTL: int = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default
REDIS_CONNECT_TIMEOUT: int = int(os.getenv("REDIS_CONNECT_TIMEOUT", "5"))
REDIS_SOCKET_TIMEOUT: int = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
REDIS_HEALTH_CHECK_INTERVAL: int = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))

# ── Embedding ─────────────────────────────────────────────────────

EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))

# ── Multi-graph (driven by graphs.yaml) ──────────────────────────

from conf.graph_manifest import (          # noqa: E402
    get_available_graph_names,
    get_default_traversal_source,
)

DEFAULT_GRAPH: str = os.getenv("DEFAULT_GRAPH", get_default_traversal_source())
AVAILABLE_GRAPHS: list[str] = get_available_graph_names()

# ── Connection pool ───────────────────────────────────────────────

POOL_MIN_SIZE: int = int(os.getenv("POOL_MIN_SIZE", "2"))
POOL_MAX_SIZE: int = int(os.getenv("POOL_MAX_SIZE", "10"))

# ── OpenAI / LLM ─────────────────────────────────────────────────

# Default to gpt-4o-mini: ~3-5x faster TTFT and 1/15 the cost of gpt-4o,
# with quality that's more than sufficient for the grounded tool-calling
# workload (the LLM mainly orchestrates tools and synthesizes JSON results
# rather than reasoning from scratch). Override with OPENAI_CHAT_MODEL=gpt-4o
# if a deployment needs the larger model.
OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_REASONING_EFFORT: str = os.getenv("OPENAI_REASONING_EFFORT", "low")

# Models that accept the reasoning_effort parameter
_REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o4-mini"}

def supports_reasoning_effort(model: str) -> bool:
    """Return True if the model supports the reasoning_effort parameter."""
    m = model.lower()
    return m.startswith("gpt-5") or any(m.startswith(r) for r in _REASONING_MODELS)
MAX_TOOL_ROUNDS: int = int(os.getenv("MAX_TOOL_ROUNDS", "3"))

# ── Flask server ──────────────────────────────────────────────────

SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "5000"))
URL_PREFIX: str = os.getenv("URL_PREFIX", "/app")
FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")

# ── Search defaults ───────────────────────────────────────────────

SEMANTIC_SEARCH_DEFAULT_TOP_K: int = int(os.getenv("SEMANTIC_SEARCH_DEFAULT_TOP_K", "5"))
SEMANTIC_SEARCH_CACHE_TTL: int = int(os.getenv("SEMANTIC_SEARCH_CACHE_TTL", "1800"))
TEXT_SEARCH_MAX_RESULTS: int = int(os.getenv("TEXT_SEARCH_MAX_RESULTS", "10"))
FUZZY_MATCH_MAX_CANDIDATES: int = int(os.getenv("FUZZY_MATCH_MAX_CANDIDATES", "5"))
SIBLING_RULES_MAX_RESULTS: int = int(os.getenv("SIBLING_RULES_MAX_RESULTS", "10"))
STATS_HUB_RULES_LIMIT: int = int(os.getenv("STATS_HUB_RULES_LIMIT", "5"))

# ── OpenSearch k-NN index ─────────────────────────────────────────

KNN_INDEX_NAME: str = os.getenv("KNN_INDEX_NAME", "vertex_embeddings")
KNN_EF_SEARCH: int = int(os.getenv("KNN_EF_SEARCH", "100"))
KNN_NUMBER_OF_SHARDS: int = int(os.getenv("KNN_NUMBER_OF_SHARDS", "1"))
KNN_NUMBER_OF_REPLICAS: int = int(os.getenv("KNN_NUMBER_OF_REPLICAS", "0"))
KNN_EF_CONSTRUCTION: int = int(os.getenv("KNN_EF_CONSTRUCTION", "128"))
KNN_HNSW_M: int = int(os.getenv("KNN_HNSW_M", "24"))
KNN_SPACE_TYPE: str = os.getenv("KNN_SPACE_TYPE", "cosinesimil")
KNN_ENGINE: str = os.getenv("KNN_ENGINE", "lucene")

# ── OpenSearch client ─────────────────────────────────────────────

OPENSEARCH_USE_SSL: bool = os.getenv("OPENSEARCH_USE_SSL", "false").lower() in ("1", "true", "yes")
OPENSEARCH_VERIFY_CERTS: bool = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() in ("1", "true", "yes")
OPENSEARCH_HTTP_COMPRESS: bool = os.getenv("OPENSEARCH_HTTP_COMPRESS", "true").lower() in ("1", "true", "yes")
OPENSEARCH_TIMEOUT: int = int(os.getenv("OPENSEARCH_TIMEOUT", "30"))
OPENSEARCH_MAX_RETRIES: int = int(os.getenv("OPENSEARCH_MAX_RETRIES", "3"))
OPENSEARCH_RETRY_ON_TIMEOUT: bool = os.getenv("OPENSEARCH_RETRY_ON_TIMEOUT", "true").lower() in ("1", "true", "yes")

# ── Gremlin pool ──────────────────────────────────────────────────

GREMLIN_MAX_INFLIGHT: int = int(os.getenv("GREMLIN_MAX_INFLIGHT", "64"))

# ── Schema creation ───────────────────────────────────────────────

SCHEMA_RETRIES: int = int(os.getenv("SCHEMA_RETRIES", "5"))
SCHEMA_RETRY_DELAY: float = float(os.getenv("SCHEMA_RETRY_DELAY", "10.0"))

# ── Data loader ───────────────────────────────────────────────────

DATA_LOAD_BATCH_LOG_INTERVAL: int = int(os.getenv("DATA_LOAD_BATCH_LOG_INTERVAL", "50"))

# ── Gremlin query defaults ────────────────────────────────────────

QUERY_DEFAULT_LIMIT: int = int(os.getenv("QUERY_DEFAULT_LIMIT", "10"))
HIGH_CONFIDENCE_THRESHOLD: float = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "90.0"))
QUERY_HIGH_CONFIDENCE_MAX: int = int(os.getenv("QUERY_HIGH_CONFIDENCE_MAX", "15"))

# ── Docker / Cassandra (informational — consumed by docker-compose) ─
# These are not read by Python but kept here as documentation.
# Override in .env to pass through to docker-compose.

CASSANDRA_CLUSTER_NAME: str = os.getenv("CASSANDRA_CLUSTER_NAME", "jg-cluster")
CASSANDRA_MAX_HEAP: str = os.getenv("CASSANDRA_MAX_HEAP", "512M")
CASSANDRA_HEAP_NEWSIZE: str = os.getenv("CASSANDRA_HEAP_NEWSIZE", "128M")
OPENSEARCH_JAVA_OPTS: str = os.getenv("OPENSEARCH_JAVA_OPTS", "-Xms256m -Xmx256m")
REDIS_MAX_MEMORY: str = os.getenv("REDIS_MAX_MEMORY", "256mb")
REDIS_EVICTION_POLICY: str = os.getenv("REDIS_EVICTION_POLICY", "allkeys-lru")
