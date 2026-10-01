# -*- coding: utf-8 -*-
"""One calibration register, one lane that reads it (W3-02).

THE DISAGREEMENT, reproduced live on 2026-09-29 against bldg1. Two phrasings of the same
question, routed IDENTICALLY (``intent=metadata -> metadata node=sparql overrides=[]``):

    "How many sensors are overdue for calibration?"
        -> "There are 268 sensors that are overdue for calibration. Of the 1,929 sensors
            that have a calibration regime recorded ..."                        CORRECT

    "How many sensors are overdue for calibration, and what does that mean for the
     answers you give me?"
        -> "It does not contain any field that records whether a sensor is overdue for
            calibration, nor does it record a calibration schedule or status.
            Total sensors listed: 50"                                           FALSE

There is only ONE register. The graph holds exactly three calibration predicates —
``ontosage:calibratedOn``, ``calibrationDueOn``, ``calibrationMethod``, 1,929 subjects each
— and one file writes them (``<id>_sensor_metrology.ttl``). The disagreement was never two
registers; it was two LANES, one of which cannot see the register at all.

WHY THE SECOND PHRASING LOST THE REGISTER. ``_measurand_tokens`` is a denylist: any word
not in a hand-written stopword set becomes a scope. "mean", "answers", "you" and "give"
survived it, the lane built
``FILTER(CONTAINS(..., "mean") || ... || CONTAINS(..., "give"))``, that matched zero rows,
``_instrument_metrology`` returned None, and the question fell through to a generated query
which cannot see these properties and denied they exist. Four ordinary English words turned
a 1,929-record register off — and the denial is the failure contract 4 forbids, not a
missing answer but a confident false one.

THE FIX IS NOT A LONGER WORD LIST. A denylist over English cannot be finished, and the next
phrasing would find the next gap. The GRAPH decides what scopes: a token that matches no
instrument in the register is dropped before the query is built
(``_tokens_present_in_register``), so an unscopeable question is answered building-wide from
the same register rather than abandoned.
"""

import re
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.sparql_agent import SPARQLAgent  # noqa: E402
from orchestrator.services import routing_contract as rc  # noqa: E402

#: The three predicates that ARE the register. Named once, here, and asserted against every
#: reader below — a second reader inventing a fourth name is how two sources of truth start.
REGISTER_PREDICATES = ("calibratedOn", "calibrationDueOn", "calibrationMethod")

#: A miniature of the real register: names as bldg1 spells them, one per shape that matters.
_FAKE_SENSORS = [
    ("Air_CO2_Level_Sensor_5.01", "2025-11-17", "2026-11-17"),
    ("Air_CO2_Level_Sensor_5.02", "2025-11-18", "2027-11-18"),
    ("Room5.01_sat_co2", "2026-05-27", "2027-05-27"),
    ("Air_Temperature_Sensor_5.01", "2024-01-05", "2025-01-05"),  # overdue
    ("AHU_F0_Fan_Status", "", ""),  # a contact signal: verified, not calibrated
]
_TODAY = "2026-09-29"


class _FakeGraph:
    """Answers the three shapes of query the metrology lane builds, from _FAKE_SENSORS."""

    def __init__(self) -> None:
        self.queries: List[str] = []

    async def execute(self, query: str) -> Dict[str, Any]:
        self.queries.append(query)
        if "VALUES ?tok" in query:
            toks = re.findall(r'"([^"]*)"', query.split("VALUES ?tok")[1].split("}")[0])
            rows = []
            for tok in toks:
                n = sum(1 for name, _, _ in _FAKE_SENSORS if tok in name.lower())
                if n:
                    rows.append(
                        {
                            "tok": {"type": "literal", "value": tok},
                            "n": {"type": "literal", "value": str(n)},
                        }
                    )
            return {"head": {"vars": ["tok", "n"]}, "results": {"bindings": rows}}
        if "COUNT(DISTINCT ?s)" in query:
            with_regime = [s for s in _FAKE_SENSORS if s[2]]
            overdue = [s for s in with_regime if s[2] < _TODAY]
            return {
                "head": {"vars": ["a", "b", "c"]},
                "results": {
                    "bindings": [
                        {
                            "sensors_with_declared_interval": {
                                "type": "literal",
                                "value": str(len(_FAKE_SENSORS)),
                            },
                            "sensors_with_a_calibration_regime": {
                                "type": "literal",
                                "value": str(len(with_regime)),
                            },
                            "calibrations_overdue": {
                                "type": "literal",
                                "value": str(len(overdue)),
                            },
                        }
                    ]
                },
            }
        wanted = [
            m.lower() for m in re.findall(r'CONTAINS\(LCASE\(STR\(\?sensor\)\), "([^"]*)"', query)
        ]
        rows = []
        for name, on, due in _FAKE_SENSORS:
            if wanted and not any(w in name.lower() for w in wanted):
                continue
            rows.append(
                {
                    "sensor": {"type": "uri", "value": f"http://example.org/b#{name}"},
                    "calibrated_on": {"type": "literal", "value": on},
                    "calibration_due_on": {"type": "literal", "value": due},
                }
            )
        return {"head": {"vars": ["sensor"]}, "results": {"bindings": rows}}


@pytest.fixture()
def lane(monkeypatch):
    """A SPARQLAgent whose graph is the fake register and whose narration is inert."""
    agent = SPARQLAgent()
    graph = _FakeGraph()
    monkeypatch.setattr(agent, "_execute_query", graph.execute)

    async def _fmt(results, guidance, query, *a, **kw):
        return f"GUIDANCE::{guidance}"

    monkeypatch.setattr(agent, "_format_results", _fmt)
    monkeypatch.setattr(agent, "_standardize_results", lambda *a, **kw: {})
    agent._test_graph = graph
    return agent


def _overdue_count(out: Dict[str, Any]) -> str:
    rows = out["results"]["results"]["bindings"]
    assert len(rows) == 1, "an unscoped calibration question must be COUNTED, not listed"
    return rows[0]["calibrations_overdue"]["value"]


# ── the acceptance: both phrasings, same register, same number ────────────────────────

BOTH_PHRASINGS = [
    "How many sensors are overdue for calibration?",
    "How many sensors are overdue for calibration, and what does that mean for the "
    "answers you give me?",
]


@pytest.mark.parametrize("query", BOTH_PHRASINGS)
@pytest.mark.asyncio
async def test_both_phrasings_reach_the_same_lane(query):
    """Routing was never the defect, and a change that moved it would hide the real one."""
    assert rc._METROLOGY_RE.search(query), f"{query!r} is not recognised as a metrology question"


@pytest.mark.asyncio
async def test_both_phrasings_answer_from_the_register_with_the_same_number(lane):
    """The acceptance for W3-02, stated as the tracker states it.

    Before the fix the second call returned None here — the lane gave the question up and
    the generated-query path then denied the register exists.
    """
    answers = []
    for query in BOTH_PHRASINGS:
        out = await lane._instrument_metrology(query)
        assert out is not None, (
            f"the metrology lane abandoned {query!r}; whatever answers it next cannot see "
            f"the calibration register and will deny it holds anything"
        )
        answers.append(_overdue_count(out))
    assert (
        answers[0] == answers[1]
    ), f"the same question answered {answers[0]} one way and {answers[1]} the other"


@pytest.mark.asyncio
async def test_the_trailing_clause_does_not_scope_the_query(lane):
    """ "...what does that mean for the answers you give me?" is not four sensor names."""
    await lane._instrument_metrology(BOTH_PHRASINGS[1])
    built = [q for q in lane._test_graph.queries if "VALUES ?tok" not in q]
    assert built, "no metrology query was built at all"
    for junk in ("mean", "answers", "give"):
        assert f'"{junk}"' not in built[-1], (
            f"{junk!r} was used as a sensor-name filter; a word the register has never "
            f"heard of must not decide which instruments the answer covers"
        )


# ── the mechanism, pinned directly ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_graph_decides_what_scopes_not_a_word_list(lane):
    kept = await lane._tokens_present_in_register(["mean", "answers", "co2", "you", "5.01"])
    assert kept == [
        "co2",
        "5.01",
    ], f"expected only the tokens the register actually carries, got {kept!r}"


@pytest.mark.asyncio
async def test_the_defect_returns_the_moment_the_check_is_removed(lane, monkeypatch):
    """The guard has teeth: put the denylist back in charge and the register goes dark.

    Without this, the acceptance test above could pass for reasons unrelated to the fix —
    and a later session deleting the scope check as "an extra query" would see nothing fail.
    """

    async def _keep_everything(tokens):
        return list(tokens)

    monkeypatch.setattr(lane, "_tokens_present_in_register", _keep_everything)
    out = await lane._instrument_metrology(BOTH_PHRASINGS[1])
    assert out is None, (
        "the scope check is no longer what keeps this question in the lane; whatever now "
        "does it is undocumented, and the denylist it replaced is still a denylist"
    )


@pytest.mark.asyncio
async def test_a_scope_check_that_cannot_run_does_not_widen_the_scope(monkeypatch):
    """Fail CLOSED on the scope: a lookup that errored must not silently answer building-wide."""
    agent = SPARQLAgent()

    async def _boom(_query):
        raise RuntimeError("graphdb unreachable")

    monkeypatch.setattr(agent, "_execute_query", _boom)
    assert await agent._tokens_present_in_register(["co2", "5.01"]) == ["co2", "5.01"]


@pytest.mark.asyncio
async def test_a_real_scope_still_scopes(lane):
    """The fix must not cost the instance answer that BUG-427 was opened for."""
    out = await lane._instrument_metrology("When was the CO2 sensor in Room 5.01 last calibrated?")
    assert out is not None
    names = [r["sensor"]["value"] for r in out["results"]["results"]["bindings"]]
    assert names, "a question naming Room 5.01 returned nothing from a register that holds it"
    assert all("5.01" in n for n in names), f"the scope leaked: {names}"


@pytest.mark.asyncio
async def test_a_scope_the_user_named_that_matches_nothing_is_stated(lane):
    """Honest, and still one lane: building-wide figures that SAY they are building-wide."""
    out = await lane._instrument_metrology(
        "When was the sensor in Room 9.99 last calibrated, Facilities?"
    )
    assert (
        out is not None
    ), "a question about an instrument the register does not cover fell out of the lane"
    assert "BUILDING-WIDE" in out["formatted_response"], (
        "the narration was not told the named scope matched nothing, so it will present "
        "the whole building's figures as if they were that room's"
    )


# ── one register: every reader names the same three properties ────────────────────────


def test_every_reader_names_the_same_three_properties():
    """A second reader inventing a fourth property name is how two registers begin."""
    import inspect

    from orchestrator.services.evidence import assemble

    readers = {
        "sparql_agent._instrument_metrology": inspect.getsource(SPARQLAgent._instrument_metrology),
        "evidence.assemble._calibration_state": inspect.getsource(assemble._calibration_state)
        + inspect.getsource(assemble._calibration_verdicts),
    }
    # The evidence reader works on a dict whose keys are built by its caller; what must
    # agree is the VOCABULARY, checked at the one place that names the RDF properties.
    src = readers["sparql_agent._instrument_metrology"]
    for prop in REGISTER_PREDICATES:
        assert prop in src, f"{prop} is no longer read by the lane that answers about it"
    assert "calibrated" in readers["evidence.assemble._calibration_state"]


def test_the_register_is_the_only_source_the_lane_consults():
    """Every figure is the graph's, and "overdue" is judged against TODAY (contract 3).

    TODO-484: the count moved 194 -> 201 -> 206 -> 237 -> 268 while the system stayed
    correct, because a due date passes on its own. A frozen date in this method would stop
    that drift by making the answer wrong instead.
    """
    import inspect

    src = inspect.getsource(SPARQLAgent._instrument_metrology)
    assert "ontosage.org/capabilities#" in src, "the lane no longer reads the register"
    assert "datetime.now(timezone.utc).date()" in src, (
        "overdue is no longer judged against today; a pinned date makes the count wrong "
        "rather than current"
    )
    assert not re.search(
        r'"\d{4}-\d{2}-\d{2}"', src
    ), "a literal date appears in the lane; the only date it may use is today's"
