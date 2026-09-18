"""A label that matches several rooms and names none of them is ambiguous (BUG-526).

`_exists` runs two `LIMIT 1` lookups with CONTAINS, and building ids share prefixes: "5.1"
is contained in Room5.10, Room5.11 and Room5.12. The gate reported RESOLVED, and a
downstream lane answered about whichever subject the store happened to return first — with
the user's own words in the answer, which is what makes it convincing.

Nothing recorded that the label had been ambiguous, so nothing downstream could.
"""

import pytest

from orchestrator.services.referent_resolver import (
    AMBIGUOUS,
    RESOLVED,
    ReferentResolver,
)

pytestmark = pytest.mark.unit

_NS = "http://example.org/bldg#"


def _exec_returning(subjects):
    """A SPARQL stub: every query answers with the same subject list."""

    async def _exec(query: str):
        return {"results": {"bindings": [{"s": {"value": s}} for s in subjects]}}

    return _exec


@pytest.mark.asyncio
async def test_a_prefix_matching_several_rooms_is_ambiguous():
    rooms = [f"{_NS}Room5.1{n}" for n in range(3)]
    res = await ReferentResolver(_exec_returning(rooms)).resolve(
        "what is the temperature in room 5.1?", entities=None, namespace=_NS
    )
    assert res.status == AMBIGUOUS
    assert res.referent == "5.1"
    assert len(res.suggestions) == 3
    assert "names none of them exactly" in res.message


@pytest.mark.asyncio
async def test_an_exact_id_resolves_even_though_other_ids_contain_it():
    """"5.01" matching {5.01} is one place however many sensors sit in it — and a room whose
    id is a prefix of nothing must not be made ambiguous by its own neighbours."""
    subjects = [f"{_NS}Room5.01", f"{_NS}CO2_Level_Sensor_5.01", f"{_NS}Humidity_5.01"]
    res = await ReferentResolver(_exec_returning(subjects)).resolve(
        "what is the temperature in room 5.01?", entities=None, namespace=_NS
    )
    assert res.status == RESOLVED


@pytest.mark.asyncio
async def test_a_word_shaped_referent_is_not_checked_for_ambiguity():
    """"kitchen" matching several rooms is ordinary language, not a typo — the lanes below
    already handle a set, and declining would cost a real answer."""
    subjects = [f"{_NS}Kitchen_Floor2", f"{_NS}Kitchen_Floor3"]
    res = await ReferentResolver(_exec_returning(subjects)).resolve(
        "is the kitchen busy?", entities=None, namespace=_NS
    )
    assert res.status != AMBIGUOUS


@pytest.mark.asyncio
async def test_a_failing_ambiguity_check_never_costs_a_resolved_referent():
    """This gate fails OPEN by design. A check added to it must not become a new way to
    refuse a question the building can answer."""

    calls = {"n": 0}

    async def _exec(query: str):
        calls["n"] += 1
        if calls["n"] == 1:  # the existence lookup succeeds
            return {"results": {"bindings": [{"s": {"value": f"{_NS}Room5.01"}}]}}
        raise RuntimeError("graph hiccup during the ambiguity check")

    res = await ReferentResolver(_exec).resolve(
        "what is the temperature in room 5.01?", entities=None, namespace=_NS
    )
    assert res.status == RESOLVED


@pytest.mark.asyncio
async def test_a_room_that_does_not_exist_is_still_not_found():
    """The pre-existing outcome must survive: an id-shaped token the graph does not know is
    a real mistake and telling the user is the point of the gate."""
    from orchestrator.services.referent_resolver import NOT_FOUND

    async def _exec(query: str):
        return {"results": {"bindings": []}}

    res = await ReferentResolver(_exec).resolve(
        "what is the temperature in room 5.99?", entities=None, namespace=_NS
    )
    assert res.status == NOT_FOUND


def test_the_pipeline_acts_on_the_new_status():
    """A status nothing consumes is a status that changes nothing — the shape of several
    defects in this tracker. The gate must answer AMBIGUOUS the way it answers NOT_FOUND."""
    from pathlib import Path

    source = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert "AMBIGUOUS," in source, "the status must be imported by the gate's caller"
    assert '_resolution.status == AMBIGUOUS' in source
    assert '"referent_ambiguous"' in source
    # And it must be checked BEFORE the not-found branch, or an ambiguous referent that
    # happens to exist would fall through to the lane that picks one.
    assert source.index("== AMBIGUOUS") < source.index("== NOT_FOUND")


@pytest.mark.asyncio
async def test_only_the_ids_that_actually_matched_are_suggested():
    """A subject can carry more than one number. Taking the FIRST dotted id offered "2.5"
    as a candidate for "5.1" — a suggestion the user never typed and cannot act on."""
    subjects = [
        f"{_NS}Sensor_2.5_Room5.10",
        f"{_NS}Room5.11",
        f"{_NS}Room5.12",
    ]
    res = await ReferentResolver(_exec_returning(subjects)).resolve(
        "what is the temperature in room 5.1?", entities=None, namespace=_NS
    )
    assert res.status == AMBIGUOUS
    assert set(res.suggestions) == {"5.10", "5.11", "5.12"}
    assert "2.5" not in res.suggestions
