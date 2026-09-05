# -*- coding: utf-8 -*-
"""Calibration and cadence describe the instrument, not the measurement (BUG-427).

`ontosage:calibratedOn`, `calibrationDueOn`, `samplingIntervalS` and `archivalIntervalS`
live in the graph, and 2,728 sensors on bldg1 now carry them. The lanes that answer from
time-series rows cannot see any of it. Measured live on the day the metrology landed:

    "When was the CO2 sensor in Room 5.01 last calibrated?"
      -> analytics: "No calibration record found for the CO2 Level Sensor 5.01"
         The graph says calibratedOn 2025-11-17.

    "How often does a CO2 sensor report?"
      -> sensor_data: "every 30 seconds", inferred from the spacing of the ten rows it
         happened to fetch. The declared interval is 60, and the publisher agrees.

The first is the serious one. A confident false negative about data the building holds is
precisely what contract 4 forbids — worse than declining, because nothing signals it is
wrong. Both answers are the same mistake: measuring the readings to answer a question about
the instrument that produced them.

The rule sits LAST in the parse stage. This contract applies every matching rule and the
last one wins, so a rule placed earlier would be overridden by the very data-lane rules it
exists to correct.
"""

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import routing_contract as rc  # noqa: E402


def _ctx(query: str, intent: str):
    """A rule context, built the way the contract builds one."""
    return rc._Ctx(query=query, ql=query.lower(), normalized={"intent": intent}, sr=None)


@pytest.mark.parametrize(
    "query",
    [
        "When was the CO2 sensor in Room 5.01 last calibrated?",
        "How many sensors are overdue for calibration?",
        "Which sensors need recalibration this year?",
        "What is the sampling interval for the temperature sensors?",
        "What is the archival interval on this stream?",
        "How often does a CO2 sensor report?",
        "How often do the meters record?",
    ],
)
def test_metrology_questions_are_recognised(query):
    assert rc._METROLOGY_RE.search(query), f"{query!r} is not recognised as a metrology question"


@pytest.mark.parametrize(
    "query",
    [
        # Readings, not instruments.
        "What is the CO2 level in Room 5.01 right now?",
        "Show me the temperature trend for last week",
        "Which room is warmest?",
        # A register question about test regimes, which the record matcher already owns.
        "Which fire doors are overdue for inspection?",
        # Ordinary frequency questions that are not about an instrument reporting.
        "How often is the atrium cleaned?",
        "How often do people use the lift?",
    ],
)
def test_ordinary_questions_are_not_claimed(query):
    assert not rc._METROLOGY_RE.search(query), (
        f"{query!r} would be pulled out of its lane; the pattern is too broad"
    )


def test_the_rule_only_takes_from_lanes_that_read_rows():
    """A register or capability route must survive: those lanes can already answer."""
    for intent in ("metadata", "capability", "register", "maintenance", "privacy_refusal"):
        ctx = _ctx("when was it last calibrated?", intent)
        assert rc._r_instrument_metrology(ctx) is None, (
            f"the rule claimed a question already routed to {intent}"
        )


def test_the_rule_claims_the_lanes_that_cannot_answer():
    for intent in ("sensor_data", "analytics", "trend", "compare"):
        ctx = _ctx("when was it last calibrated?", intent)
        assert rc._r_instrument_metrology(ctx) == "metadata", (
            f"a calibration question left in {intent}, which reads rows and cannot see a "
            f"calibration date"
        )


def test_the_rule_survives_the_data_rules():
    """Order is the contract: every matching rule applies and the last one wins.

    This asserted `names[-1] == "instrument_metrology"` — "last" as a proxy for "after the
    rules that would take it back". A second rule needing the same property (readiness_check)
    then made the proxy false while the property still held, so the test failed on position
    rather than on behaviour.

    What matters is that no rule AFTER metrology claims a metrology question. That is checked
    directly, so a third such rule can be added without editing this.
    """
    names = [r.name for r in rc.PARSE_STAGE_RULES]
    idx = names.index("instrument_metrology")
    later = rc.PARSE_STAGE_RULES[idx + 1 :]
    query = "when was the CO2 sensor in room 4.02 last calibrated?"
    for rule in later:
        ctx = _ctx(query, "metadata")
        assert rule.fn(ctx) is None if hasattr(rule, "fn") else True, (
            f"rule {rule.name!r} runs after instrument_metrology and claims a metrology "
            f"question, which would take it back to the wrong lane"
        )
    # And it must still come after the lanes it exists to correct.
    for earlier in ("compare_two_referents", "sensor_trend_not_compliance"):
        if earlier in names:
            assert names.index(earlier) < idx, (
                f"{earlier} now runs after instrument_metrology and would override it"
            )


def test_the_post_stage_promotion_does_not_take_it_back():
    """Both halves are needed; neither is sufficient.

    `_r_data_query_promotion` runs AFTER the parse stage and promotes metadata back to
    sensor_data whenever the question names a place and a measurable — which a calibration
    question does. Measured: the parse rule fired, this promoted it straight back, and the
    answer was "there is no record of a calibration event in this dataset" about a sensor
    whose record says 2025-11-17. Same shape as CAVEAT-324, where order alone did not settle
    it either.
    """
    import inspect

    src = inspect.getsource(rc._r_data_query_promotion)
    assert "_METROLOGY_RE" in src, (
        "the promotion rule no longer guards against metrology questions; the parse-stage "
        "rule will fire and be overridden one stage later, silently"
    )


# ── the five places that each decide this question's shape ─────────────────────────────
#
# Getting one metrology question answered required a guard in FIVE independent components.
# Each fired in turn, and each one silently produced a different wrong answer:
#
#   1. dialogue_agent's document-KB probe    -> "the documents do not answer this"
#   2. routing_contract parse stage          -> left in sensor_data, read the readings
#   3. routing_contract post stage           -> promoted back out of metadata
#   4. capability_agent's metrics path       -> the building's live figures
#   5. building_metrics.is_inventory_count   -> the class census
#   (ontology_inventory.is_inventory_question was a sixth, on a neighbouring shape)
#
# That is the finding, not an aside: a new question type has to be taught to every
# component that classifies question shape, and nothing enumerates them. Each guard below
# is pinned by name so removing one fails here rather than in a capture six weeks later.

def test_the_document_probe_does_not_claim_a_metrology_question():
    import inspect

    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    assert "_METROLOGY_RE.search(user_query)" in src, (
        "the document-KB probe no longer bypasses metrology questions; it fires BEFORE "
        "classification, so nothing downstream gets a turn"
    )


def test_the_capability_metrics_path_does_not_claim_it():
    import inspect

    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent)
    assert "_is_metrology" in src, (
        "the capability metrics path no longer guards against metrology questions and will "
        "answer with the building's live figures"
    )


def test_the_inventory_count_detector_does_not_claim_it():
    from orchestrator.services.building_metrics import is_inventory_count_question

    assert is_inventory_count_question("how many sensors are there?") is True
    assert is_inventory_count_question("how many sensors are overdue for calibration?") is False


def test_the_class_census_detector_does_not_claim_it():
    from orchestrator.services.ontology_inventory import is_inventory_question

    assert is_inventory_question("what kinds of sensors does the building have?") is True
    assert is_inventory_question("how many sensors are overdue for calibration?") is False


def test_the_sparql_lane_has_a_deterministic_metrology_path():
    """The properties are few and named; a generated query has to guess they exist."""
    from orchestrator.agents.sparql_agent import SPARQLAgent

    assert hasattr(SPARQLAgent, "_instrument_metrology")
    import inspect

    src = inspect.getsource(SPARQLAgent._instrument_metrology)
    for prop in ("calibratedOn", "calibrationDueOn", "archivalIntervalS"):
        assert prop in src, f"{prop} is no longer fetched"
    assert "COUNT(DISTINCT" in src, (
        "an unscoped metrology question must be COUNTED in the graph, not listed under a "
        "LIMIT and counted by the model from a fraction of the rows"
    )
