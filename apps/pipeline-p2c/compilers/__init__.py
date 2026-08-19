"""Deterministic, non-agentic projections of admitted Policy IR.

Nothing in this package calls a model. Each compiler takes Policy IR plus a gate
report and emits an artefact, refusing anything the gate did not admit.

Import the submodules directly (``from compilers.run import compile_all``). This
package intentionally re-exports nothing: ``compilers`` depends on ``validation``,
which depends on ``policy_ir``, and eager re-exports here would turn that clean
one-way layering into an import cycle.
"""
