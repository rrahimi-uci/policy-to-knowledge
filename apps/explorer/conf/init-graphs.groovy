// Auto-generated from graphs.yaml — DO NOT EDIT
// JanusGraph Multi-Graph initialization script
//
// `globals` is the binding Gremlin Server reads after this script runs to
// register global TraversalSources. Some server versions inject it; others
// (e.g. JanusGraph 1.0.0) do not, in which case the script must create it.
// We create it only when absent — and WITHOUT `def`, since `def` would
// shadow the binding and the aliases would never become visible (alias
// lookups then fail with 'not in the Graph or TraversalSource global
// bindings').
if (!binding.hasVariable('globals')) { globals = [:] }

println("[init-graphs] Binding sample_guidelines_g to sample_guidelines.traversal() (Sample Guidelines)")
globals << [sample_guidelines_g : sample_guidelines.traversal()]

println("[init-graphs] Binding example_policies_g to example_policies.traversal() (Example Policies)")
globals << [example_policies_g : example_policies.traversal()]
