"""Unit tests for capability facts answered from ontology triples (ROADMAP-009).

The SPARQL executor is injected and mocked, so these run offline. They lock in that
structured amenity questions (prayer room, café, lift) are answered from triples, that
weak/unrelated queries fall through to the KB, and that the resolver degrades gracefully.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.capability_graph_resolver import (
    CapabilityFact,
    CapabilityGraphResolver,
)

pytestmark = pytest.mark.unit

_AMENITIES = [
    {
        "label": "Multi-faith prayer & reflection room",
        "loc": "Floor 1, room 1.04",
        "note": "Available to all.",
        "cat": "AMENITIES",
        "lay": "prayer room, quiet room, reflection, faith, worship, where can i pray",
    },
    {
        "label": "Abacws Café",
        "loc": "Ground floor",
        "note": "Open 08:00-16:30.",
        "cat": "AMENITIES",
        "lay": "cafe, coffee, canteen, food, lunch, get a coffee",
    },
    {
        "label": "Main passenger lift",
        "loc": "serves floors G-5",
        "note": "Weight limit 1000 kg.",
        "cat": "ACCESSIBILITY",
        "lay": "lift, elevator, passenger lift, where is the lift, nearest lift",
    },
]


def _exec_amenities(amenities):
    async def _exec(_query: str) -> dict:
        return {
            "results": {
                "bindings": [
                    {
                        "a": {"value": f"urn:{i}"},
                        "label": {"value": am["label"]},
                        "loc": {"value": am["loc"]},
                        "note": {"value": am["note"]},
                        "cat": {"value": am["cat"]},
                        "lay": {"value": am["lay"]},
                    }
                    for i, am in enumerate(amenities)
                ]
            }
        }

    return _exec


def _resolver():
    return CapabilityGraphResolver(sparql_exec=_exec_amenities(_AMENITIES))


async def test_prayer_room_matches():
    facts = await _resolver().resolve("Is there a prayer room in the building?")
    assert facts and facts[0].label.startswith("Multi-faith prayer")
    assert "1.04" in facts[0].location


async def test_coffee_matches_cafe():
    facts = await _resolver().resolve("where can I get a coffee?")
    assert facts and facts[0].label == "Abacws Café"


async def test_lift_matches():
    facts = await _resolver().resolve("where is the nearest lift?")
    assert facts and facts[0].label == "Main passenger lift"


async def test_unrelated_query_falls_through():
    # No amenity terms → return nothing so the KB / document search handles it.
    facts = await _resolver().resolve("what is the temperature in zone 5.28 right now?")
    assert facts == []


async def test_common_word_does_not_false_match():
    # "room" alone is not distinctive enough (single word, but appears in a multi-word
    # lay phrase only) — a bare "book a room" must not hijack the prayer room.
    facts = await _resolver().resolve("how do I book a room?")
    assert all("prayer" not in f.label.lower() for f in facts)


async def test_graceful_on_sparql_error():
    async def _boom(_q):
        raise RuntimeError("GraphDB down")

    facts = await CapabilityGraphResolver(sparql_exec=_boom).resolve("where is the lift?")
    assert facts == []  # falls through to KB, never raises


def test_fact_render():
    f = CapabilityFact(label="Main passenger lift", location="serves floors G-5", note="1000 kg.")
    r = f.render()
    assert "Main passenger lift" in r and "serves floors G-5" in r and "1000 kg" in r


# ── Knowledge topics (WS-3): procedures / info / maintenance issues ────────────


def _exec_rows(rows):
    async def _exec(_query: str) -> dict:
        return {"results": {"bindings": rows}}

    return _exec


async def test_knowledge_topic_answered_from_triples():
    rows = [
        {
            "a": {"value": "urn:leak"},
            "label": {"value": "Water leak / leakage"},
            "lay": {"value": "leak, leaking, leakage, water on the floor, flooding"},
            "answer": {"value": "Report water leaks to Estates immediately."},
            "report": {"value": "Estates FM helpdesk"},
            "email": {"value": "estates@cardiff.ac.uk"},
        }
    ]
    facts = await CapabilityGraphResolver(sparql_exec=_exec_rows(rows)).resolve(
        "there is a leak in the ceiling"
    )
    assert facts and facts[0].label.startswith("Water leak")
    r = facts[0].render()
    assert "Report water leaks" in r
    assert "Report to: Estates FM helpdesk" in r
    assert "estates@cardiff.ac.uk" in r


def test_fact_render_knowledge_topic():
    f = CapabilityFact(
        label="Making a complaint",
        answer="Contact the Building Manager.",
        report_to="FM helpdesk",
        email="estates@cardiff.ac.uk",
        steps="Note the room and floor; Email estates@cardiff.ac.uk",
    )
    r = f.render()
    assert "Making a complaint" in r and "Contact the Building Manager" in r
    assert "Report to: FM helpdesk" in r and "Steps:" in r and "(1)" in r and "(2)" in r


async def test_capability_agent_answers_from_triples(monkeypatch):
    import orchestrator.agents.capability_agent as cap
    import orchestrator.services.building_context as bctx
    import orchestrator.services.capability_graph_resolver as cgr
    from shared.models import ConversationState, Message

    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Abacws"))

    class _FakeResolver:
        async def resolve(self, _q):
            return [
                cgr.CapabilityFact(
                    label="Main passenger lift", location="serves floors G-5", note="1000 kg."
                )
            ]

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _FakeResolver())

    state = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message="where is the lift?",
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content="where is the lift?")],
    )
    out = await cap.CapabilityAgent().answer(state)
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "capability_graph"
    assert "Main passenger lift" in res["response"]
    assert "ontology" in res["response"].lower()


# ── new Facility / Service / Accessibility amenities (Phase 1.2) ──────────────

_FACILITY_AMENITIES = [
    {
        "label": "Makerspace & IT Workshop",
        "loc": "Abacws",
        "note": "",
        "cat": "FACILITY",
        "lay": "makerspace, it workshop, labs, key facilities, what facilities",
    },
    {
        "label": "Reception",
        "loc": "Ground floor",
        "note": "Mon-Fri 09:00-16:30",
        "cat": "SERVICE",
        "lay": "reception, front desk, opening hours, reception hours, when is it open",
    },
    {
        "label": "Accessibility",
        "loc": "Building-wide",
        "note": "",
        "cat": "ACCESSIBILITY",
        "lay": "wheelchair, accessible, disability, step-free, hearing loop, blue badge",
    },
]


async def test_new_facility_service_amenities_match():
    r = CapabilityGraphResolver(sparql_exec=_exec_amenities(_FACILITY_AMENITIES))
    assert (await r.resolve("where is the makerspace?"))[0].label.startswith("Makerspace")
    assert (await r.resolve("what are the reception opening hours?"))[0].label == "Reception"
    assert (await r.resolve("is the building wheelchair accessible?"))[0].label == "Accessibility"


# ── CAPABILITIES_TTL_FIRST flag: prose answered from documents, not the KB ─────


def _cap_setup(monkeypatch, resolver_facts, docs):
    """Wire up the capability agent with a stub resolver + document search (TODO-012: no KB)."""
    import orchestrator.agents.capability_agent as cap
    import orchestrator.services.building_context as bctx
    import orchestrator.services.capability_graph_resolver as cgr

    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Abacws"))

    class _Resolver:
        async def resolve(self, _q):
            return resolver_facts

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

    async def _docs(*_a, **_k):
        return docs

    monkeypatch.setattr(cap, "_search_documents", _docs)


def _cap_state(msg="how do I connect to the wifi?"):
    from shared.models import ConversationState, Message

    return ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=msg,
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content=msg)],
    )


async def test_no_source_gives_honest_boundary(monkeypatch):
    # TODO-012: capability.yaml + its Qdrant KB safety net are GONE. Triples miss +
    # documents miss → an honest boundary, never a fabricated answer.
    import orchestrator.agents.capability_agent as cap

    _cap_setup(monkeypatch, resolver_facts=[], docs=[])
    res = (await cap.CapabilityAgent().answer(_cap_state())).intermediate_results[
        "capability_result"
    ]
    assert res["provenance"] == "no_match"
    assert "don't have that specific information" in res["response"].lower()


async def test_documents_answer_when_triples_miss(monkeypatch):
    # Triples miss, an uploaded manual matches → answered from documents.
    # The chunk must be a REALISTIC match for the question: since BUG-103 the node
    # refuses to present a passage that is topically unrelated to what was asked.
    import orchestrator.agents.capability_agent as cap

    _cap_setup(
        monkeypatch,
        resolver_facts=[],
        docs=[
            {
                "doc_name": "wifi_policy",
                "text": "Connect to the Guest-WiFi network; no password is required.",
                "score": 0.5,
            }
        ],
    )
    res = (await cap.CapabilityAgent().answer(_cap_state())).intermediate_results[
        "capability_result"
    ]
    # Either provenance means the document source fired. The lane now COMPOSES an answer
    # from the passage where it can ("document_answered") and falls back to presenting the
    # passage where the composer cannot run ("document_kb") — so which one appears depends
    # on whether a model is reachable, and pinning one made this test pass on a dev box
    # and fail in a parked checkout. What the test is actually for is that documents work
    # as a source without capability.yaml, and both labels say they did.
    assert res["provenance"] in ("document_kb", "document_answered")


async def test_off_topic_document_is_not_presented_as_an_answer(monkeypatch):
    """BUG-103: a real-but-unrelated chunk must NOT be dressed up as the answer.

    Vector similarity alone let an HVAC CO2 table 'answer' a question about pH — real
    text, wrong question. The invariant is that the off-topic chunk is never presented.

    Since BUG-136 the interception happens even earlier: "the water tank" is a named
    referent asking for a reading, and with no reachable graph (this test runs
    offline) the existence check cannot complete — so the answer is the honest
    "couldn't verify" rather than the post-search boundary. Either way the chunk
    must not appear; which honest reply is produced depends only on whether the
    check could run.
    """
    import orchestrator.agents.capability_agent as cap

    _cap_setup(
        monkeypatch,
        resolver_facts=[],
        docs=[
            {
                "doc_name": "hvac_operation",
                "text": "CO2 < 800 ppm (occupied); > 1000 ppm triggers damper opening.",
                "score": 0.62,
            }
        ],
    )
    state = _cap_state("What is the pH level of the water tank?")
    res = (await cap.CapabilityAgent().answer(state)).intermediate_results["capability_result"]
    # The load-bearing assertion: the unrelated chunk is never shown as the answer.
    assert "800 ppm" not in res["response"]
    assert res["provenance"] in ("no_match", "referent_not_found", "referent_unverified")
    if res["provenance"] == "no_match":
        # Post-search boundary: must tell the user how to make it answerable.
        assert "no code changes" in res["response"].lower()
    else:
        # Pre-search gate: must be clearly about the named thing, not a doc miss.
        assert "water tank" in res["response"]
