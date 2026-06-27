"""
Connection pool management for JanusGraph (Gremlin) and OpenSearch.

Implements singleton connection pools to avoid creating new connections
for every request, improving performance and resource utilization.
"""

import json
from typing import Optional
from contextlib import contextmanager
from threading import Lock

from gremlin_python.driver import client, serializer
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.process.anonymous_traversal import traversal
from opensearchpy import OpenSearch

from conf.config import (
    JANUSGRAPH_HOST,
    JANUSGRAPH_PORT,
    OPENSEARCH_HOST,
    OPENSEARCH_PORT,
    POOL_MAX_SIZE,
    GREMLIN_MAX_INFLIGHT,
    OPENSEARCH_HTTP_COMPRESS,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_VERIFY_CERTS,
    OPENSEARCH_TIMEOUT,
    OPENSEARCH_MAX_RETRIES,
    OPENSEARCH_RETRY_ON_TIMEOUT,
)
from src.log import log as _log


class GremlinConnectionPool:
    """
    Singleton connection pool for Gremlin/JanusGraph connections.
    
    Uses the gremlin-python Client which internally maintains a connection pool.
    Provides context manager for safe resource handling.
    """
    
    _instance: Optional["GremlinConnectionPool"] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self.url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"
            self._clients: dict[str, client.Client] = {}
            self._initialized = True
            _log("INFO", f"Initialized GremlinConnectionPool for {self.url}")
    
    def get_client(self, traversal_source: str = "g") -> client.Client:
        """
        Get or create a pooled Gremlin client for script-based queries.
        
        Args:
            traversal_source: Name of the traversal source (e.g., 'g', 'contracts_g')
        
        Returns:
            Gremlin client instance with built-in connection pooling
        """
        if traversal_source not in self._clients:
            with self._lock:
                if traversal_source not in self._clients:
                    _log("INFO", f"Creating new Gremlin client for traversal source: {traversal_source}")
                    self._clients[traversal_source] = client.Client(
                        self.url,
                        traversal_source,
                        pool_size=POOL_MAX_SIZE,
                        max_inflight=GREMLIN_MAX_INFLIGHT,
                    )
        return self._clients[traversal_source]
    
    @contextmanager
    def get_traversal(self, graph_name: str = "g"):
        """
        Context manager for bytecode traversals with automatic cleanup.
        
        Args:
            graph_name: Name of the graph traversal source
        
        Yields:
            GraphTraversalSource instance
        
        Example:
            with pool.get_traversal('g') as g:
                results = g.V().count().next()
        """
        conn = DriverRemoteConnection(
            self.url,
            graph_name,
            pool_size=POOL_MAX_SIZE,
        )
        try:
            g = traversal().withRemote(conn)
            yield g
        finally:
            try:
                conn.close()
            except Exception as e:
                _log("WARN", f"Error closing Gremlin connection: {e}")
    
    def close_all(self):
        """Close all pooled connections. Should be called on application shutdown."""
        _log("INFO", "Closing all Gremlin connections")
        for ts, cli in self._clients.items():
            try:
                cli.close()
                _log("INFO", f"Closed Gremlin client for {ts}")
            except Exception as e:
                _log("ERROR", f"Error closing Gremlin client {ts}: {e}")
        self._clients.clear()


class OpenSearchConnectionPool:
    """
    Singleton connection pool for OpenSearch.
    
    OpenSearch Python client already maintains connection pooling internally.
    This class provides a singleton wrapper for application-wide access.
    """
    
    _instance: Optional["OpenSearchConnectionPool"] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._client: Optional[OpenSearch] = None
            self._initialized = True
    
    def get_client(self) -> OpenSearch:
        """
        Get the singleton OpenSearch client.
        
        Returns:
            OpenSearch client with built-in connection pooling
        """
        if self._client is None:
            with self._lock:
                if self._client is None:
                    _log("INFO", f"Creating OpenSearch client at {OPENSEARCH_HOST}:{OPENSEARCH_PORT}")
                    self._client = OpenSearch(
                        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
                        http_compress=OPENSEARCH_HTTP_COMPRESS,
                        use_ssl=OPENSEARCH_USE_SSL,
                        verify_certs=OPENSEARCH_VERIFY_CERTS,
                        timeout=OPENSEARCH_TIMEOUT,
                        max_retries=OPENSEARCH_MAX_RETRIES,
                        retry_on_timeout=OPENSEARCH_RETRY_ON_TIMEOUT,
                        # Connection pool settings
                        pool_maxsize=POOL_MAX_SIZE,
                    )
        return self._client
    
    def close(self):
        """Close the OpenSearch connection. Should be called on application shutdown."""
        if self._client is not None:
            try:
                _log("INFO", "Closing OpenSearch connection")
                self._client.close()
                self._client = None
            except Exception as e:
                _log("ERROR", f"Error closing OpenSearch client: {e}")


# Global pool instances
_gremlin_pool: Optional[GremlinConnectionPool] = None
_opensearch_pool: Optional[OpenSearchConnectionPool] = None


def get_gremlin_pool() -> GremlinConnectionPool:
    """Get the global Gremlin connection pool instance."""
    global _gremlin_pool
    if _gremlin_pool is None:
        _gremlin_pool = GremlinConnectionPool()
    return _gremlin_pool


def get_opensearch_pool() -> OpenSearchConnectionPool:
    """Get the global OpenSearch connection pool instance."""
    global _opensearch_pool
    if _opensearch_pool is None:
        _opensearch_pool = OpenSearchConnectionPool()
    return _opensearch_pool


def shutdown_pools():
    """Shutdown all connection pools. Call on application exit."""
    _log("INFO", "Shutting down all connection pools")
    if _gremlin_pool:
        _gremlin_pool.close_all()
    if _opensearch_pool:
        _opensearch_pool.close()
