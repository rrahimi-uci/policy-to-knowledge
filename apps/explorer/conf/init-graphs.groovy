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

println("[init-graphs] Binding comercial_lending_g to comercial_lending.traversal() (Comercial Lending)")
globals << [comercial_lending_g : comercial_lending.traversal()]

println("[init-graphs] Binding fannie_mae_g to fannie_mae.traversal() (Fannie Mae)")
globals << [fannie_mae_g : fannie_mae.traversal()]

println("[init-graphs] Binding freddie_mac_g to freddie_mac.traversal() (Freddie Mac)")
globals << [freddie_mac_g : freddie_mac.traversal()]

println("[init-graphs] Binding healthcare_g to healthcare.traversal() (Healthcare)")
globals << [healthcare_g : healthcare.traversal()]
