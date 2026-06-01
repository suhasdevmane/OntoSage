"""orchestrator.workflow — LangGraph orchestration package.

Phase 17 (2026-05-29) — the historical single-file `workflow.py` (3,220 lines)
was split into a package to enable incremental decomposition.  All existing
external imports continue to work unchanged:

    from orchestrator.workflow import WorkflowOrchestrator      # still works
    import orchestrator.workflow as wf_module                   # still works
    from orchestrator import workflow                           # still works

Module layout:
    _orchestrator.py — the WorkflowOrchestrator class and its node methods.
                       The bulk of the legacy file lives here UNCHANGED.
    _routing.py      — Phase 17B: WorkflowRoutingMixin with _route_from_* methods
                       (mixed into WorkflowOrchestrator).
    _graph.py        — Phase 17C: WorkflowGraphMixin with _build_graph and
                       _safe_node helper.

When adding a new module to this package, also re-export any public symbols
from __init__.py so external callers don't have to know about the split.
"""

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

__all__ = ["WorkflowOrchestrator"]
