"""
Semantic search using OpenSearch k-NN (vector search).

Embeds vertex content with sentence-transformers, stores vectors in
an OpenSearch k-NN index, and uses approximate nearest-neighbor search
for semantic similarity queries.

Updated to use connection pooling and caching for improved performance.
"""

import sys
from typing import Optional

from sentence_transformers import SentenceTransformer

from conf.config import (
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    KNN_INDEX_NAME,
    KNN_EF_SEARCH,
    KNN_NUMBER_OF_SHARDS,
    KNN_NUMBER_OF_REPLICAS,
    KNN_EF_CONSTRUCTION,
    KNN_HNSW_M,
    KNN_SPACE_TYPE,
    KNN_ENGINE,
    SEMANTIC_SEARCH_CACHE_TTL,
)
from src.graph_connection import get_traversal
from src.connection_pool import get_opensearch_pool
from src.cache import cached
from conf.graph_manifest import get_default_traversal_source, get_loaded_traversal_sources
from gremlin_python.process.graph_traversal import __
from src.log import log as _log

# ── OpenSearch k-NN index settings ────────────────────────────────

KNN_INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": KNN_EF_SEARCH,
        },
        "number_of_shards": KNN_NUMBER_OF_SHARDS,
        "number_of_replicas": KNN_NUMBER_OF_REPLICAS,
    },
    "mappings": {
        "properties": {
            "vertex_name": {"type": "keyword"},
            "vertex_label": {"type": "keyword"},
            "graph_name": {"type": "keyword"},
            "content": {"type": "text"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIM,
                "method": {
                    "name": "hnsw",
                    "space_type": KNN_SPACE_TYPE,
                    "engine": KNN_ENGINE,
                    "parameters": {
                        "ef_construction": KNN_EF_CONSTRUCTION,
                        "m": KNN_HNSW_M,
                    },
                },
            },
        }
    },
}


class SemanticSearchEngine:
    """
    Manages embedding generation, OpenSearch k-NN indexing, and similarity search.
    
    Updated to use connection pooling for OpenSearch and caching for search results.
    """

    def __init__(self) -> None:
        self.model: Optional[SentenceTransformer] = None
        self._os_pool = get_opensearch_pool()

    def _get_model(self) -> SentenceTransformer:
        if self.model is None:
            _log("INFO", f"Loading embedding model: {EMBEDDING_MODEL}")
            self.model = SentenceTransformer(EMBEDDING_MODEL)
        return self.model

    # ── Create k-NN index ─────────────────────────────────────────

    def _ensure_index(self) -> None:
        """Create the k-NN index if it doesn't exist."""
        client = self._os_pool.get_client()
        if not client.indices.exists(index=KNN_INDEX_NAME):
            client.indices.create(index=KNN_INDEX_NAME, body=KNN_INDEX_BODY)
            _log("INFO", f"Created OpenSearch k-NN index: {KNN_INDEX_NAME}")

    def delete_index(self) -> None:
        """Delete the k-NN embeddings index so it can be rebuilt."""
        client = self._os_pool.get_client()
        if client.indices.exists(index=KNN_INDEX_NAME):
            client.indices.delete(index=KNN_INDEX_NAME)
            _log("INFO", f"Deleted OpenSearch k-NN index: {KNN_INDEX_NAME}")

    def delete_embeddings_for_graph(self, graph_name: str) -> int:
        """Delete all embeddings for a specific graph. Returns count deleted."""
        client = self._os_pool.get_client()
        if not client.indices.exists(index=KNN_INDEX_NAME):
            return 0
        try:
            resp = client.delete_by_query(
                index=KNN_INDEX_NAME,
                body={"query": {"term": {"graph_name": graph_name}}},
                refresh=True,
            )
            deleted = int(resp.get("deleted", 0))
            _log("INFO", f"Deleted {deleted} embeddings for graph '{graph_name}'")
            return deleted
        except Exception as exc:
            _log("WARN", f"Failed to delete embeddings for '{graph_name}': {exc}")
            return 0

    # ── Embedding count / freshness checks ────────────────────────

    def embedding_count(self, graph_name: Optional[str] = None) -> int:
        """Return the number of indexed embeddings, optionally filtered by graph."""
        client = self._os_pool.get_client()
        if not client.indices.exists(index=KNN_INDEX_NAME):
            return 0
        body: dict = {}
        if graph_name:
            body = {"query": {"term": {"graph_name": graph_name}}}
        try:
            resp = client.count(index=KNN_INDEX_NAME, body=body)
            return int(resp.get("count", 0))
        except Exception:
            return 0

    def embeddings_current(self) -> bool:
        """Return True if embeddings exist for every loaded graph.

        Compares the number of indexed embeddings per graph against
        the vertex count in JanusGraph.  Returns False if any graph
        has zero embeddings or a count mismatch.
        """
        for ts in get_loaded_traversal_sources():
            emb_count = self.embedding_count(ts)
            if emb_count == 0:
                _log("INFO", f"Embeddings missing for graph '{ts}'")
                return False
            try:
                with get_traversal(ts) as (g, conn):
                    vertex_count = g.V().count().next()
                if emb_count != vertex_count:
                    _log("INFO", f"Embedding count mismatch for '{ts}': {emb_count} embeddings vs {vertex_count} vertices")
                    return False
            except Exception as exc:
                _log("WARN", f"Cannot verify embeddings for '{ts}': {exc}")
                return False
        return True

    def index_graph_if_needed(self, graph_name: Optional[str] = None) -> int:
        """Index embeddings for a graph only if they are missing or stale.

        Returns the number of embeddings (existing or newly created).
        """
        graph_name = graph_name or get_default_traversal_source()
        emb_count = self.embedding_count(graph_name)
        try:
            with get_traversal(graph_name) as (g, conn):
                vertex_count = g.V().count().next()
        except Exception:
            vertex_count = -1

        if emb_count > 0 and emb_count == vertex_count:
            _log("INFO", f"Embeddings for '{graph_name}' already current ({emb_count} docs) — skipping")
            return emb_count

        _log("INFO", f"Embeddings for '{graph_name}' need rebuild ({emb_count} indexed vs {vertex_count} vertices)")
        return self.index_graph_embeddings(graph_name)

    def index_all_if_needed(self) -> int:
        """Index embeddings for all loaded graphs, skipping those already current."""
        self._ensure_index()
        total = 0
        for ts in get_loaded_traversal_sources():
            try:
                count = self.index_graph_if_needed(ts)
                total += count
            except Exception as e:
                _log("WARN", f"Failed to index embeddings for graph '{ts}': {e}")
        _log("INFO", f"Embedding sync complete — {total} total across all graphs")
        return total

    # ── Index embeddings from the graph ───────────────────────────

    def index_graph_embeddings(self, graph_name: Optional[str] = None) -> int:
        """
        Read all vertices from a single JanusGraph graph, generate embeddings
        for their content, and store in OpenSearch k-NN index.

        Args:
            graph_name: Traversal source to index. Defaults to the primary graph.

        Uses connection pooling for efficient resource management.
        """
        graph_name = graph_name or get_default_traversal_source()
        with get_traversal(graph_name) as (g, conn):
            client = self._os_pool.get_client()
            model = self._get_model()

            self._ensure_index()

            # Fetch all vertices with content
            vertices = (
                g.V()
                .project("name", "label", "content")
                .by(__.values("name"))
                .by(__.label())
                .by(__.values("content"))
                .toList()
            )

            _log("INFO", f"Generating embeddings for {len(vertices)} vertices")

            # Generate embeddings in batch
            texts = [v["content"] for v in vertices]
            embeddings = model.encode(texts, show_progress_bar=True)

            # Bulk index into OpenSearch
            bulk_body = []
            for i, (v, emb) in enumerate(zip(vertices, embeddings)):
                doc_id = f"{graph_name}_{i}"
                bulk_body.append({"index": {"_index": KNN_INDEX_NAME, "_id": doc_id}})
                bulk_body.append({
                    "vertex_name": v["name"],
                    "vertex_label": v["label"],
                    "graph_name": graph_name,
                    "content": v["content"],
                    "embedding": emb.tolist(),
                })

            if bulk_body:
                client.bulk(body=bulk_body, refresh=True)

            _log("INFO", f"Indexed {len(vertices)} vertex embeddings for graph '{graph_name}' in OpenSearch k-NN")
            return len(vertices)

    def index_all_graph_embeddings(self) -> int:
        """Index embeddings from all loaded graphs in graphs.yaml."""
        self._ensure_index()
        total = 0
        for ts in get_loaded_traversal_sources():
            try:
                count = self.index_graph_embeddings(graph_name=ts)
                total += count
                _log("INFO", f"Indexed {count} embeddings for graph '{ts}'")
            except Exception as e:
                _log("WARN", f"Failed to index embeddings for graph '{ts}': {e}")
        _log("INFO", f"Total embeddings indexed across all graphs: {total}")
        return total

    # ── Index a single vertex ────────────────────────────────────────

    def index_single_vertex(self, vertex_name: str, vertex_label: str,
                            content: str, graph_name: Optional[str] = None) -> None:
        """Index a single vertex's content into the OpenSearch k-NN index.

        Used when creating new vertices via the API so they become
        immediately discoverable by semantic search.

        Args:
            vertex_name: The vertex ``name`` property.
            vertex_label: The vertex label (e.g. ``business_rule``).
            content: Full text content to embed.
            graph_name: Graph traversal source this vertex belongs to.
        """
        graph_name = graph_name or get_default_traversal_source()
        client = self._os_pool.get_client()
        model = self._get_model()
        self._ensure_index()

        embedding = model.encode([content])[0].tolist()
        doc_id = f"{graph_name}_manual_{vertex_name.replace(' ', '_')}"
        client.index(
            index=KNN_INDEX_NAME,
            id=doc_id,
            body={
                "vertex_name": vertex_name,
                "vertex_label": vertex_label,
                "graph_name": graph_name,
                "content": content,
                "embedding": embedding,
            },
            refresh=True,
        )
        _log("INFO", f"Indexed single vertex embedding: {vertex_name} ({graph_name})")

    # ── Semantic search (k-NN) ────────────────────────────────────

    @cached('semantic_search', ttl=SEMANTIC_SEARCH_CACHE_TTL)
    def search(self, query: str, top_k: int = 5, graph_name: Optional[str] = None) -> list[dict]:
        """
        Perform semantic search using OpenSearch k-NN:
        1. Encode query text with the sentence-transformer model.
        2. Submit a k-NN query to OpenSearch (optionally filtered by graph).
        3. Return top-k results with similarity scores.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            graph_name: If provided, restrict results to this graph's vertices.

        Results are cached for 30 minutes to improve performance.
        """
        client = self._os_pool.get_client()
        model = self._get_model()

        # Encode query
        query_embedding = model.encode([query])[0].tolist()

        # Build k-NN clause with optional graph filter
        knn_body: dict = {
            "vector": query_embedding,
            "k": top_k,
        }
        if graph_name:
            knn_body["filter"] = {"term": {"graph_name": graph_name}}

        knn_query = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": knn_body,
                }
            },
            "_source": ["vertex_name", "vertex_label", "content", "graph_name"],
        }

        response = client.search(index=KNN_INDEX_NAME, body=knn_query)

        results = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            results.append({
                "name": src["vertex_name"],
                "label": src["vertex_label"],
                "content": src["content"],
                "graph_name": src.get("graph_name", ""),
                "similarity": float(hit["_score"]),
            })

        return results


# ── Demo ──────────────────────────────────────────────────────────

def run_semantic_search_demo() -> None:
    """Run example semantic search queries."""
    engine = SemanticSearchEngine()

    try:
        # Index embeddings
        print("\n" + "=" * 60)
        print("  SEMANTIC SEARCH (OpenSearch k-NN)")
        print("=" * 60)

        count = engine.index_graph_embeddings()
        print(f"\n  Indexed {count} vertex embeddings\n")

        # Example queries
        queries = [
            "How do neural networks understand language?",
            "distributed data storage systems",
            "finding similar documents using vectors",
            "breaking apart monolithic applications into services",
            "connecting data points in a network structure",
        ]

        for query in queries:
            print(f"\n{'─'*60}")
            print(f"  Query: \"{query}\"")
            print(f"{'─'*60}")

            results = engine.search(query, top_k=3)
            for i, r in enumerate(results, 1):
                snippet = r["content"][:70] + "..." if len(r["content"]) > 70 else r["content"]
                print(f"  {i}. [{r['label']}] {r['name']}  (score={r['similarity']:.4f})")
                print(f"     {snippet}")

        print(f"\n{'='*60}")
        print("  Semantic search demo complete!")
        print(f"{'='*60}\n")

    finally:
        pass


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    run_semantic_search_demo()
