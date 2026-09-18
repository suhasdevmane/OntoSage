# -*- coding: utf-8 -*-
"""An honest decline speaks to the person reading it (2026-09-17, user decision).

Measured live: every honest decline told EVERY reader how to fix the system —

    "No — radiation is not measured in the atrium. ...
     Unlock: install a sensor and describe it in the ontology, or upload a TTL for one
     that already exists."

A supervisor or an occupant cannot upload a TTL, and an answer that tells them to reads as a
broken system rather than as a building that does not measure radiation. The decision:

* every reader keeps the HONEST DECLINE (design contract 4 — it never disappears) and what IS
  available, in plain words;
* only a reader whose authenticated ROLE holds ``system:admin`` also sees the remediation.
  Personas are not RBAC (contracts 5 and 7), so the persona plays no part;
* an unknown or missing role is NOT an administrator — the failure goes toward the plain
  message.

Each message site is asked the same four questions: does a non-admin see the decline, does a
non-admin see no remediation jargon, does an admin see the remediation, and is the decline
sentence itself identical in both.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

#: Words that only make sense to someone editing the building's data. None may reach a reader
#: who cannot act on them.
REMEDIATION_JARGON = (
    "TTL",
    "upload",
    "front-matter",
    "ingest",
    "ref:",
    "hasTimeseriesId",
    "install a sensor",
    "Unlock",
    "no code change",
    "ontology",
    "Admin portal",
)

NON_ADMIN_ROLES = ("facility_manager", "analyst", "operator", "occupant", "readonly")
UNKNOWN_ROLES = (None, "", "   ", "guest", "anonymous", "superuser", 7, ["admin"])


def _assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in REMEDIATION_JARGON:
        assert word.lower() not in lowered, f"{word!r} reached a non-admin reader:\n{text}"


# ── who counts as an administrator ───────────────────────────────────────────


class TestWhoIsAnAdministrator:
    def test_the_admin_role_holds_the_permission(self):
        from orchestrator.services.grounding_guard import reader_is_admin

        assert reader_is_admin("admin")

    @pytest.mark.parametrize("role", NON_ADMIN_ROLES)
    def test_every_other_built_in_role_does_not(self, role):
        """facility_manager holds config:write — and still is not shown TTL instructions."""
        from orchestrator.services.grounding_guard import reader_is_admin

        assert not reader_is_admin(role)

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    def test_an_unknown_role_is_not_an_administrator(self, role):
        from orchestrator.services.grounding_guard import reader_is_admin

        assert not reader_is_admin(role)

    def test_the_decision_is_a_permission_not_a_role_name(self, monkeypatch):
        """A role granted system:admin later must see the remediation with no code change."""
        import orchestrator.middleware.rbac as rbac
        from orchestrator.services.grounding_guard import reader_is_admin

        monkeypatch.setitem(rbac.ROLE_PERMISSIONS, "estates_lead", {"system:admin"})
        assert reader_is_admin("estates_lead")
        monkeypatch.setitem(rbac.ROLE_PERMISSIONS, "admin", {"sensor:read"})
        assert not reader_is_admin("admin")

    def test_state_without_a_role_is_not_an_administrator(self):
        from orchestrator.services.grounding_guard import reader_is_admin_in

        assert not reader_is_admin_in(SimpleNamespace(intermediate_results={}))
        assert not reader_is_admin_in(SimpleNamespace())
        assert reader_is_admin_in(SimpleNamespace(intermediate_results={"user_role": "admin"}))


# ── observability: "can you measure X in Y?" ─────────────────────────────────


def _reach(status_entry, **kw):
    from orchestrator.services.observability import reach_from_coverage

    return reach_from_coverage("radiation", "the atrium", status_entry, **kw)


_REACH_CASES = {
    "uninstrumented": ({"status": "missing"}, "not measured in the atrium"),
    "unconnected": ({"status": "unbacked"}, "no radiation readings for the atrium"),
    "stale": (
        {"status": "present", "fresh": False, "stored_at": "co2_data"},
        "has not reported recently",
    ),
}


class TestObservabilityDeclines:
    @pytest.mark.parametrize("case", sorted(_REACH_CASES))
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, case):
        entry, verdict = _REACH_CASES[case]
        text = _reach(entry).describe()
        assert verdict in text
        _assert_plain(text)

    @pytest.mark.parametrize("case", sorted(_REACH_CASES))
    def test_an_admin_sees_the_remediation(self, case):
        entry, verdict = _REACH_CASES[case]
        text = _reach(entry).describe(for_admin=True)
        assert verdict in text
        assert "Unlock:" in text

    @pytest.mark.parametrize("case", sorted(_REACH_CASES))
    def test_the_decline_is_the_same_sentence_for_both(self, case):
        entry, _verdict = _REACH_CASES[case]
        plain = _reach(entry).describe()
        admin = _reach(entry).describe(for_admin=True)
        assert admin.startswith(plain.split("\n\n")[0])

    def test_the_admin_remediation_is_the_specific_one(self):
        assert "upload a TTL" in _reach({"status": "missing"}).describe(for_admin=True)
        unbacked = _reach({"status": "unbacked"}).describe(for_admin=True)
        assert "ref:hasTimeseriesId" in unbacked and "ref:storedAt" in unbacked
        stale = _reach({"status": "present", "fresh": False, "stored_at": "co2_data"})
        assert "co2_data" in stale.describe(for_admin=True)
        assert "co2_data" not in stale.describe(), "a store name is an internal identifier"

    @pytest.mark.parametrize("entry", [{"status": "missing"}, {"status": "unbacked"}])
    def test_what_is_measured_is_offered_to_everyone(self, entry):
        """The offer comes from the coverage matrix the caller already holds, never a guess."""
        text = _reach(entry, present_modalities=["co2", "humidity", "noise"]).describe()
        assert "What IS measured there: co2, humidity, noise" in text
        _assert_plain(text)

    def test_no_alternatives_invents_none(self):
        text = _reach({"status": "missing"}).describe()
        assert "What IS measured" not in text
        assert "invented" in text

    def test_a_plain_decline_does_not_soften_absence(self):
        """'Not measured' must not become something that implies it might be."""
        text = _reach({"status": "missing"}).describe()
        for hedge in ("not yet", "coming soon", "may be", "might be", "soon"):
            assert hedge not in text.lower()

    def test_the_workflow_passes_the_readers_role(self):
        """The lane must not call describe() without deciding who is reading."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert "reach.describe()" not in src
        assert "reach.describe(for_admin=_for_admin)" in src
        assert "_for_admin = reader_is_admin_in(state)" in src


# ── grounding_guard.enablement_hint ──────────────────────────────────────────


class TestEnablementHint:
    @pytest.mark.parametrize("kind", ["sensor", "space", "equipment", "document", "other"])
    def test_a_non_admin_gets_nothing_appended(self, kind):
        from orchestrator.services.grounding_guard import enablement_hint

        assert enablement_hint(kind, "the helipad") == ""
        assert enablement_hint(kind, "the helipad", for_admin=False) == ""

    def test_an_admin_gets_the_steps(self):
        from orchestrator.services import grounding_guard as gg

        sensor = gg.enablement_hint(gg.SUBJECT_SENSOR, "methane", for_admin=True)
        assert "ref:hasTimeseriesId" in sensor and "upload a TTL" in sensor
        assert "documents/" in gg.enablement_hint(gg.SUBJECT_DOCUMENT, for_admin=True)


# ── retrieval_outcome: the kinds of nothing ──────────────────────────────────


def _outcomes():
    from orchestrator.services.retrieval_outcome import SeriesResolution, classify

    return {
        "not_declared": classify(declared=False, subject="a radon sensor"),
        "reference_missing": classify(declared=True, has_reference=False, subject="the sensor"),
        "series_unresolved": classify(declared=True, series=SeriesResolution.UNKNOWN),
        "backend_unavailable": classify(declared=True, backend_reachable=False),
        "no_observations": classify(declared=True, series=SeriesResolution.CONFIRMED),
        "insufficient_quality": classify(declared=True, rows=4, quality_ok=False),
        "access_restricted": classify(declared=True, access_permitted=False),
    }


class TestRetrievalOutcomeDeclines:
    @pytest.mark.parametrize("name", sorted(_outcomes()))
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, name):
        from orchestrator.services.retrieval_outcome import describe

        r = _outcomes()[name]
        text = describe(r)
        assert text.startswith(r.external)
        _assert_plain(text)

    @pytest.mark.parametrize("name", sorted(_outcomes()))
    def test_an_admin_sees_every_remedy_there_is(self, name):
        from orchestrator.services.retrieval_outcome import describe

        r = _outcomes()[name]
        text = describe(r, for_admin=True)
        assert text.startswith(r.external)
        if r.admin_remedy:
            assert r.admin_remedy in text

    def test_the_admin_remedy_is_the_data_edit(self):
        from orchestrator.services.retrieval_outcome import describe

        o = _outcomes()
        assert "ontology" in describe(o["not_declared"], for_admin=True)
        assert "ref:hasTimeseriesId" in describe(o["reference_missing"], for_admin=True)

    def test_a_step_any_reader_can_take_is_kept_for_everyone(self):
        """'Ask again shortly' and 'widen the period' are not instructions to add data."""
        from orchestrator.services.retrieval_outcome import describe

        o = _outcomes()
        assert "Ask again shortly" in describe(o["backend_unavailable"])
        assert "Widening the period" in describe(o["no_observations"])


# ── capability agent ─────────────────────────────────────────────────────────


def _state(msg: str, role):
    from shared.models import ConversationState, Message

    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=msg,
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content=msg)],
    )
    if role is not None:
        s.intermediate_results["user_role"] = role
    return s


def _wire(monkeypatch, docs):
    import orchestrator.agents.capability_agent as cap
    import orchestrator.services.building_context as bctx
    import orchestrator.services.capability_graph_resolver as cgr

    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Bldg"))

    class _Resolver:
        async def resolve(self, _q):
            return []

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

    async def _docs(*_a, **_k):
        return docs

    monkeypatch.setattr(cap, "_search_documents", _docs)
    return cap


async def _answer(cap, msg, role):
    state = await cap.CapabilityAgent().answer(_state(msg, role))
    return state.intermediate_results["capability_result"]


_READERS = [("admin", True), ("occupant", False), ("facility_manager", False), (None, False)]


class TestCapabilityNoMatch:
    @pytest.mark.parametrize("role,admin", _READERS)
    async def test_the_honest_boundary(self, monkeypatch, role, admin):
        cap = _wire(monkeypatch, docs=[])
        res = await _answer(cap, "how do I connect to the wifi?", role)
        assert res["provenance"] == "no_match"
        text = res["response"]
        assert "I don't have that specific information on record" in text
        if admin:
            assert "no code changes" in text.lower()
        else:
            _assert_plain(text)


class TestCapabilityDocumentsDoNotAnswer:
    @pytest.mark.parametrize("role,admin", _READERS)
    async def test_documents_searched_and_none_answered(self, monkeypatch, role, admin):
        cap = _wire(
            monkeypatch,
            docs=[
                {
                    "doc_name": "wifi_policy",
                    "text": "Connect to the Guest-WiFi network from any wifi enabled device.",
                    "score": 0.7,
                }
            ],
        )

        async def _undecided_passage(self, _q, _hits):
            return None, True

        monkeypatch.setattr(cap.CapabilityAgent, "_answer_from_passages", _undecided_passage)
        res = await _answer(cap, "how do I connect to the wifi?", role)
        assert res["provenance"] == "documents_do_not_answer"
        text = res["response"]
        assert "documents do not answer this" in text
        assert "wifi policy" in text.lower()  # the honest "I searched ..." part is kept
        # BUG-710: this used to require "the building's records do not cover this" — a claim
        # about everything the building holds, reached by searching documents only. The
        # decline may report the documents it read and nothing wider.
        assert "the building's records do not cover this" not in text
        assert "not about the building" in text
        # BUG-730: an owner nobody names points nowhere.
        assert "holds the answer" not in text
        assert "owner" not in text.lower()
        if admin:
            assert "front-matter" in text
        else:
            _assert_plain(text)


class TestCapabilityAbsentRecordClass:
    @pytest.mark.parametrize("role,admin", _READERS)
    async def test_a_system_of_record_the_building_does_not_hold(self, monkeypatch, role, admin):
        import orchestrator.services.record_registry as rr

        cap = _wire(monkeypatch, docs=[])

        async def _noop(*_a, **_k):
            return []

        monkeypatch.setattr(rr, "load_lay_terms", _noop)
        monkeypatch.setattr(rr, "record_classes", _noop)
        monkeypatch.setattr(rr, "absent_record_class", lambda _q, _c: "ServiceContract")
        res = await _answer(cap, "how do I connect to the wifi?", role)
        assert res["provenance"] == "absent_system_of_record"
        text = res["response"]
        assert "holds no service contract records" in text
        assert "authoritative answer" in text
        if admin:
            assert "front-matter" in text and "TTL" in text
        else:
            _assert_plain(text)


class TestCapabilityAbsentReferent:
    @pytest.mark.parametrize("role,admin", _READERS)
    async def test_a_named_place_that_is_not_there(self, monkeypatch, role, admin):
        import orchestrator.agents.sparql_agent as sa
        import orchestrator.services.referent_resolver as rres
        from orchestrator.agents.capability_agent import CapabilityAgent

        class _Agent:
            async def _execute_query(self, _q):
                return {}

        monkeypatch.setattr(sa, "SPARQLAgent", _Agent)
        monkeypatch.setattr(sa, "_active_namespace", lambda: "http://example.org/b#")

        async def _not_found(self, **_k):
            return rres.ReferentResolution(
                status=rres.NOT_FOUND, referent="the helipad", suggestions=["Floor 5"]
            )

        monkeypatch.setattr(rres.ReferentResolver, "resolve", _not_found)
        monkeypatch.setattr(
            rres,
            "detect_typed_referent",
            lambda _q: rres.TypedReferent(
                kind="space", token="helipad", phrase="the helipad", head="helipad"
            ),
        )
        res = await CapabilityAgent._absent_referent_decline(
            _state("what is the temperature on the helipad?", role), "bldg1", "Bldg"
        )
        text = res["response"]
        assert "I couldn't find **the helipad**" in text
        assert "What this building does have: **Floor 5**" in text
        if admin:
            assert "upload a TTL" in text
        else:
            _assert_plain(text)
