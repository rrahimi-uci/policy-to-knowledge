// Auto-generated from graphs.yaml — DO NOT EDIT
// JanusGraph Multi-Graph initialization script
//
// NOTE: do NOT declare `def globals = [:]` — Gremlin Server's
// ScriptFileGremlinPlugin injects `globals` as a script binding;
// using `def` shadows it and the traversal sources never become
// visible to the server (alias lookups then fail with
// 'not in the Graph or TraversalSource global bindings').

println("[init-graphs] Binding sample_guidelines_g to sample_guidelines.traversal() (Sample Guidelines)")
globals << [sample_guidelines_g : sample_guidelines.traversal()]

println("[init-graphs] Binding example_policies_g to example_policies.traversal() (Example Policies)")
globals << [example_policies_g : example_policies.traversal()]
