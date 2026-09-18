# -*- coding: utf-8 -*-
"""A decline may not recite registers that have nothing to do with the question (BUG-748/749).

Measured by hand over 147 live stakeholder answers on 2026-09-17
(docs/phase0/phase0_rerun_read.md, classes C8, C9 and C11):

    "Which washroom should I service next ...?"
        -> "Abacws Building's documents do not answer this. I searched Asset Engineering
            Register, Waste Collection Register, Water Hygiene Legionella ..."
           while 30 CleaningTask records were held and never searched.

    "Which current Security records are incomplete, stale, duplicated or conflicting ...?"
        -> the same decline, citing Continuity Provision, Coordination Function and Patrol
           Checkpoint.

Two separate defects sit in that one sentence and both are tested here.

* The LIST. The retriever returns the nearest passages whatever the distance, so naming all
  of them tells the reader the system looked in three unrelated registers — which it did.
  Only passages the strength test calls DISTINCTIVE are named now; when none is, the
  boundary is stated with no list at all. What was searched stays on the evidence record.
* The ABSENCE. "The building's records do not cover this" was said over registers the
  building holds. Before any decline, the held registers get a say, scored by the same
  function the routing short-circuit uses — so this cannot claim a register the question
  did not name, which would be the same defect with the sign flipped.

Every message here is also checked against the reader: a non-admin is never told to add or
upload anything (2026-09-17 user decision, see test_declines_speak_to_the_reader.py).
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

#: Words that only make sense to someone editing the building's data.
REMEDIATION_JARGON = (
    "ttl",
    "upload",
    "front-matter",
    "ingest",
    "no code change",
    "admin portal",
)


def _assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in REMEDIATION_JARGON:
        assert word not in lowered, f"{word!r} reached a non-admin reader:\n{text}"


def _state(msg: str, role=None):
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=msg,
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content=msg)],
    )
    if role is not None:
        state.intermediate_results["user_role"] = role
    return state


def _wire(monkeypatch, docs, held=(), distinctive=None):
    """The capability agent with its document lane and record registry supplied.

    ``distinctive`` decides which passages the strength test calls distinctive; None leaves
    the real function in place. ``held`` is the building's record classes.
    """
    import orchestrator.agents.capability_agent as cap
    import orchestrator.services.building_context as bctx
    import orchestrator.services.capability_graph_resolver as cgr
    import orchestrator.services.grounding_guard as gg
    import orchestrator.services.record_registry as rr

    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Bldg"))

    class _Resolver:
        async def resolve(self, _q):
            return []

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

    async def _docs(*_a, **_k):
        return list(docs)

    monkeypatch.setattr(cap, "_search_documents", _docs)
    # The on-topic guard decides WHETHER a passage is shown; this file is about what the
    # decline SAYS once the lane has them, so the passages are handed through unchanged.
    monkeypatch.setattr(gg, "filter_on_topic", lambda _q, hits, **_k: hits)

    if distinctive is not None:

        def _strength(_q, text, **_k):
            return gg.MATCH_DISTINCTIVE if text in distinctive else "weak"

        monkeypatch.setattr(gg, "match_strength", _strength)

    async def _load_lay_terms():
        return None

    async def _record_classes(*_a, **_k):
        return list(held)

    monkeypatch.setattr(rr, "load_lay_terms", _load_lay_terms)
    monkeypatch.setattr(rr, "record_classes", _record_classes)
    monkeypatch.setattr(rr, "absent_record_class", lambda *_a, **_k: None)
    return cap


def _undecided(monkeypatch, cap):
    """The passages were read and none of them answered — the decline branch."""

    async def _answer_from_passages(self, _q, _hits):
        return None, True

    monkeypatch.setattr(cap.CapabilityAgent, "_answer_from_passages", _answer_from_passages)


async def _answer(cap, msg, role=None):
    state = await cap.CapabilityAgent().answer(_state(msg, role))
    return state.intermediate_results["capability_result"]


def _cleaning_register():
    from orchestrator.services.record_registry import RecordClass, _terms_for

    return RecordClass(
        "CleaningTask",
        "Cleaning task",
        30,
        _terms_for("CleaningTask", "Cleaning task", "washroom should i service|my zone"),
    )


WASHROOM = (
    "Which washroom should I service next, considering required frequency, time since "
    "the last confirmed service and current demand evidence?"
)
SECURITY = (
    "Which current Security records are incomplete, stale, duplicated or conflicting, "
    "and which operational decisions do those defects block?"
)

#: The three passages row 86 was declined with, verbatim from the live read.
UNRELATED_HITS = [
    {
        "doc_name": "continuity_provision",
        "text": "Service continuity fallback arrangements.",
        "score": 0.52,
    },
    {
        "doc_name": "coordination_function",
        "text": "Coordination duty roster and system state.",
        "score": 0.51,
    },
    {
        "doc_name": "patrol_checkpoint",
        "text": "Checkpoint sequence and shift verification.",
        "score": 0.50,
    },
]


class TestTheDeclineNamesOnlyWhatWasAboutTheQuestion:
    async def test_an_unrelated_register_is_not_recited(self, monkeypatch):
        """Row 86: three registers named at a reader who asked about none of them."""
        cap = _wire(monkeypatch, docs=UNRELATED_HITS, distinctive=set())
        _undecided(monkeypatch, cap)
        res = await _answer(cap, SECURITY)
        text = res["response"]
        for name in ("Continuity Provision", "Coordination Function", "Patrol Checkpoint"):
            assert name not in text, f"an unrelated register was recited:\n{text}"
        assert "could not find this in" in text.lower()
        _assert_plain(text)

    async def test_what_was_searched_is_still_on_the_evidence_record(self, monkeypatch):
        """Narrowing the sentence must not narrow the audit trail."""
        cap = _wire(monkeypatch, docs=UNRELATED_HITS, distinctive=set())
        _undecided(monkeypatch, cap)
        res = await _answer(cap, SECURITY)
        assert res["documents"] == [
            "Continuity Provision",
            "Coordination Function",
            "Patrol Checkpoint",
        ]
        assert res["documents_named"] == []

    async def test_a_document_that_IS_about_the_question_is_still_named(self, monkeypatch):
        """The honest half is kept: a close document is named, an incidental one is not."""
        hits = UNRELATED_HITS + [
            {
                "doc_name": "security_records_register",
                "text": "Security record review.",
                "score": 0.8,
            }
        ]
        cap = _wire(monkeypatch, docs=hits, distinctive={"Security record review."})
        _undecided(monkeypatch, cap)
        res = await _answer(cap, SECURITY)
        text = res["response"]
        assert "Security Records Register" in text
        assert "Patrol Checkpoint" not in text
        assert res["documents_named"] == ["Security Records Register"]

    @pytest.mark.parametrize("role", [None, "occupant", "facility_manager"])
    async def test_a_non_admin_is_never_told_to_add_anything(self, monkeypatch, role):
        cap = _wire(monkeypatch, docs=UNRELATED_HITS, distinctive=set())
        _undecided(monkeypatch, cap)
        _assert_plain((await _answer(cap, SECURITY, role))["response"])


class TestAHeldRegisterIsNamedBeforeAnAbsenceIsClaimed:
    async def test_the_document_decline_gives_way_to_the_register(self, monkeypatch):
        """Row 20: declined over 30 cleaning tasks the lane never looked at."""
        cap = _wire(
            monkeypatch,
            docs=UNRELATED_HITS,
            held=[_cleaning_register()],
            distinctive=set(),
        )
        _undecided(monkeypatch, cap)
        res = await _answer(cap, WASHROOM)
        text = res["response"]
        assert res["provenance"] == "held_register_named"
        assert "cleaning task" in text.lower()
        assert "30" in text
        assert "documents do not answer" not in text.lower()
        assert "records do not cover" not in text.lower()

    async def test_the_no_match_boundary_gives_way_too(self, monkeypatch):
        """Row 111's sentence — 'I don't have that specific information on record'."""
        cap = _wire(monkeypatch, docs=[], held=[_cleaning_register()])
        res = await _answer(cap, WASHROOM)
        assert res["provenance"] == "held_register_named"
        assert "I don't have that specific information" not in res["response"]

    async def test_a_register_the_question_did_not_name_is_not_claimed(self, monkeypatch):
        """The sign-flipped C8 defect: naming a held register nobody asked about."""
        cap = _wire(monkeypatch, docs=[], held=[_cleaning_register()])
        res = await _answer(cap, "How do I connect to the wifi?")
        assert res["provenance"] == "no_match"
        assert "cleaning" not in res["response"].lower()

    async def test_a_building_with_no_registers_declines_exactly_as_before(self, monkeypatch):
        """A building that holds nothing must be unaffected (design contract 1 and 3)."""
        cap = _wire(monkeypatch, docs=UNRELATED_HITS, held=[], distinctive=set())
        _undecided(monkeypatch, cap)
        res = await _answer(cap, WASHROOM)
        assert res["provenance"] == "documents_do_not_answer"

    async def test_an_unreadable_registry_never_blocks_the_decline(self, monkeypatch):
        """A graph hiccup must degrade to the old decline, not to an error."""
        import orchestrator.services.record_registry as rr

        cap = _wire(monkeypatch, docs=UNRELATED_HITS, held=[], distinctive=set())
        _undecided(monkeypatch, cap)

        def _boom(*_a, **_k):
            raise RuntimeError("graph unavailable")

        monkeypatch.setattr(rr, "rank_record_classes", _boom)
        res = await _answer(cap, WASHROOM)
        assert res["provenance"] == "documents_do_not_answer"

    @pytest.mark.parametrize("role", [None, "occupant", "facility_manager", "admin"])
    async def test_the_register_note_tells_nobody_to_add_data(self, monkeypatch, role):
        """Not even an admin: the register is HELD, so there is nothing to add."""
        cap = _wire(monkeypatch, docs=[], held=[_cleaning_register()])
        _assert_plain((await _answer(cap, WASHROOM, role))["response"])
