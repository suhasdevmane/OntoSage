"""Synthetic time-series generation for toggleable data sources (Phase 2).

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from orchestrator.services.synthetic.generator import (
    GENERATOR_KINDS,
    SyntheticDataService,
    generate_point_series,
)

__all__ = ["SyntheticDataService", "generate_point_series", "GENERATOR_KINDS"]
