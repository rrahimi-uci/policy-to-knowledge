#!/usr/bin/env python3
"""
Generate JanusGraph configuration files from graphs.yaml manifest.

Reads graphs.yaml and produces:
  - conf/janusgraph-<key>.properties   (one per graph)
  - conf/gremlin-server.yaml           (full server config with dynamic graphs map)
  - conf/init-graphs.groovy            (Groovy traversal-source bindings)

Usage:
    python scripts/generate_graph_config.py              # uses ./graphs.yaml
    python scripts/generate_graph_config.py my.yaml      # custom manifest path
"""

import json
import os
import sys
import time
from typing import Optional

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(ROOT_DIR, "conf", "graphs.yaml")
CONF_DIR = os.path.join(ROOT_DIR, "conf")


def _log(severity: str, message: str) -> None:
    print(
        json.dumps({
            "t": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "severity": severity,
            "message": message,
            "error": None,
            "stack_trace": None,
        }),
        flush=True,
    )


def load_manifest(path: Optional[str] = None) -> dict:
    """Load and validate the graphs.yaml manifest."""
    path = path or DEFAULT_MANIFEST
    if not os.path.exists(path):
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path) as f:
        manifest = yaml.safe_load(f)
    if not manifest or "graphs" not in manifest:
        raise ValueError("Manifest must contain a 'graphs' key with at least one graph entry")
    return manifest


# ── Properties file generator ─────────────────────────────────────

_PROPERTIES_TEMPLATE = """\
# Auto-generated from graphs.yaml — DO NOT EDIT
# Graph: {display_name}
# Cassandra keyspace: {keyspace}
# OpenSearch index: {index_name}

gremlin.graph=org.janusgraph.core.JanusGraphFactory

# Storage backend – Cassandra
storage.backend={storage_backend}
storage.hostname={storage_hostname}
storage.cql.keyspace={keyspace}

# Index backend – OpenSearch (via elasticsearch compatibility)
index.search.backend={index_backend}
index.search.hostname={index_hostname}
index.search.elasticsearch.http.auth.type={index_auth_type}
index.search.index-name={index_name}

# Graph settings
graph.set-vertex-id={graph_set_vertex_id}
graph.replace-instance-if-exists=true
ids.block-size={ids_block_size}
storage.batch-loading={storage_batch_loading}
query.batch={query_batch}
"""


def generate_properties(manifest: dict) -> list[str]:
    """Generate a .properties file for each graph. Returns list of created files."""
    defaults = manifest.get("defaults", {})
    created = []
    expected_files = {f"janusgraph-{key}.properties" for key in manifest["graphs"]}
    for filename in sorted(os.listdir(CONF_DIR)):
        if not filename.startswith("janusgraph-") or not filename.endswith(".properties"):
            continue
        if filename in expected_files:
            continue
        os.remove(os.path.join(CONF_DIR, filename))
        _log("INFO", f"Removed stale {filename}")

    for key, graph in manifest["graphs"].items():
        merged = {**defaults, **graph}
        content = _PROPERTIES_TEMPLATE.format(
            display_name=graph.get("display_name", key),
            keyspace=graph["cassandra_keyspace"],
            index_name=graph["opensearch_index"],
            storage_backend=merged.get("storage_backend", "cql"),
            storage_hostname=merged.get("storage_hostname", "cassandra"),
            index_backend=merged.get("index_backend", "elasticsearch"),
            index_hostname=merged.get("index_hostname", "opensearch"),
            index_auth_type=merged.get("index_auth_type", "none"),
            graph_set_vertex_id=str(merged.get("graph_set_vertex_id", False)).lower(),
            ids_block_size=merged.get("ids_block_size", 100000),
            storage_batch_loading=str(merged.get("storage_batch_loading", False)).lower(),
            query_batch=str(merged.get("query_batch", True)).lower(),
        )
        filename = f"janusgraph-{key}.properties"
        filepath = os.path.join(CONF_DIR, filename)
        with open(filepath, "w") as f:
            f.write(content)
        created.append(filepath)
        _log("INFO", f"Generated {filename}")
    return created


# ── Gremlin server YAML generator ─────────────────────────────────

def generate_gremlin_server_yaml(manifest: dict) -> str:
    """Generate the full gremlin-server.yaml with dynamic graphs map."""
    graphs_map = {}
    for key, graph in manifest["graphs"].items():
        graph_ref = graph["graph_ref"]
        # Properties file path is relative to JanusGraph's working directory
        graphs_map[graph_ref] = f"conf-graphs/janusgraph-{key}.properties"

    server_config = {
        "host": "0.0.0.0",
        "port": 8182,
        "evaluationTimeout": 120000,
        "channelizer": "org.apache.tinkerpop.gremlin.server.channel.WebSocketChannelizer",
        "graphManager": "org.janusgraph.graphdb.management.JanusGraphManager",
        "graphs": graphs_map,
        "scriptEngines": {
            "gremlin-groovy": {
                "plugins": {
                    "org.janusgraph.graphdb.tinkerpop.plugin.JanusGraphGremlinPlugin": {},
                    "org.apache.tinkerpop.gremlin.server.jsr223.GremlinServerGremlinPlugin": {},
                    "org.apache.tinkerpop.gremlin.tinkergraph.jsr223.TinkerGraphGremlinPlugin": {},
                    "org.apache.tinkerpop.gremlin.jsr223.ImportGremlinPlugin": {
                        "classImports": ["java.lang.Math"],
                        "methodImports": ["java.lang.Math#*"],
                    },
                    "org.apache.tinkerpop.gremlin.jsr223.ScriptFileGremlinPlugin": {
                        "files": ["conf-graphs/init-graphs.groovy"],
                    },
                },
            },
        },
        "processors": [
            {
                "className": "org.apache.tinkerpop.gremlin.server.op.session.SessionOpProcessor",
                "config": {"sessionTimeout": 28800000},
            },
            {
                "className": "org.apache.tinkerpop.gremlin.server.op.traversal.TraversalOpProcessor",
                "config": {"cacheExpirationTime": 600000, "cacheMaxSize": 1000},
            },
        ],
        "metrics": {
            "consoleReporter": {"enabled": True, "interval": 180000},
            "csvReporter": {"enabled": True, "interval": 180000, "fileName": "/tmp/gremlin-server-metrics.csv"},
            "jmxReporter": {"enabled": True},
            "slf4jReporter": {"enabled": True, "interval": 180000},
        },
        "maxInitialLineLength": 4096,
        "maxHeaderSize": 8192,
        "maxChunkSize": 65536,
        "maxContentLength": 10485760,
        "maxAccumulationBufferComponents": 1024,
        "resultIterationBatchSize": 32,
        "writeBufferLowWaterMark": 1048576,
        "writeBufferHighWaterMark": 10485760,
    }

    filepath = os.path.join(CONF_DIR, "gremlin-server.yaml")
    with open(filepath, "w") as f:
        f.write("# Auto-generated from graphs.yaml — DO NOT EDIT\n")
        f.write("# JanusGraph Gremlin Server Configuration with Multi-Graph Support\n\n")
        yaml.dump(server_config, f, default_flow_style=False, sort_keys=False)

    _log("INFO", f"Generated gremlin-server.yaml ({len(manifest['graphs'])} graphs)")
    return filepath


# ── Groovy init script generator ──────────────────────────────────

def generate_init_groovy(manifest: dict) -> str:
    """Generate init-graphs.groovy that binds traversal sources."""
    lines = [
        "// Auto-generated from graphs.yaml — DO NOT EDIT",
        "// JanusGraph Multi-Graph initialization script",
        "//",
        "// NOTE: do NOT declare `def globals = [:]` — Gremlin Server's",
        "// ScriptFileGremlinPlugin injects `globals` as a script binding;",
        "// using `def` shadows it and the traversal sources never become",
        "// visible to the server (alias lookups then fail with",
        "// 'not in the Graph or TraversalSource global bindings').",
        "",
    ]

    for key, graph in manifest["graphs"].items():
        graph_ref = graph["graph_ref"]
        traversal_source = graph["traversal_source"]
        display_name = graph.get("display_name", key)
        lines.append(f'println("[init-graphs] Binding {traversal_source} to {graph_ref}.traversal() ({display_name})")')
        lines.append(f"globals << [{traversal_source} : {graph_ref}.traversal()]")
        lines.append("")

    filepath = os.path.join(CONF_DIR, "init-graphs.groovy")
    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    _log("INFO", f"Generated init-graphs.groovy ({len(manifest['graphs'])} traversal bindings)")
    return filepath


# ── Main entry point ──────────────────────────────────────────────

def generate_all(manifest_path: Optional[str] = None) -> dict:
    """
    Generate all configuration files from the manifest.

    Returns:
        dict with keys: properties_files, server_yaml, init_groovy
    """
    manifest = load_manifest(manifest_path)
    _log("INFO", f"Loaded manifest with {len(manifest['graphs'])} graph(s)")

    os.makedirs(CONF_DIR, exist_ok=True)

    properties = generate_properties(manifest)
    server_yaml = generate_gremlin_server_yaml(manifest)
    init_groovy = generate_init_groovy(manifest)

    _log("INFO", f"All config files generated successfully for {len(manifest['graphs'])} graph(s)")
    return {
        "properties_files": properties,
        "server_yaml": server_yaml,
        "init_groovy": init_groovy,
    }


if __name__ == "__main__":
    manifest_path = sys.argv[1] if len(sys.argv) > 1 else None
    generate_all(manifest_path)
