"""Admin-console and open-caveat fixes of 2026-11-05 (BUG-1690..1702).

Each test names the defect it pins. They read the shipped files or call the real functions;
none of them needs a running stack.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
APP_JS = REPO / "config-panel" / "html" / "app.js"
INDEX = REPO / "config-panel" / "html" / "index.html"


# ── BUG-1690: the Add capability dialog draws its fields and reads only those ──────────


def test_capability_dialog_reads_no_input_it_does_not_draw():
    """createCapability read #cap-location, #cap-floor, … which no code ever drew."""
    js = APP_JS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    for removed in ("cap-location", "cap-floor", "cap-category", "cap-lay", "cap-answer"):
        assert f'$("{removed}")' not in js, removed
        assert f'id="{removed}"' not in html, removed
    assert "function renderCapFields" in js
    assert "data-cap-field" in js
    assert '$("cap-type").addEventListener("change", renderCapFields)' in js


def test_every_dialog_field_is_a_field_the_api_accepts():
    """The fallback field names must be CapabilityCreate fields, or the server drops them."""
    from orchestrator.main import CapabilityCreate

    js = APP_JS.read_text(encoding="utf-8")
    block = js.split("const CAP_FIELD_FALLBACK = [", 1)[1].split("];", 1)[0]
    names = re.findall(r'field: "([a-z_]+)"', block)
    assert names, "fallback list not found"
    accepted = set(CapabilityCreate.model_fields)
    assert not set(names) - accepted, set(names) - accepted


@pytest.mark.asyncio
async def test_schema_form_fields_map_to_accepted_api_fields():
    """Every field the schema-driven form can draw is one CapabilityCreate accepts."""
    from orchestrator.main import CapabilityCreate
    from orchestrator.services import capability_admin

    accepted = set(CapabilityCreate.model_fields)
    assert set(capability_admin._PROP_FIELD.values()) <= accepted


# ── BUG-1699: the AI tab knows the hosted gateway ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_config_offers_the_hosted_provider_settings_accepts():
    from orchestrator.main import get_ai_config

    resp = await get_ai_config(user=SimpleNamespace(role="admin"))
    data = resp.data
    assert "hosted" in data["providers"]
    assert {"hosted_llm_base_url", "hosted_llm_model", "hosted_llm_api_key_set"} <= set(data)
    assert isinstance(data["hosted_llm_api_key_set"], bool)  # presence only, never the key


def test_the_console_names_every_provider_it_can_be_given():
    js = APP_JS.read_text(encoding="utf-8")
    labels = js.split("const PROVIDER_LABELS = {", 1)[1].split("}", 1)[0]
    for p in ("local", "hosted", "cloud", "openai"):
        assert f"{p}:" in labels, p
    # The old ternary called everything that was not local or cloud "OpenAI".
    assert ': "OpenAI");' not in js


# ── BUG-1694: PDFs are indexed, and the reindex job calls a method that exists ──────────


def test_pdf_text_is_extracted(tmp_path):
    fitz = pytest.importorskip("fitz")
    from orchestrator.services import document_indexer as di

    pdf = tmp_path / "wifi_policy.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Guest wifi passwords change every Monday.")
    doc.save(str(pdf))
    doc.close()
    assert ".pdf" in di._SUPPORTED_EXTENSIONS
    text = di._read_document(pdf)
    assert text and "Guest wifi passwords change every Monday" in text


def test_a_pdf_with_no_text_layer_is_reported_not_indexed(tmp_path):
    fitz = pytest.importorskip("fitz")
    from orchestrator.services import document_indexer as di

    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page: what a scan without OCR looks like to a text extractor
    doc.save(str(pdf))
    doc.close()
    assert di._read_document(pdf) is None


# ── BUG-1700: no directory listings, exports carry an unguessable token ──────────────────


def test_the_file_server_lists_nothing_and_serves_only_floor_plan_pdfs_from_input():
    raw = (REPO / "config" / "nginx-file-server.conf").read_text(encoding="utf-8")
    conf = " ; ".join(ln.split("#", 1)[0] for ln in raw.splitlines())  # directives only
    assert "autoindex on" not in conf
    assert "autoindex off" in conf
    fp = [ln for ln in conf.splitlines() if "location" in ln and "/floor-plans/" in ln]
    assert fp and all(".pdf" in ln or ".png" in ln for ln in fp), fp
    assert "return 404" in conf


@pytest.mark.asyncio
async def test_an_export_file_name_carries_a_random_token(tmp_path, monkeypatch):
    from orchestrator.agents.data_export_agent import DataExportAgent
    from shared.config import settings

    monkeypatch.setattr(settings, "EXPORTS_DIR", str(tmp_path))
    agent = DataExportAgent()
    a = await agent.export(data=[{"t": 1}], label="co2 readings/room 2.01", fmt="csv")
    b = await agent.export(data=[{"t": 1}], label="co2 readings/room 2.01", fmt="csv")
    assert a["filename"] != b["filename"]
    assert re.fullmatch(r"[A-Za-z0-9_.-]+_\d{8}_\d{6}_[0-9a-f]{16}\.csv", a["filename"]), a[
        "filename"
    ]


# ── CAVEAT-1701: a graph edit retires every graph-derived cache ─────────────────────────


@pytest.mark.asyncio
async def test_a_graph_change_clears_the_derived_caches(monkeypatch):
    import orchestrator.main as m

    deleted: List[str] = []

    class _Client:
        async def scan_iter(self, match: str, count: int = 0):
            for key in (f"{match[:-1]}one", f"{match[:-1]}two"):
                yield key

        async def delete(self, key: str):
            deleted.append(key)

    monkeypatch.setattr(m, "redis_manager", SimpleNamespace(client=_Client()))

    async def _no_flush():
        return None

    monkeypatch.setattr(m, "_flush_datasource_cache", _no_flush)
    cleared = await m._after_graph_change("")
    for prefix in ("cache:sparql", "cache:intent:", "cqir_compile:"):
        assert any(k.startswith(prefix) for k in deleted), prefix
    assert cleared["redis_keys"] == 6
    assert "concept_map" in cleared


# ── CAVEAT-1697: settings that did nothing ──────────────────────────────────────────────


def test_the_floor_plan_watcher_opt_out_is_a_real_setting():
    from shared.config import Settings

    assert "FLOOR_PLAN_WATCHER" in Settings.model_fields
    assert Settings.model_fields["FLOOR_PLAN_WATCHER"].annotation is bool


# ── BUG-1699: compose passes what .env says ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "compose",
    ["docker-compose.bldg2.yml", "docker-compose.bldg3.yml", "docker-compose.bldgtest.yml"],
)
def test_compose_honours_env_and_defaults_safely(compose):
    text = (REPO / compose).read_text(encoding="utf-8")
    assert "SECRET_KEY=${ONTOSAGE_SECRET_KEY:-${SECRET_KEY:-" in text
    # The fallback must be the default STRICT_SECRETS refuses, not a string it does not know.
    assert "change-me-in-production-use-32-random-bytes}}" in text
    assert "RESPONSE_CACHE_FUZZY=${RESPONSE_CACHE_FUZZY:-false}" in text
    assert "EMBEDDING_MODEL_LOCAL=${EMBEDDING_MODEL_LOCAL:-BAAI/bge-large-en-v1.5}" in text


def test_fuzzy_matching_would_serve_an_opposite_question():
    """Why the fuzzy cache is off by default: these pairs clear its 0.85 threshold."""
    from orchestrator.services.response_cache import salient_ids, trigram_similarity

    pairs = [
        (
            "which meeting rooms on floor 2 are occupied right now",
            "which meeting rooms on floor 2 are unoccupied right now",
        ),
        (
            "list the sensors that are online on the third floor of the building",
            "list the sensors that are offline on the third floor of the building",
        ),
    ]
    for a, b in pairs:
        assert salient_ids(a) == salient_ids(b)  # the id guard cannot tell them apart
        assert trigram_similarity(a, b) >= 0.85


# ── BUG-1696: the place a reporter gives after filing reaches the report ────────────────


def _state(*turns: tuple) -> Any:
    from shared.models import ConversationState, Message

    return ConversationState(
        conversation_id="t",
        user_message=turns[-1][1],
        messages=[Message(role=r, content=c) for r, c in turns],
    )


_ASKED = (
    "Your maintenance report has been logged as **REP-A1B2C3**.\n\n**One thing missing:** "
    "Which room, floor or piece of equipment is affected? Reply with the room, floor or "
    "equipment and I'll add it to this report."
)


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("room 2.01", ("REP-A1B2C3", "room 2.01")),
        ("It's in 3.15", ("REP-A1B2C3", "3.15")),
        ("what is the CO2 in room 2.01?", None),  # a new question that names a place
        ("show me floor 2", None),
        ("thanks", None),
    ],
)
def test_a_location_reply_is_recognised_only_after_the_prompt(reply, expected):
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    state = _state(("user", "the light is broken"), ("assistant", _ASKED), ("user", reply))
    assert W._pending_location_reply(state) == expected


def test_no_prompt_no_capture():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    state = _state(("user", "hi"), ("assistant", "Hello."), ("user", "room 2.01"))
    assert W._pending_location_reply(state) is None


@pytest.mark.asyncio
async def test_add_location_is_scoped_to_the_askers_placeless_report(monkeypatch):
    from orchestrator.services.report_intake_service import ReportIntakeService

    calls: List[tuple] = []

    class _Conn:
        async def execute(self, sql, *params):
            calls.append((sql, params))
            return "UPDATE 1"

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    pg = SimpleNamespace(pool=SimpleNamespace(acquire=lambda: _Acquire()))
    svc = ReportIntakeService(pg)

    async def _no_space(_text):
        return None

    monkeypatch.setattr(svc, "_resolve_space", _no_space)
    res = await svc.add_location("rep-a1b2c3", "room 2.01", reporter_id="occupant01")
    assert res["success"] and res["report_id"] == "REP-A1B2C3"
    sql, params = calls[0]
    assert "location IS NULL OR location = ''" in sql  # never overwrites a recorded place
    assert "reporter_id" in sql and "occupant01" in params  # never someone else's report


def test_the_dialogue_node_and_router_honour_the_reply():
    src = (REPO / "orchestrator" / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    assert "self._pending_location_reply(state)" in src
    assert '"report_location_reply"' in src
    assert 'state.intermediate_results.pop("report_add_location", None)' in src


# ── CAVEAT-1702: the visualization node publishes the key its readers use ─────────────


def test_a_drawn_chart_is_published_as_visualization_path():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    state = _state(("user", "plot it"))
    W._publish_chart_path(state, {"success": True, "media": [{"type": "image", "url": "/s/a.png"}]})
    assert state.intermediate_results["visualization_path"] == "/s/a.png"

    state = _state(("user", "plot it"))
    W._publish_chart_path(state, {"success": False, "skipped": "no_data"})
    assert "visualization_path" not in state.intermediate_results


# ── BUG-1692: the headline is not said twice ────────────────────────────────────────────

_TREND_LIVE = (
    "**The highest temperature recorded in Air Temperature Sensor 2.01 during the last 24 hours "
    "was 23.7 °C at 13:00.**  \n"
    "The lowest temperature observed was 21.1 °C at 01:00, giving a spread of 2.6 °C.  \n"
    "Across the window, the mean temperature fell from 22.0 °C to 21.8 °C, a decrease of 0.2 °C.  \n"
    "The trend shows a gradual cooling in the early morning hours and a rise in the afternoon, "
    "with the peak at 13:00.  \n"
    "The highest temperature recorded was 23.7 °C.\n\n"
    "---\n**You might also ask:** Detect anomalies in this trend?"
)


def test_a_closing_sentence_that_repeats_the_headline_is_dropped():
    from orchestrator.services.narration_validators import validate_narration

    res = validate_narration("Show me the temperature trend in room 2.01", _TREND_LIVE, "trend")
    assert "The highest temperature recorded was 23.7 °C." not in res.text
    assert res.text.startswith("**The highest temperature recorded")
    assert "gradual cooling" in res.text and "You might also ask" in res.text
    assert any(c.validator == "restated_headline" for c in res.changes)


def test_an_identical_opening_and_closing_sentence_keeps_the_opening():
    from orchestrator.services.narration_validators import validate_narration

    head = "The temperature increased by 0.264 C (+1.2 %) over the last 24 hours."
    text = f"**{head}**\n\nIt rose most in the afternoon. The overnight minimum was 21.1 C. {head}"
    out = validate_narration("trend", text, "trend").text
    assert out.count(head) == 1 and out.startswith(f"**{head}**")


def test_a_closing_sentence_with_a_new_figure_is_kept():
    from orchestrator.services.narration_validators import validate_narration

    text = (
        "**The highest temperature recorded was 23.7 C at 13:00.**\n\n"
        "The lowest was 21.1 C. The trend was flat overnight. "
        "The highest temperature recorded was 23.7 C, 1.4 C above yesterday's."
    )
    assert validate_narration("trend", text, "trend").text == text


# ── BUG-1691: an inventory answer does not wait for a slow freshness scan ──────────────


@pytest.mark.asyncio
async def test_a_slow_freshness_scan_does_not_hold_the_answer(monkeypatch):
    import asyncio

    from orchestrator.services import building_metrics as bm

    async def _slow_scan(window_hours):
        await asyncio.sleep(0.3)
        return {"store_a": {"u1", "u2"}, "store_b": {"u3"}}

    monkeypatch.setattr(bm, "reporting_uuids_by_store", _slow_scan)
    monkeypatch.setattr(bm, "_REPORTING_WAIT_S", 0.05)
    monkeypatch.setattr(bm, "_FRESH_CACHE", {})
    monkeypatch.setattr(bm, "_FRESH_INFLIGHT", {})

    assert await bm._default_reporting_provider(24) is None  # answered without the figure
    await asyncio.sleep(0.4)  # the scan was not cancelled; it finishes and is cached
    assert await bm._default_reporting_provider(24) == 3


@pytest.mark.asyncio
async def test_stores_are_probed_concurrently(monkeypatch, tmp_path):
    import asyncio
    import json
    import time

    from orchestrator.services import building_metrics as bm
    from orchestrator.services.adapters import registry as reg
    from shared.config import settings

    smap = {f"s{i}": {"uuid": f"u{i}", "storage": f"store{i}"} for i in range(8)}
    path = tmp_path / "sensor_map.json"
    path.write_text(json.dumps(smap), encoding="utf-8")
    monkeypatch.setattr(settings, "SENSOR_MAP_PATH", str(path))

    class _Adapter:
        table = "t"

        def __init__(self, key):
            self.key = key

        async def execute_query(self, sql):
            await asyncio.sleep(0.2)
            return SimpleNamespace(success=True, data=[{"uuid": "u" + self.key[5:]}])

    fake = SimpleNamespace(is_available=True, get=lambda k: _Adapter(k))
    monkeypatch.setattr(reg, "adapter_registry", fake)
    t0 = time.monotonic()
    by_store = await bm.reporting_uuids_by_store(24)
    elapsed = time.monotonic() - t0
    assert len(by_store) == 8
    assert elapsed < 1.0, elapsed  # 8 x 0.2 s one after another would be 1.6 s


# ── BUG-1693: the evidence panel describes the source it had ────────────────────────────


def test_built_in_systems_are_not_called_sensors():
    from orchestrator.services.evidence.assemble import _kind_for_store_key
    from orchestrator.services.evidence.precedence import tier_for_kind

    assert _kind_for_store_key("ontology") == "building_model"
    assert _kind_for_store_key("capability_graph") == "building_model"
    assert _kind_for_store_key("live_metrics") == "building_model"
    assert _kind_for_store_key("analytics") == "computation"
    assert _kind_for_store_key("documents") == "document"
    assert _kind_for_store_key("store:occupancy_data") == "sensor"
    # The model is NOT authoritative: the permission guard reads "authoritative" as settling
    # whether something is booked or allowed, which the graph does not record.
    assert tier_for_kind("building_model") == "model"
    assert tier_for_kind("floor_plan") == "model"


def test_a_floor_plan_answer_is_not_said_to_be_read_from_an_instrument():
    from orchestrator.services.answer_provenance import render

    rec = {
        "status": "observed",
        "operation": "observation",
        "sources": [{"source_id": "floor_plan", "label": "Floor plan", "kind": "floor_plan"}],
    }
    text = render(rec)
    assert "read from an instrument" not in text
    assert "floor plan or model" in text


@pytest.mark.parametrize("lane", ["## Floor 2\n![plan](x.png)", {"answer": "area 120 m2"}])
def test_a_floor_plan_turn_records_the_plan_as_its_source(lane):
    from orchestrator.services.evidence.assemble import _sources_from

    key = "floor_plan_result" if isinstance(lane, str) else "spatial_result"
    sources = _sources_from({key: lane})
    assert [(s.source_id, s.kind) for s in sources] == [("floor_plan", "floor_plan")]


def test_a_filed_report_is_described_as_a_persons_account():
    from orchestrator.services.answer_provenance import render
    from orchestrator.services.provenance import readable_source_label

    assert readable_source_label("REP-701F38") == "Report REP-701F38"
    rec = {
        "status": "inferred",
        "operation": "authoritative_lookup",
        "sources": [{"source_id": "REP-701F38", "kind": "human_report"}],
    }
    text = render(rec)
    assert "a person's account" in text and "reasoned from observations" not in text
    assert "Report REP-701F38" in text


def test_the_location_prompt_is_not_repeated_and_both_prompts_are_honoured():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    service_only = (
        "Your complaint has been logged as **REP-ABC123**.\n\n📍 I couldn't tell **where** this "
        "is. If you reply with the room, floor or area, I'll attach it."
    )
    state = _state(("user", "it is too hot"), ("assistant", service_only), ("user", "floor 3"))
    assert W._pending_location_reply(state) == ("REP-ABC123", "floor 3")
    src = (REPO / "orchestrator" / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    assert "msg = re.sub(r\"\\n*📍 I couldn't tell \\*\\*where\\*\\* this is" in src


def test_a_downgraded_reading_is_not_said_to_be_unmeasured():
    from orchestrator.services.answer_provenance import render

    rec = {
        "status": "inferred",
        "operation": "observation",
        "gates_applied": ["freshness"],
        "sources": [{"source_id": "u1", "label": "Sensor reading", "kind": "sensor"}],
    }
    text = render(rec)
    assert "not itself measured" not in text
    assert "would not let stand as observed" in text


def test_a_graph_only_answer_is_led_by_the_building_model():
    from orchestrator.services.answer_provenance import render

    text = render(
        {"status": "observed", "operation": "authoritative_lookup", "source_tier": "model"}
    )
    assert "Kind of source that led:** the building model" in text


# ── Where is THE named room: wayfinding, not a superlative (found live 2026-11-05) ──────


@pytest.mark.parametrize(
    "question,superlative",
    [
        ("Where is the prayer room?", False),
        ("Where is the guest room?", False),
        ("where is the meeting room 2.14", False),
        ("Where's the coolest place to work today?", True),
        ("Where is the nearest quiet room?", True),
        ("Where is a quiet room?", True),
        ("Where's a quiet place to sit right now?", True),
    ],
)
def test_a_named_room_is_not_a_superlative(question, superlative):
    from orchestrator.services.routing_contract import DELIBERATE_RE

    assert bool(DELIBERATE_RE.search(question)) is superlative


# ── BUG-1698: schema declarations ──────────────────────────────────────────────────────


def test_schema_declares_what_buildings_use_and_gives_about_equipment_one_domain():
    rdflib = pytest.importorskip("rdflib")
    from rdflib.namespace import OWL, RDF, RDFS

    g = rdflib.Graph()
    g.parse(str(REPO / "ontology" / "ontosage_schema.ttl"), format="turtle")
    O = rdflib.Namespace("http://ontosage.org/capabilities#")
    assert (O.Record, RDF.type, OWL.Class) in g
    assert (O.AccessibleToilet, RDF.type, OWL.Class) in g
    for prop in ("appliesTo", "configurationOf", "configLocation", "meterServes"):
        assert (O[prop], RDF.type, OWL.ObjectProperty) in g, prop
    assert len(list(g.objects(O.aboutEquipment, RDFS.domain))) == 1
    text = (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")
    assert "#  Version : 2.1.0" in text and 'owl:versionInfo "2.1.0"' in text
