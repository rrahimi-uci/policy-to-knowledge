# Knowledge Graphs (`kgs/`)

This directory holds the knowledge-graph JSON files the Explorer loads into
JanusGraph, one per graph defined in [`conf/graphs.yaml`](../conf/graphs.yaml)
(the `kg_file` field).

**No data ships with this repository.** Supply your own graphs here, e.g.
`kgs/sample-guidelines-kg.json`, then run the loader (`python -m src.main setup`).
Generate graphs from documents with the [Pipeline](../../pipeline/) app.
