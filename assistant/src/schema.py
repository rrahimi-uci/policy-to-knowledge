"""
Schema creation for the Explorer compliance knowledge graph.

Creates vertex labels, edge labels, property keys, and mixed indexes
backed by OpenSearch for full-text search over Fannie Mae business rules.

In multi-graph mode (JanusGraphManager), each graph object is available
as a Groovy variable named after its ``graph_ref`` (from gremlin-server.yaml).
We template the management script with the correct graph_ref so that
``{graph_ref}.openManagement()`` resolves correctly on the server.
"""

import sys
import time

from gremlin_python.driver import client as gremlin_client
from gremlin_python.driver.serializer import GraphSONSerializersV3d0

from conf.config import JANUSGRAPH_HOST, JANUSGRAPH_PORT, SCHEMA_RETRIES, SCHEMA_RETRY_DELAY
from conf.graph_manifest import get_graph_configs, get_graph_ref_map, get_traversal_sources
from src.log import log as _log

# ── JanusGraph management Groovy script template ──────────────────
# {graph_var} is replaced at runtime with the graph_ref name
# (e.g. "compliance", "overlays") that JanusGraphManager binds.

_SCHEMA_TEMPLATE = """
// ── Property keys ────────────────────────────────────────────────
mgmt = {graph_var}.openManagement()

// Check if schema already exists
if (mgmt.getPropertyKey('rule_id') != null) {{
    mgmt.rollback()
    'schema_already_exists'
}} else {{
    // ── Business rule vertex properties ──────────────────────────
    rule_id              = mgmt.makePropertyKey('rule_id').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    rule_name            = mgmt.makePropertyKey('rule_name').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    rule_type            = mgmt.makePropertyKey('rule_type').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    description          = mgmt.makePropertyKey('description').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    conditions           = mgmt.makePropertyKey('conditions').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    consequences         = mgmt.makePropertyKey('consequences').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    exceptions           = mgmt.makePropertyKey('exceptions').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    reference            = mgmt.makePropertyKey('reference').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    mandatory            = mgmt.makePropertyKey('mandatory').dataType(Boolean.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    confidence_score     = mgmt.makePropertyKey('confidence_score').dataType(Double.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    requires_review      = mgmt.makePropertyKey('requires_review').dataType(Boolean.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    review_reason        = mgmt.makePropertyKey('review_reason').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    entity_or_relationship = mgmt.makePropertyKey('entity_or_relationship').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    entity_type          = mgmt.makePropertyKey('entity_type').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    extraction_notes     = mgmt.makePropertyKey('extraction_notes').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    node_type            = mgmt.makePropertyKey('node_type').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    vertex_uuid          = mgmt.makePropertyKey('vertex_uuid').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()

    // ── Extended business rule properties (v2 KG format) ─────────
    source_reference     = mgmt.makePropertyKey('source_reference').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    effective_date       = mgmt.makePropertyKey('effective_date').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    expiration_date      = mgmt.makePropertyKey('expiration_date').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    superseded_by        = mgmt.makePropertyKey('superseded_by').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    jurisdiction         = mgmt.makePropertyKey('jurisdiction').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    risk_level           = mgmt.makePropertyKey('risk_level').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    related_rules        = mgmt.makePropertyKey('related_rules').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    enforcement_action   = mgmt.makePropertyKey('enforcement_action').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    applicability_scope  = mgmt.makePropertyKey('applicability_scope').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    data_points_required = mgmt.makePropertyKey('data_points_required').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    audit_frequency      = mgmt.makePropertyKey('audit_frequency').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    reference_verified   = mgmt.makePropertyKey('reference_verified').dataType(Boolean.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    reference_verification_note = mgmt.makePropertyKey('reference_verification_note').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    confidence_breakdown = mgmt.makePropertyKey('confidence_breakdown').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    deduplication_info   = mgmt.makePropertyKey('deduplication_info').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()

    // Shared properties (used for search index + general labeling)
    name                 = mgmt.makePropertyKey('name').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    content              = mgmt.makePropertyKey('content').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    category             = mgmt.makePropertyKey('category').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()

    // ── Edge properties ──────────────────────────────────────────
    dependency_type      = mgmt.makePropertyKey('dependency_type').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    rationale            = mgmt.makePropertyKey('rationale').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    impact_if_fails      = mgmt.makePropertyKey('impact_if_fails').dataType(String.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()
    strength             = mgmt.makePropertyKey('strength').dataType(Integer.class).cardinality(org.janusgraph.core.Cardinality.SINGLE).make()

    // ── Vertex labels ────────────────────────────────────────────
    business_rule   = mgmt.makeVertexLabel('business_rule').make()
    entity_category = mgmt.makeVertexLabel('entity_category').make()

    // ── Edge labels ──────────────────────────────────────────────
    mgmt.makeEdgeLabel('depends_on').make()
    mgmt.makeEdgeLabel('belongs_to_category').make()
    mgmt.makeEdgeLabel('relates_to').make()

    // ── Mixed index (OpenSearch) for full-text search ────────────
    mgmt.buildIndex('mixedContentIndex', Vertex.class) \\
        .addKey(content, Mapping.TEXT.asParameter()) \\
        .addKey(name, Mapping.TEXTSTRING.asParameter()) \\
        .addKey(rule_type, Mapping.STRING.asParameter()) \\
        .addKey(node_type, Mapping.STRING.asParameter()) \\
        .addKey(rule_id, Mapping.STRING.asParameter()) \\
        .addKey(category, Mapping.STRING.asParameter()) \\
        .addKey(entity_or_relationship, Mapping.STRING.asParameter()) \\
        .addKey(vertex_uuid, Mapping.STRING.asParameter()) \\
        .addKey(jurisdiction, Mapping.STRING.asParameter()) \\
        .addKey(risk_level, Mapping.STRING.asParameter()) \\
        .addKey(effective_date, Mapping.STRING.asParameter()) \\
        .addKey(audit_frequency, Mapping.STRING.asParameter()) \\
        .buildMixedIndex('search')

    mgmt.commit()

    // Wait for index to become available
    mgmt2 = {graph_var}.openManagement()
    idx = mgmt2.getGraphIndex('mixedContentIndex')
    mgmt2.rollback()

    // Wait for REGISTERED or ENABLED (JanusGraph may transition past REGISTERED before we poll)
    ManagementSystem.awaitGraphIndexStatus({graph_var}, 'mixedContentIndex').status(SchemaStatus.REGISTERED, SchemaStatus.ENABLED).call()

    // Enable the index only if it is not already enabled
    mgmt3 = {graph_var}.openManagement()
    idx3 = mgmt3.getGraphIndex('mixedContentIndex')
    if (idx3.getIndexStatus(idx3.getFieldKeys()[0]) != SchemaStatus.ENABLED) {{
        mgmt3.updateIndex(idx3, SchemaAction.ENABLE_INDEX).get()
        mgmt3.commit()
    }} else {{
        mgmt3.rollback()
    }}

    'schema_created'
}}
"""


def _build_schema_script(graph_ref: str) -> str:
    """Return the schema Groovy script with ``graph`` replaced by the graph_ref name."""
    return _SCHEMA_TEMPLATE.format(graph_var=graph_ref)


# ── Groovy script for opening a new graph at runtime ──────────────
_OPEN_GRAPH_TEMPLATE = """\
import org.janusgraph.core.JanusGraphFactory
import org.janusgraph.graphdb.management.JanusGraphManager

// Check if graph is already known to JanusGraphManager
def mgr = JanusGraphManager.getInstance()
def existingNames = mgr.getGraphNames()

if (existingNames.contains("{graph_ref}")) {{
    // Already open — ensure the traversal source is registered with the manager
    def existingGraph = mgr.getGraph("{graph_ref}")
    def ts = existingGraph.traversal()
    mgr.putTraversalSource("{traversal_source}", ts)
    "graph_already_open"
}} else {{
    // Build configuration for new graph
    def conf = new org.apache.commons.configuration2.PropertiesConfiguration()
    conf.setProperty("gremlin.graph",                       "org.janusgraph.core.JanusGraphFactory")
    conf.setProperty("storage.backend",                     "cql")
    conf.setProperty("storage.hostname",                    "{cassandra_host}")
    conf.setProperty("storage.cql.keyspace",                "{cassandra_keyspace}")
    conf.setProperty("index.search.backend",                "elasticsearch")
    conf.setProperty("index.search.hostname",               "{opensearch_host}")
    conf.setProperty("index.search.elasticsearch.http.auth.type", "none")
    conf.setProperty("index.search.index-name",             "{opensearch_index}")
    conf.setProperty("graph.set-vertex-id",                 "false")
    conf.setProperty("graph.replace-instance-if-exists",    "true")
    conf.setProperty("ids.block-size",                      "100000")
    conf.setProperty("query.batch",                         "true")

    // Open + register with JanusGraphManager
    def newGraph = mgr.openGraph("{graph_ref}", {{ gName ->
        JanusGraphFactory.open(conf)
    }})

    // Register the traversal source so future scripts and aliases can use it
    def ts = newGraph.traversal()
    mgr.putTraversalSource("{traversal_source}", ts)
    "graph_opened"
}}
"""


def open_graph_runtime(
    graph_ref: str,
    traversal_source: str,
    cassandra_keyspace: str,
    opensearch_index: str,
) -> str:
    """Open a new graph on JanusGraph at runtime without container restart.

    Submits a Groovy script via an existing traversal source that:
      1. Opens the graph with JanusGraphManager
            2. Registers the traversal source with JanusGraphManager

    Returns the script result string ('graph_opened' or 'graph_already_open').
    """
    from conf.config import (
        JANUSGRAPH_HOST,
        JANUSGRAPH_PORT,
        CASSANDRA_HOST_INTERNAL,
        OPENSEARCH_HOST_INTERNAL,
    )

    # Pick any existing traversal source to send the script through
    existing_sources = get_traversal_sources()
    if not existing_sources:
        raise RuntimeError("No existing graphs to connect through — cannot open graph at runtime")

    anchor_ts = existing_sources[0]

    script = _OPEN_GRAPH_TEMPLATE.format(
        graph_ref=graph_ref,
        traversal_source=traversal_source,
        cassandra_host=CASSANDRA_HOST_INTERNAL,
        cassandra_keyspace=cassandra_keyspace,
        opensearch_host=OPENSEARCH_HOST_INTERNAL,
        opensearch_index=opensearch_index,
    )

    _log("INFO", f"Opening graph '{graph_ref}' at runtime via anchor '{anchor_ts}'")
    result = _submit_script(script, traversal_source=anchor_ts)
    _log("INFO", f"Runtime graph open result: {result}")
    return result


def _submit_script(script: str, traversal_source: str = "g", retries: int = SCHEMA_RETRIES, delay: float = SCHEMA_RETRY_DELAY) -> str:
    """Submit a Groovy script to JanusGraph server via a raw Client.

    The ``traversal_source`` must be a valid server-side traversal binding
    (e.g. 'compliance_g') so the alias handshake succeeds.  The script
    itself can reference any global variable (graph refs, traversal sources).
    """
    url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"

    for attempt in range(1, retries + 1):
        cli = None
        try:
            cli = gremlin_client.Client(
                url, traversal_source,
                message_serializer=GraphSONSerializersV3d0(),
            )
            result = cli.submit(script).all().result()
            return str(result)
        except Exception as exc:
            _log(
                "WARN",
                f"Schema script attempt {attempt}/{retries} failed: {exc}",
                error=type(exc).__name__,
            )
            if attempt < retries:
                time.sleep(delay)
            else:
                raise
        finally:
            if cli:
                try:
                    cli.close()
                except Exception:
                    pass


def create_schema() -> None:
    """Create the graph schema and OpenSearch mixed index for every configured graph."""
    ref_map = get_graph_ref_map()       # traversal_source → graph_ref
    configs = get_graph_configs()        # traversal_source → {file, name}

    for ts, graph_ref in ref_map.items():
        display = configs.get(ts, {}).get("name", ts)
        _log("INFO", f"Creating schema for '{display}' (graph_ref={graph_ref})")
        script = _build_schema_script(graph_ref)
        result = _submit_script(script, traversal_source=ts)
        _log("INFO", f"Schema result for '{display}': {result}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    create_schema()
