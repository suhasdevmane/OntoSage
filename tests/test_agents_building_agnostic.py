# -*- coding: utf-8 -*-
"""No agent may name a building.

Core code resolves the active building at runtime (settings.BUILDING_ID, the
request BuildingContext, input/database_registry.yaml). A named building in an
agent is a defect that only shows itself after a swap, on the building nobody
tested — which is exactly when it is hardest to spot.

control_agent carried one: `or "bldg1"` as the last-resort building id. Its own
comment named the risk — consulting the wrong building's actuation config after a
swap — and the literal was still there. That agent decides which points may be
written and by which driver, so it is the worst place for a silent wrong default.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_AGENTS = Path("orchestrator/agents")
_CORE = [Path("orchestrator/services"), Path("shared")]
# A building's own vocabulary: site names, per-building ids, institution names.
_LITERAL = re.compile(r"\b(abacws|bldg[123]|cardiff|buildsys)\b", re.IGNORECASE)


def _code_lines(path: Path):
    """Yield (lineno, text) for lines that are code, not comments or docstrings."""
    in_doc = False
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        ticks = line.count('"""') + line.count("'''")
        if in_doc:
            if ticks:
                in_doc = False
            continue
        if ticks == 1:
            in_doc = True
            continue
        if line.startswith("#") or not line:
            continue
        yield i, raw.split("#", 1)[0]


@pytest.mark.parametrize("agent", sorted(_AGENTS.glob("*.py")), ids=lambda p: p.name)
def test_no_agent_names_a_building_in_code(agent):
    offenders = [(n, t.strip()) for n, t in _code_lines(agent) if _LITERAL.search(t)]
    assert not offenders, f"{agent.name} names a building in code: {offenders}"


# Core services and shared/ still carry literals — CAVEAT-094, open. Most are
# documented DEFAULTS (settings.BUILDING_ID defaults to bldg1 and warns when it is
# still the default) or legacy-alias fallbacks reached only after the building
# registry has already been consulted. They are not clean, and this test does not
# pretend otherwise: it pins the known set so the count can only go DOWN. A new
# file appearing here fails, which is the point.
_KNOWN_LITERAL_FILES = {
    "building_registry.py",  # legacy "abacws" alias resolution
    "dwg_pipeline.py",  # ABACWS_CONFIG fallback after registry miss
    "floor_plan_pipeline.py",  # ABACWS_CONFIG fallback after registry miss
    "floor_plan_service.py",  # default display name
    "reindex_service.py",  # default kwarg
    "service_catalog.py",  # an optional add-on service's own product name
    "config.py",  # documented legacy default + the warning that detects it
    "floor_plan_config.py",  # the shipped example floor-plan config
    "models.py",  # default field value
}


@pytest.mark.parametrize("pkg", _CORE, ids=lambda p: str(p))
def test_core_building_literals_do_not_spread(pkg):
    """CAVEAT-094 ratchet — no NEW core file may start naming a building."""
    offenders = {
        f.name
        for f in sorted(pkg.rglob("*.py"))
        if any(_LITERAL.search(t) for _, t in _code_lines(f))
    }
    new = offenders - _KNOWN_LITERAL_FILES
    assert not new, f"new building literals in {pkg}: {sorted(new)} (CAVEAT-094 must shrink)"
