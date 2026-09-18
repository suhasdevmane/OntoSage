# -*- coding: utf-8 -*-
"""The ontology RAG fallback may not answer from class definitions, or invent an absence.

Measured on 2026-09-17, hand-reading 147 live answers as a non-admin facility manager. The
`semantic_rag` fallback (`SPARQLAgent.answer_semantically`) is handed a similarity-retrieved
slice of the graph — frequently TBox: a class, its rdfs:comment, its declared properties —
and asked to answer from that slice alone. Fourteen answers came back in one of two shapes:

* the SCHEMA narrated as the building ("the only property that hints at a governance
  relationship is policyOwner"), usually closing with an instruction to extend the ontology;
* "not in the slice I was given" published as "not in the building". Row 57 told a person
  with accessibility needs the building has no toilet records; row 88 told a space planner
  it has no occupancy sensors. Both are in the graph in quantity.

`_ground_semantic_fallback` corrects exactly those two, from the building's own live
register vocabulary, and touches no other lane.
"""

import pytest

from orchestrator.workflow import _orchestrator
from orchestrator.workflow._orchestrator import _ground_semantic_fallback

pytestmark = pytest.mark.unit


class _Record:
    def __init__(self, local_name, label, instances, terms=()):
        self.local_name = local_name
        self.label = label
        self.instances = instances
        self.terms = tuple(terms)


class _State:
    def __init__(self, user_message="", method="semantic_rag", role="facility_manager"):
        self.user_message = user_message
        self.messages = []
        self.building_id = None
        self.intermediate_results = {
            "sparql_result": {"method": method},
            "user_role": role,
        }


_TOILET = _Record("ToiletFacility", "Toilet facility", 14, ("toilet facility", "toilet"))
_WORK = _Record("WorkOrder", "Work order", 412, ("work order", "work orders"))


@pytest.fixture
def registers(monkeypatch):
    async def _fake(state, timeout_s=5.0):
        return (["CO2", "temperature"], [_WORK, _TOILET])

    monkeypatch.setattr(_orchestrator, "_closest_holdings", _fake)


@pytest.fixture
def no_absent_class(monkeypatch):
    """The ontology defines no class for the question. Nothing may be named."""
    import orchestrator.services.record_registry as rr

    monkeypatch.setattr(rr, "absent_record_class", lambda q, held, *a, **k: None)


# ── 1. an absence the graph contradicts ──────────────────────────────────────

_ROW_57 = (
    "The ontology data provided does **not contain any information** about a Changing "
    "Places toilet (or any specific toilet) in or near this location."
)


@pytest.mark.asyncio
async def test_a_false_absence_is_replaced_by_the_register_that_holds_it(registers):
    out = await _ground_semantic_fallback(_State("Is a Changing Places toilet available?"), _ROW_57)
    assert "not contain any information" not in out
    assert "Toilet facility" in out
    assert "14 entries" in out


@pytest.mark.asyncio
async def test_the_correction_is_recorded_on_the_turn(registers):
    state = _State("Is a Changing Places toilet available?")
    await _ground_semantic_fallback(state, _ROW_57)
    assert state.intermediate_results["unsupported_absence_corrected"] == "ToiletFacility"


@pytest.mark.asyncio
async def test_an_absence_the_graph_supports_is_left_alone(registers, no_absent_class):
    """Not every 'we do not hold that' is false. The true ones are this system's best work."""
    honest = "This building does not record the barometric pressure of the plant room."
    assert await _ground_semantic_fallback(_State("barometric pressure?"), honest) == honest


@pytest.mark.asyncio
async def test_an_absence_that_already_names_the_register_is_left_alone(registers):
    """The claim is about something else inside an answer that DID find the register."""
    prose = (
        "The Toilet facility records do not contain an accessibility grade for each " "facility."
    )
    assert await _ground_semantic_fallback(_State("accessibility grade?"), prose) == prose


@pytest.mark.asyncio
async def test_a_supported_absence_names_the_record_that_would_carry_it(registers, monkeypatch):
    """'Not recorded' is far more useful when it says what WOULD have recorded it."""
    import orchestrator.services.record_registry as rr

    monkeypatch.setattr(rr, "absent_record_class", lambda q, held, *a, **k: "ContractRecord")
    out = await _ground_semantic_fallback(
        _State("which contracts expire this year?"),
        "This building does not record contract expiry dates.",
    )
    assert "contract record" in out
    assert "holds none" in out


# ── 2. remediation is for the reader who can act on it ───────────────────────

_ROW_13 = (
    "**Answer**\n\nThe building's records contain only ApprovalRecord objects.\n\n"
    "If you need to track this information, you would need to extend the ontology with "
    "properties that capture asset lifecycle events.\n\nLet me know if that helps."
)


@pytest.mark.asyncio
async def test_a_non_admin_is_not_told_to_edit_the_ontology(registers, no_absent_class):
    out = await _ground_semantic_fallback(_State("were controls transferred?"), _ROW_13)
    assert "extend the ontology" not in out
    assert "ApprovalRecord objects" in out, "only the instruction is removed, not the answer"


@pytest.mark.asyncio
async def test_an_admin_still_sees_it(registers, no_absent_class):
    out = await _ground_semantic_fallback(
        _State("were controls transferred?", role="admin"), _ROW_13
    )
    assert "extend the ontology" in out


# ── 3. blast radius ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_other_lane_is_untouched(registers):
    """The gate is the fallback's own marker. A register answer must pass through whole."""
    prose = "The building does not record a filter size for any asset."
    state = _State("filter size?", method="whole_register")
    assert await _ground_semantic_fallback(state, prose) == prose


@pytest.mark.asyncio
async def test_an_empty_answer_is_returned_unchanged(registers):
    assert await _ground_semantic_fallback(_State("anything"), "") == ""
