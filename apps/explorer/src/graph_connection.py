"""
Gremlin connection helper – thin wrapper around gremlinpython.

Provides a context-manager based API for opening bytecode traversals
with automatic cleanup, plus a legacy script-based GremlinClient.
New code should prefer src.connection_pool.get_gremlin_pool() for
pooled connections.
"""

from typing import Optional, Any
from contextlib import contextmanager
from gremlin_python.driver import client
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.driver.serializer import GraphSONSerializersV3d0
from gremlin_python.process.anonymous_traversal import traversal

from conf.config import JANUSGRAPH_HOST, JANUSGRAPH_PORT, DEFAULT_GRAPH


class GremlinClient:
    """
    Gremlin client wrapper using script-based queries.
    
    DEPRECATED: Use connection_pool.get_gremlin_pool().get_client() instead.
    
    This is the recommended approach for JanusGraph with graph manager,
    as it works reliably with both single and multi-graph configurations.
    """
    
    def __init__(self, traversal_source: str = "g"):
        """
        Initialize the Gremlin client.
        
        Args:
            traversal_source: Name of the traversal source (e.g., 'g', 'contracts_g')
        """
        self.url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"
        self.traversal_source = traversal_source
        self._client = client.Client(self.url, self.traversal_source)
    
    def submit(self, gremlin_script: str, bindings: Optional[dict] = None) -> list[Any]:
        """
        Submit a Gremlin script and return results.
        
        Args:
            gremlin_script: Gremlin script string (e.g., "g.V().count()")
            bindings: Optional variable bindings for the script
        
        Returns:
            List of results from the query
        """
        if bindings:
            result_set = self._client.submit(gremlin_script, bindings)
        else:
            result_set = self._client.submit(gremlin_script)
        return result_set.all().result()
    
    def close(self):
        """Close the client connection."""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_client(graph_name: Optional[str] = None) -> GremlinClient:
    """
    Get a GremlinClient for the specified graph.
    
    DEPRECATED: Use connection_pool.get_gremlin_pool().get_client() instead.
    
    Args:
        graph_name: Name of the traversal source. Defaults to 'g'.
    
    Returns:
        GremlinClient instance. Caller should close when done.
    """
    if graph_name is None:
        graph_name = DEFAULT_GRAPH
    return GremlinClient(graph_name)


@contextmanager
def get_traversal(
    graph_name: Optional[str] = None
):
    """
    Context manager that yields (GraphTraversalSource, DriverRemoteConnection)
    with automatic cleanup.
    
    Args:
        graph_name: Name of the graph to connect to. Defaults to DEFAULT_GRAPH.
    
    Yields:
        Tuple of (GraphTraversalSource, DriverRemoteConnection)
        
    Example:
        with get_traversal('g') as (g, conn):
            count = g.V().count().next()
    """
    if graph_name is None:
        graph_name = DEFAULT_GRAPH
    
    url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"
    conn = DriverRemoteConnection(
        url, graph_name,
        message_serializer=GraphSONSerializersV3d0(),
    )
    g = traversal().withRemote(conn)
    
    try:
        # Return tuple for backward compatibility
        yield g, conn
    finally:
        try:
            conn.close()
        except Exception:
            pass  # Suppress cleanup errors


def list_available_graphs() -> list[str]:
    """
    Return list of available traversal source names from graphs.yaml.
    """
    from conf.graph_manifest import get_traversal_sources
    return get_traversal_sources()
