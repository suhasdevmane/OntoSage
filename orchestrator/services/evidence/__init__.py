# -*- coding: utf-8 -*-
"""Evidence discipline (V6).

The machinery behind the Master Technical Report's central demand -- *"the building should
never sound more certain than the evidence available inside the building."*

Deliberately a package rather than a module: the gates, the policy, the spatial classifier
and the record assembler are separate concerns that will grow, and the one thing they must
share is a single assembly point. BUG-210 in this repository was two copies of one step
drifting until identical inputs produced different results depending which path ran.
"""

from orchestrator.services.evidence.access_tiers import (  # noqa: F401
    AccessTier,
    all_tiers,
    permission_for_tier,
    tier_for_role,
    tier_for_shape,
)
from orchestrator.services.evidence.accessibility import (  # noqa: F401
    AccessibilityRequirement,
    AccessibleOption,
    filter_options,
)
from orchestrator.services.evidence.completeness import (  # noqa: F401
    CompletenessReport,
    Gap,
    assess,
    duration_above,
)
from orchestrator.services.evidence.conflict import (  # noqa: F401
    ConflictReport,
    Reading,
    detect,
    detect_all,
)
from orchestrator.services.evidence.gates import (  # noqa: F401
    GateVerdict,
    advisory_failures,
    apply,
    blocking,
    calibration_gate,
    completeness_gate,
    freshness_gate,
    spatial_gate,
)
from orchestrator.services.evidence.history import (  # noqa: F401
    ConfigurationPeriod,
    WindowIntegrity,
    attribute_readings,
    check_window,
    location_as_of,
)
from orchestrator.services.evidence.narration import (  # noqa: F401
    adequacy_note,
    collect_omissions,
    describe_not_assessable,
    describe_omissions,
    label_proxy,
    status_badge,
)
from orchestrator.services.evidence.policy import (  # noqa: F401
    EvidencePolicy,
    GateMode,
    load_policy,
)
from orchestrator.services.evidence.sensor_health import (  # noqa: F401
    HealthState,
    SensorHealth,
    assess_drift,
    assess_sensor,
    summarise,
)
from orchestrator.services.evidence.causal_guard import (  # noqa: F401
    CausalClaim,
    causal_gate,
    find_claims,
    is_already_correlational,
    qualify,
    support_from_evidence,
    unlicensed_claims,
)
from orchestrator.services.evidence.aggregation import (  # noqa: F401
    describe_basis,
    exceedance_duration,
    time_weighted_mean,
)
from orchestrator.services.evidence.omissions import (  # noqa: F401
    CriterionFacts,
    collect,
    facts_from_ranking,
    omission_for,
)
from orchestrator.services.evidence.spatial_adequacy import (  # noqa: F401
    AdequacyVerdict,
    PointFacts,
    best_verdict,
    classify,
    is_permitted,
)
from orchestrator.services.evidence.time_windows import (  # noqa: F401
    HourMask,
    detect_mask,
    filter_samples,
    nightly_minimums,
)
from orchestrator.services.evidence.trend_integrity import (  # noqa: F401
    TrendIntegrity,
    TrendVerdict,
    artefact_kinds,
    assess_trend,
)

__all__ = [
    "AccessTier",
    "AccessibilityRequirement",
    "TrendIntegrity",
    "TrendVerdict",
    "artefact_kinds",
    "assess_trend",
    "AccessibleOption",
    "AdequacyVerdict",
    "HourMask",
    "detect_mask",
    "filter_options",
    "filter_samples",
    "nightly_minimums",
    "GateVerdict",
    "adequacy_note",
    "advisory_failures",
    "apply",
    "blocking",
    "calibration_gate",
    "collect_omissions",
    "completeness_gate",
    "describe_not_assessable",
    "describe_omissions",
    "freshness_gate",
    "label_proxy",
    "spatial_gate",
    "status_badge",
    "ConfigurationPeriod",
    "ConflictReport",
    "HealthState",
    "Reading",
    "SensorHealth",
    "WindowIntegrity",
    "assess_drift",
    "assess_sensor",
    "attribute_readings",
    "check_window",
    "detect",
    "detect_all",
    "location_as_of",
    "summarise",
    "describe_basis",
    "exceedance_duration",
    "time_weighted_mean",
    "CriterionFacts",
    "collect",
    "facts_from_ranking",
    "omission_for",
    "CausalClaim",
    "causal_gate",
    "find_claims",
    "is_already_correlational",
    "qualify",
    "support_from_evidence",
    "unlicensed_claims",
    "CompletenessReport",
    "Gap",
    "PointFacts",
    "assess",
    "best_verdict",
    "classify",
    "duration_above",
    "is_permitted",
    "EvidencePolicy",
    "GateMode",
    "all_tiers",
    "load_policy",
    "permission_for_tier",
    "tier_for_role",
    "tier_for_shape",
]
