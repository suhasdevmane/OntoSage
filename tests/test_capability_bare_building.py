"""Bare-building guardrail — the capability node must answer from EVERY
KB-independent source even when the building has no ``capability.yaml``.

Why this file exists
--------------------
BUG-076 and BUG-078 were the same defect twice: the capability node early-returned
"I don't have a capability profile on record" whenever the building had no
``capability.yaml`` — *before* the live-metrics grounding, the ontology graph resolver,
and the document KB ever ran. TODO-012 then removed ``capability.yaml`` entirely, so this
KB-independent chain is now the ONLY path. These tests keep it honest.

The invariant these tests lock in
---------------------------------
**No answer source is a precondition for trying another.** With exactly ONE source
populated, that source must still produce the answer. The honest "no info" boundary is
reachable ONLY when every source (metrics, ontology triples, uploaded documents) misses.

Everything is offline: each source seam is injected, so no GraphDB / Qdrant / floor plans
are required. A building that ships only TTL capability triples (authored via the admin
GUI / OCBV TBox) inherits this guarantee for free — there is no ``capability.yaml``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import orchestrator.agents.capability_agent as cap
import orchestrator.services.building_context as bctx
import orchestrator.services.building_metrics as bmmod
import orchestrator.services.capability_graph_resolver as cgr
from orchestrator.services.building_metrics import BuildingMetricsSnapshot
from shared.models import ConversationState, Message


def _ascii_dashes(text: str) -> str:
    """Normalise the dash family so a typographic swap is not read as a different value."""
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        text = text.replace(dash, "-")
    return text


pytestmark = pytest.mark.unit

_BARE_NAME = "Bare Test Building"


def _state(message: str) -> ConversationState:
    return ConversationState(
        conversation_id="bare-1",
        user_id="u",
        user_message=message,
        building_id="bldgX",  # a building with NO capability.yaml
        current_intent="capability",
        messages=[Message(role="user", content=message)],
    )


class _FakeFact:
    """Minimal stand-in for a CapabilityGraphResolver fact (has .render() + .label)."""

    def __init__(self, label: str, text: str, document_ref: str = "") -> None:
        self.label = label
        self._text = text
        # A topic MAY name the document that sets it out in full; most do not.
        self.document_ref = document_ref

    def render(self) -> str:
        return self._text


def _bare_building(
    monkeypatch,
    *,
    snapshot: Optional[BuildingMetricsSnapshot] = None,
    facts: Optional[List[_FakeFact]] = None,
    docs: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Wire a building with NO capability.yaml and every source defaulting to a MISS.

    Only the source explicitly passed in is populated — so a produced answer proves
    that source fired on its own, with kb=None and no sibling source helping.
    """
    # 1. Display name resolves from building.yaml (there is no capability.yaml / KB anymore).
    monkeypatch.setattr(
        bctx, "resolve_building_context", lambda _bid: SimpleNamespace(name=_BARE_NAME)
    )

    # 3. Live metrics — miss by default (empty snapshot: no counts, no area).
    _snap = snapshot if snapshot is not None else BuildingMetricsSnapshot()

    class _FakeBM:
        async def snapshot(self, _bid, namespace=None):
            return _snap

    monkeypatch.setattr(bmmod, "get_building_metrics", lambda: _FakeBM())

    # 4. Ontology graph resolver — miss by default (no amenity triples).
    class _FakeResolver:
        async def resolve(self, _q):
            return facts or []

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _FakeResolver())

    # 5. Document KB — miss by default (no policy/manual chunks).
    async def _fake_docs(_q, _bid, top_k: int = 3, only_document: str = "", stats=None):
        # `stats` is CAVEAT-226's out-parameter: the real search reports how many candidates
        # the retrieval floor suppressed, so a threshold change can name itself in the
        # evidence record. The double accepts it and leaves it empty -- these tests are about
        # source precedence, not about the floor.
        return docs or []

    monkeypatch.setattr(cap, "_search_documents", _fake_docs)


# ── One source populated at a time — each must answer with kb=None ───────────


async def test_metrics_source_fires_without_capability_yaml(monkeypatch):
    """Count/area question → live_metrics, even though the building has no KB."""
    _bare_building(
        monkeypatch,
        snapshot=BuildingMetricsSnapshot(total_points=533, total_sensors=326, zone_count=108),
    )
    out = await cap.CapabilityAgent().answer(_state("how many sensors are there?"))
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "live_metrics"
    assert res["success"] is True
    assert "326" in res["response"]
    assert _BARE_NAME in res["response"]  # name from building.yaml, not the KB


async def test_graph_amenity_source_fires_without_capability_yaml(monkeypatch):
    """Amenity question → capability_graph (ontology triples), with kb=None."""
    _bare_building(
        monkeypatch,
        facts=[_FakeFact("lift", "There is 1 passenger lift serving all floors.")],
    )
    out = await cap.CapabilityAgent().answer(_state("is there a lift?"))
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "capability_graph"
    assert res["success"] is True
    assert "passenger lift" in res["response"]
    assert _BARE_NAME in res["response"]


async def test_document_source_fires_without_capability_yaml(monkeypatch):
    """Policy/manual question → document_kb (documents_<bldg>), with kb=None.
    This is the exact BUG-078 scenario (wifi policy) reduced to a unit test."""
    _bare_building(
        monkeypatch,
        docs=[{"doc_name": "wifi_policy", "text": "Guests use Guest-WiFi; no password."}],
    )
    out = await cap.CapabilityAgent().answer(_state("what is the wifi policy?"))
    res = out.intermediate_results["capability_result"]
    # Either provenance means the document source fired. The lane now COMPOSES an answer
    # from the passage where it can ("document_answered") and falls back to presenting the
    # passage where the composer cannot run ("document_kb") — so which one appears depends
    # on whether a model is reachable, and pinning one made this test pass on a dev box
    # and fail in a parked checkout. What the test is actually for is that documents work
    # as a source without capability.yaml, and both labels say they did.
    assert res["provenance"] in ("document_kb", "document_answered")
    assert res["success"] is True
    # Hyphens are normalised before comparing: the composer once returned "Guest‑WiFi"
    # with a non-breaking hyphen, which is the same value typographically reformatted. The
    # prompt now asks for identifiers verbatim, and the test does not fail on a dash.
    assert "Guest-WiFi" in _ascii_dashes(res["response"])


async def test_all_sources_miss_gives_honest_boundary_not_crash(monkeypatch):
    """Every source misses → honest 'no info' boundary, success (no crash, no fabrication).
    This is the ONLY path to the boundary message — reachable only when all sources miss."""
    _bare_building(monkeypatch)  # all sources default to a miss
    out = await cap.CapabilityAgent().answer(_state("is there a rooftop helipad?"))
    res = out.intermediate_results["capability_result"]
    assert res["success"] is True
    assert res["provenance"] == "no_match"
    assert _BARE_NAME in res["response"]  # honest, building-named boundary


# ── The invariant itself: kb=None must not gate later sources ────────────────


async def test_uploaded_document_source_is_not_preempted(monkeypatch):
    """Regression lock (BUG-076/078 + TODO-012): an uploaded-manual match must be
    returned even when metrics and triples both miss. If a future refactor re-adds an
    early boundary return above the document search, this fails."""
    _bare_building(
        monkeypatch,
        docs=[{"doc_name": "fire_safety", "text": "Assemble at the north car park."}],
    )
    out = await cap.CapabilityAgent().answer(_state("where do I go in a fire?"))
    res = out.intermediate_results["capability_result"]
    # Must reach the document source, not short-circuit to the honest boundary.
    #
    # EITHER document label satisfies the invariant, and pinning one made this test
    # provider-dependent. `document_answered` is the path where the model synthesises an
    # answer from the retrieved manual; `document_kb` returns the snippet directly when it
    # does not. Which one runs depends on the model: this asserted `document_kb` and failed
    # the moment MODEL_PROVIDER moved to the hosted 120B, which took the synthesis path
    # instead — a better answer failing a test written around a weaker one.
    #
    # The invariant is that the document source was REACHED. The content assertion below is
    # what actually proves it, and it holds on both paths.
    assert res["provenance"] in ("document_kb", "document_answered"), res["provenance"]
    assert res["provenance"] != "no_match"
    assert "north car park" in res["response"]


# ── a topic that NAMES its document (ontosage:documentRef) ───────────────────


async def test_declared_document_is_read_instead_of_being_searched_for(monkeypatch):
    """When the ontology names the governing document, detail comes from THAT file.

    Otherwise the document is chosen by cosine score against a floor calibrated on
    one corpus and one embedding model — so changing either silently changes which
    document answers which question. The triple settles relevance; similarity is
    left only to order chunks inside a document already known to be right.
    """
    _bare_building(
        monkeypatch,
        facts=[_FakeFact("WiFi and network access", "Guests use Guest-WiFi.", "wifi_policy.md")],
    )
    seen = {}

    async def _scoped_docs(_q, _bid, top_k: int = 3, only_document: str = ""):
        seen["only_document"] = only_document
        return [{"doc_name": "wifi_policy", "text": "Full policy: eduroam covers all floors."}]

    monkeypatch.setattr(cap, "_search_documents", _scoped_docs)

    out = await cap.CapabilityAgent().answer(_state("how do I connect to the wifi?"))
    res = out.intermediate_results["capability_result"]

    assert seen["only_document"] == "wifi_policy.md", "retrieval must be scoped to the named file"
    assert "eduroam covers all floors" in res["response"], "the document detail must be included"
    assert "wifi_policy.md" in res["response"], "the answer must say which document it quoted"
    assert res["provenance"] == "capability_graph"


async def test_a_topic_without_a_document_still_answers_from_triples_alone(monkeypatch):
    """Most topics name no document — the answer must not depend on one existing."""
    _bare_building(monkeypatch, facts=[_FakeFact("lift", "There is 1 passenger lift.")])
    called = {"n": 0}

    async def _never(_q, _bid, top_k: int = 3, only_document: str = ""):
        called["n"] += 1
        return []

    monkeypatch.setattr(cap, "_search_documents", _never)

    out = await cap.CapabilityAgent().answer(_state("is there a lift?"))
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "capability_graph"
    assert "passenger lift" in res["response"]
    assert called["n"] == 0, "no document was declared, so none should be fetched"
