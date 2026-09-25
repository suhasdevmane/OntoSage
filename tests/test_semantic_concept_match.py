"""The model may CHOOSE one of the building's concepts; it may never invent one.

This is the fallback for a lay word the ontology was never taught. "coolest" was the word that
exposed the gap: the register held "warmest", "hottest" and "coldest", so a temperature question
resolved to no measurand and was answered from the workspace register.
"""

import pytest

from orchestrator.services import semantic_concept_match as scm

pytestmark = pytest.mark.unit


CONCEPT_MAP = {
    "http://ontosage.org/hbco#thermal_comfort": {
        "concept_id": "thermal_comfort",
        "label": "Thermal comfort",
        "lay_terms": ["too warm", "warmest", "coldest", "stuffy heat"],
        "brick_classes": ["brick:Temperature_Sensor"],
    },
    "http://ontosage.org/hbco#stuffiness": {
        "concept_id": "stuffiness",
        "label": "Stuffiness",
        "lay_terms": ["stuffy", "stale air"],
        "brick_classes": ["brick:CO2_Level_Sensor"],
    },
    "http://ontosage.org/hbco#no_sensor": {
        "concept_id": "no_sensor",
        "label": "A concept this building cannot measure",
        "lay_terms": ["whatever"],
        "brick_classes": [],
    },
}


def _ids():
    return [c["id"] for c in scm.build_candidates(CONCEPT_MAP)]


# ── the menu ───────────────────────────────────────────────────────────────────────────────────

def test_only_concepts_the_building_can_measure_are_offered():
    """Offering a concept with no sensor invites a match that leads nowhere."""
    assert "no_sensor" not in _ids()
    assert set(_ids()) == {"stuffiness", "thermal_comfort"}


def test_the_menu_is_built_from_the_building_not_from_a_constant():
    """Another building's concepts are what its questions are matched against."""
    other = {"x#humid": {"concept_id": "humidity", "label": "Humidity", "lay_terms": ["damp"],
                         "brick_classes": ["brick:Humidity_Sensor"]}}
    assert [c["id"] for c in scm.build_candidates(other)] == ["humidity"]


def test_the_menu_shows_example_words():
    menu = scm.render_menu(scm.build_candidates(CONCEPT_MAP))
    assert "thermal_comfort" in menu and "warmest" in menu


# ── reading the reply ──────────────────────────────────────────────────────────────────────────

def test_a_listed_concept_is_accepted():
    got = scm.parse_choice("thermal_comfort | 'coolest' means lowest temperature", _ids())
    assert got.matched and got.concept_id == "thermal_comfort"


def test_none_is_a_real_answer_and_matches_nothing():
    got = scm.parse_choice("NONE | the building does not measure that", _ids())
    assert not got.matched and not got.skipped


@pytest.mark.parametrize(
    "reply",
    [
        "radiation_level | it is about radiation",     # a class the building does not have
        "brick:Temperature_Sensor | close enough",     # a class name, not a concept id
        "thermal_comfort_and_stuffiness | both",       # two concepts welded together
    ],
)
def test_an_off_menu_reply_is_discarded_not_trusted(reply):
    """The one failure that would matter: naming a sensor class the building does not hold."""
    got = scm.parse_choice(reply, _ids())
    assert not got.matched and "off-menu" in got.skipped


def test_an_empty_reply_matches_nothing():
    assert not scm.parse_choice("", _ids()).matched


def test_a_reply_is_read_case_insensitively():
    assert scm.parse_choice("Thermal_Comfort | yes", _ids()).concept_id == "thermal_comfort"


# ── the call itself ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_it_chooses_the_concept_and_carries_its_sensor_classes(monkeypatch):
    # ONE stub instance: `lambda: _TwoStep(...)` would build a fresh one per call, resetting its
    # counter so the confirmation step received the selection reply instead of YES.
    llm = _TwoStep("thermal_comfort | 'coolest' asks for the lowest temperature", "YES")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    got = await scm.match("where's the coolest place to work right now?", CONCEPT_MAP)
    assert got.matched and got.concept_id == "thermal_comfort"
    assert got.brick_classes == ["brick:Temperature_Sensor"]


@pytest.mark.asyncio
async def test_a_question_about_something_unmeasured_still_resolves_to_nothing(monkeypatch):
    """The honest 'this building does not measure that' decline must survive this component."""
    class _LLM:
        async def generate(self, *a, **k):
            return "NONE | radiation is not among the listed concepts"

    monkeypatch.setattr(scm, "_client", lambda: _LLM())
    got = await scm.match("what is the radiation level in the atrium?", CONCEPT_MAP)
    assert not got.matched


@pytest.mark.asyncio
async def test_a_provider_error_costs_nothing(monkeypatch):
    class _LLM:
        async def generate(self, *a, **k):
            raise RuntimeError("provider down")

    monkeypatch.setattr(scm, "_client", lambda: _LLM())
    got = await scm.match("anything at all", CONCEPT_MAP)
    assert not got.matched and got.skipped.startswith("error:")


@pytest.mark.asyncio
async def test_a_timeout_costs_nothing(monkeypatch):
    import asyncio

    class _LLM:
        async def generate(self, *a, **k):
            await asyncio.sleep(5)

    monkeypatch.setattr(scm, "_client", lambda: _LLM())
    got = await scm.match("anything at all", CONCEPT_MAP, timeout_s=0.05)
    assert not got.matched and "timed out" in got.skipped


@pytest.mark.asyncio
async def test_the_flag_turns_it_off(monkeypatch):
    monkeypatch.setattr(scm, "enabled", lambda: False)
    got = await scm.match("where is it coolest?", CONCEPT_MAP)
    assert not got.matched and got.skipped == "disabled"


@pytest.mark.asyncio
async def test_a_building_with_no_measurable_concept_is_not_asked(monkeypatch):
    called = []

    class _LLM:
        async def generate(self, *a, **k):
            called.append(1)
            return "x"

    monkeypatch.setattr(scm, "_client", lambda: _LLM())
    got = await scm.match("where is it coolest?", {"a": {"concept_id": "a", "brick_classes": []}})
    assert not got.matched and not called


@pytest.mark.asyncio
async def test_a_cached_resolution_does_not_call_the_model(monkeypatch):
    """The second person to use a new phrasing must pay nothing for it."""
    called = []

    class _LLM:
        async def generate(self, *a, **k):
            called.append(1)
            return "thermal_comfort | x" if len(called) == 1 else "YES"

    monkeypatch.setattr(scm, "_client", lambda: _LLM())
    store = {}

    async def cget(k):
        return store.get(k)

    async def cset(k, v):
        store[k] = v

    q = "where's the coolest place to work right now?"
    first = await scm.match(q, CONCEPT_MAP, cache_get=cget, cache_set=cset)
    second = await scm.match(q, CONCEPT_MAP, cache_get=cget, cache_set=cset)
    assert first.matched and second.matched
    assert second.concept_id == "thermal_comfort"
    assert len(called) == 2          # the first ask selects and confirms; the second asks nothing


# ── the confirmation step ──────────────────────────────────────────────────────────────────────
#
# Selecting from ~90 concepts is a recall problem the model is good at; DECLINING is what it is bad
# at. Measured live before this step existed: "what is the radiation level in the atrium?" was
# matched to solar irradiance and "is there smoke in the lab" to an emergency exit. Both produced
# honest-sounding answers to a question nobody asked.


def _llm(reply):
    class _L:
        async def generate(self, *a, **k):
            return reply

    return _L()


class _TwoStep:
    """First call selects, every later call is the confirmation."""

    def __init__(self, choice, confirm):
        self.choice, self.confirm, self.calls = choice, confirm, 0

    async def generate(self, *a, **k):
        self.calls += 1
        return self.choice if self.calls == 1 else self.confirm


@pytest.mark.asyncio
async def test_a_near_miss_is_rejected_at_confirmation(monkeypatch):
    """The chosen concept measures a DIFFERENT quantity, so it must not be used."""
    llm = _TwoStep("thermal_comfort | closest available", "NO")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    got = await scm.match("what is the radiation level in the atrium?", CONCEPT_MAP)
    assert not got.matched
    assert "different quantity" in got.reason


@pytest.mark.asyncio
async def test_a_confirmed_match_is_used(monkeypatch):
    llm = _TwoStep("thermal_comfort | 'coolest' means lowest temperature", "YES")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    got = await scm.match("where's the coolest place to work?", CONCEPT_MAP)
    assert got.matched and got.concept_id == "thermal_comfort"
    assert got.brick_classes == ["brick:Temperature_Sensor"]


@pytest.mark.asyncio
async def test_an_unclear_confirmation_is_not_a_match(monkeypatch):
    """Anything but YES leaves the question unresolved, so the honest decline still fires."""
    llm = _TwoStep("thermal_comfort | maybe", "it depends what you mean")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    assert not (await scm.match("where's the coolest place?", CONCEPT_MAP)).matched


@pytest.mark.asyncio
async def test_a_failing_confirmation_call_does_not_let_the_match_through(monkeypatch):
    class _L:
        def __init__(self):
            self.calls = 0

        async def generate(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                return "thermal_comfort | yes"
            raise RuntimeError("provider down")

    monkeypatch.setattr(scm, "_client", lambda: _L())
    assert not (await scm.match("where's the coolest place?", CONCEPT_MAP)).matched


@pytest.mark.asyncio
async def test_a_rejection_is_counted(monkeypatch):
    llm = _TwoStep("stuffiness | near enough", "NO")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    before = scm.ACTED["rejected"]
    await scm.match("is there smoke in the lab?", CONCEPT_MAP)
    assert scm.ACTED["rejected"] == before + 1


@pytest.mark.asyncio
async def test_it_counts_when_it_acts(monkeypatch):
    """A fail-open component nobody counts cannot be told from one that never runs."""
    llm = _TwoStep("stuffiness | stale air", "YES")
    monkeypatch.setattr(scm, "_client", lambda: llm)
    before = scm.ACTED["matched"]
    await scm.match("is the air stale in here", CONCEPT_MAP)
    assert scm.ACTED["matched"] == before + 1


# ── the readable-class filter: a menu is about THIS building, not the schema ──────────
#
# `fire_safety` and `emergency_exit` both name `brick:Smoke_Detector`. The schema agrees that
# is a sensor class; this building holds two instances of it and not one reading. Offering them
# as candidate measurands is what let "is there smoke in the lab?" resolve to an emergency exit,
# and no wording of the prompt fixes a menu that contains the wrong answer. Two rounds of prompt
# tuning traded that trap against recall on "which room is least noisy" and gained nothing --
# lessons.md #132.

SMOKE_MAP = dict(CONCEPT_MAP)
SMOKE_MAP["http://ontosage.org/hbco#fire_safety"] = {
    "concept_id": "fire_safety",
    "label": "Fire safety",
    "lay_terms": ["smoke", "fire"],
    "brick_classes": ["brick:Fire_Alarm", "brick:Smoke_Detector"],
}

#: What the live graph reports: classes with at least one instance carrying a timeseries.
READS = {"temperature_sensor", "co2_level_sensor"}


def test_a_class_with_no_readings_is_not_offered_as_a_quantity():
    ids = [c["id"] for c in scm.build_candidates(SMOKE_MAP, readable=READS)]
    assert "fire_safety" not in ids, "a class the building never reads is not a measurand"
    assert "thermal_comfort" in ids and "stuffiness" in ids, "real measurands must survive"


def test_an_unreadable_graph_stands_the_filter_down_rather_than_emptying_the_menu():
    """The direction this must fail in.

    An empty set would filter every concept away and silently disable the matcher, turning one
    unreadable HTTP call into a building that understands nothing. None means unknown, and an
    unknown must not act.
    """
    ids = [c["id"] for c in scm.build_candidates(SMOKE_MAP, readable=None)]
    assert "fire_safety" in ids, "with no reading of the graph, the menu is what it always was"


def test_the_filter_counts_how_often_it_acted():
    """A fail-open component nobody counts is indistinguishable from one that never runs.

    lessons.md #126 -- learned when a gate was believed to be guarding a lane it had stopped
    touching.
    """
    before = dict(scm.FILTER_STATS)
    scm.build_candidates(SMOKE_MAP, readable=READS)
    scm.build_candidates(SMOKE_MAP, readable=None)
    assert scm.FILTER_STATS["applied"] == before["applied"] + 1
    assert scm.FILTER_STATS["unavailable"] == before["unavailable"] + 1
    assert scm.FILTER_STATS["removed"] > before["removed"]


@pytest.mark.parametrize(
    "written",
    [
        "brick:Temperature_Sensor",
        "https://brickschema.org/schema/Brick#Temperature_Sensor",
        "http://example.org/vocab/Temperature_Sensor",
        "Temperature_Sensor",
    ],
)
def test_a_class_is_matched_however_it_is_written_down(written):
    """The graph returns full IRIs; the concept register writes prefixed names. A filter that
    compared the two spellings literally would remove every concept it was given."""
    one = {"k": {"concept_id": "c", "label": "c", "lay_terms": [], "brick_classes": [written]}}
    assert [c["id"] for c in scm.build_candidates(one, readable=READS)] == ["c"]


def test_the_filter_names_no_building_no_concept_and_no_class():
    """Building-agnostic by construction: the set comes from the active graph, never from here."""
    from pathlib import Path

    import ast

    src = Path("orchestrator/services/semantic_concept_match.py").read_text(encoding="utf-8")
    fn = next(
        n
        for n in ast.parse(src).body
        if isinstance(n, ast.FunctionDef) and n.name == "build_candidates"
    )
    # The EXECUTABLE body only. The docstring names `fire_safety` and `brick:Smoke_Detector`
    # on purpose -- that is the worked example of why this filter exists, and a guard that
    # forbade explaining itself would be paid for in the next maintainer's hour. Comments and
    # docstrings are prose; a literal in the LOGIC is what would break the next building.
    stmts = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    logic = "\n".join(ast.unparse(s) for s in stmts)
    for literal in ("bldg1", "bldg2", "abacws", "fire_safety", "Smoke_Detector", "Temperature"):
        assert literal.lower() not in logic.lower(), literal
