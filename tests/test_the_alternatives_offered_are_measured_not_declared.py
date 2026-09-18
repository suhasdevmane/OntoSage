# -*- coding: utf-8 -*-
""""What IS measured there" must list points that exist, not modalities that are declared.

WHAT WENT WRONG
---------------
Measured live on the demo script, 2026-09-17, through the streaming demo endpoint::

    Q: What is the radiation level in the atrium?
    A: **No — radiation is not measured in this building.** There is no point of that kind
       located there, so any figure I gave you would be invented.
       What IS measured there: air_quality, carbon_monoxide, co2, damper_position, ...

``brick:Damper_Position_Sensor`` and ``brick:Damper_Position_Command`` each have ZERO
instances in the graph. So the sentence whose entire purpose is to avoid inventing a figure
invented a capability instead — and it did so in the answer a demo would show as the
system's honesty story.

The building-wide branch built its list from ``load_modalities()``, the declared config in
``config/saturation_modalities.yaml``, with nothing checking any point existed. The
PER-SPACE branch twelve lines below had always done it correctly, through
``present_modalities``, which keeps only entries whose coverage status is ``present``.

WHAT THESE TESTS PIN
--------------------
That the honest filter is the one used, and that its empty case degrades to SILENCE rather
than to the declared list. "We measure nothing else here" said by omission is honest;
listing the config is not.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.observability import (  # noqa: E402
    UNINSTRUMENTED,
    Reach,
    present_modalities,
)

# A coverage entry as coverage_audit builds it: one modality per key, each with a status.
SPACE_A = {
    "co2": {"status": "present", "sensor": "bldg:CO2_5_01"},
    "damper_position": {"status": "uninstrumented"},
    "temperature": {"status": "present", "sensor": "bldg:T_5_01"},
}
SPACE_B = {
    "co2": {"status": "present", "sensor": "bldg:CO2_3_01"},
    "waste_fill": {"status": "uninstrumented"},
    "noise": {"status": "stale"},
}


def _union(spaces):
    """The building-wide set, expressed the way the orchestrator now expresses it."""
    return sorted({n for s in spaces for n in present_modalities(s)})


# ── the filter itself ────────────────────────────────────────────────────────


def test_a_declared_but_uninstrumented_modality_is_not_offered():
    assert "damper position" not in _union([SPACE_A, SPACE_B])
    assert "waste fill" not in _union([SPACE_A, SPACE_B])


def test_a_measured_modality_is_offered():
    assert "co2" in _union([SPACE_A, SPACE_B])
    assert "temperature" in _union([SPACE_A, SPACE_B])


def test_a_stale_modality_is_not_claimed_as_measured():
    """`stale` is a different kind of nothing from `present`, and not an offer."""
    assert "noise" not in _union([SPACE_B])


def test_the_union_spans_spaces_without_duplicating():
    out = _union([SPACE_A, SPACE_B])
    assert out == sorted(set(out))
    assert out.count("co2") == 1


# ── the empty case must be silence, not the config ───────────────────────────


def test_no_alternatives_means_the_sentence_is_omitted_entirely():
    text = Reach(
        modality="radiation",
        space_label="this building",
        status=UNINSTRUMENTED,
        lay_term="radiation",
        alternatives=[],
    ).describe()
    assert "What IS measured" not in text
    assert "not measured" in text
    assert "invented" in text


def test_the_refusal_itself_survives_having_no_alternatives():
    """Losing the offer must not lose the answer."""
    reach = Reach(
        modality="radiation",
        space_label="this building",
        status=UNINSTRUMENTED,
        lay_term="radiation",
        alternatives=[],
    )
    # The refusal survives for every reader; the unlock step is an administrator's.
    assert "not measured" in reach.describe()
    assert "Unlock:" in reach.describe(for_admin=True)


def test_alternatives_are_listed_when_there_are_some():
    text = Reach(
        modality="radiation",
        space_label="this building",
        status=UNINSTRUMENTED,
        lay_term="radiation",
        alternatives=["co2", "temperature"],
    ).describe()
    assert "What IS measured there: co2, temperature" in text


# ── the branch must not go back to the declared list ─────────────────────────


def test_the_building_wide_branch_derives_alternatives_from_coverage():
    """Source-level, because this branch needs a live schema to run.

    If someone restores `load_modalities` as the source of `alternatives` here, the
    behavioural tests above keep passing while the live answer resumes inventing
    capabilities — which is exactly how this survived.
    """
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch)
    marker = 'space_label="this building"'
    assert marker in src, "the building-wide observability branch moved; re-point this test"

    start = src.index(marker)
    branch = src[start : start + 4000]
    # The EXPRESSION, not the comment above it: read from `alternatives=` forwards, so a
    # comment mentioning either function cannot satisfy or defeat this check.
    alt = branch.index("alternatives=")
    expression = branch[alt : alt + 400]
    assert "present_modalities(" in expression, (
        "the building-wide branch must build `alternatives` from measured coverage, "
        f"not from the declared modality config; got: {expression[:200]!r}"
    )
    assert "load_modalities(" not in expression, (
        "`alternatives` is back on the declared config; that is the defect BUG-663 fixed"
    )
