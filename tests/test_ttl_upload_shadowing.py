# -*- coding: utf-8 -*-
"""A hand-named graph must not shadow a file the boot uploader owns (BUG-250).

input/bldg1_plant_points.ttl was uploaded through the admin API into a graph
named ``abacws#bldg1_plant_points``, to avoid a four-minute restart. On the next
boot ttl_uploader discovered the same FILE — it matches ``bldg1_*.ttl`` — and
loaded it into ``urn:ontosage:ttl:bldg1_plant_points.ttl`` as well. 592 triples
existed twice, and every plant point came back twice through any blank-node
join: the reference fan-out that made CAVEAT-039 a live wrong-answer defect.

The duplicate graph was dropped at the time; the durable half is here. The
trigger is a name collision, and the caller is told which graph to use instead
rather than merely being refused.
"""

from pathlib import Path

import pytest

from orchestrator.services import input_ttl_store as store

pytestmark = pytest.mark.unit


@pytest.fixture()
def fake_input(tmp_path, monkeypatch):
    (tmp_path / "bldg1_plant_points.ttl").write_text("# ttl\n", encoding="utf-8")
    (tmp_path / "bldg1_enhancements.ttl").write_text("# ttl\n", encoding="utf-8")
    monkeypatch.setattr(store, "writable_input_dir", lambda: tmp_path)
    return tmp_path


# ── the graph name that actually caused it ───────────────────────────────────
def test_the_graph_name_from_the_incident_is_detected(fake_input):
    assert store.conflicting_input_file("abacws#bldg1_plant_points") == "bldg1_plant_points.ttl"


@pytest.mark.parametrize(
    "graph_uri",
    [
        "abacws#bldg1_plant_points",
        "http://example.org/graphs/bldg1_plant_points.ttl",
        "urn:ontosage:custom:BLDG1_PLANT_POINTS",  # case is not a defence
    ],
)
def test_every_spelling_of_the_same_file_is_detected(fake_input, graph_uri):
    assert store.conflicting_input_file(graph_uri) == "bldg1_plant_points.ttl"


# ── and the legitimate cases still pass through ──────────────────────────────
def test_the_uploaders_own_graph_is_not_a_conflict(fake_input):
    """urn:ontosage:ttl:<file> IS the file's graph — uploading there updates it."""
    assert store.conflicting_input_file("urn:ontosage:ttl:bldg1_plant_points.ttl") is None


def test_a_genuinely_new_graph_is_allowed(fake_input):
    assert store.conflicting_input_file("urn:ontosage:custom:scratch_policies") is None


def test_an_empty_or_odd_uri_does_not_raise(fake_input):
    assert store.conflicting_input_file("") is None
    assert store.conflicting_input_file("#") is None


def test_no_active_building_is_not_an_error(monkeypatch):
    """The committed tree has no input/ at all; a validator that raises there
    would break the parked state every test run sees."""

    def _boom():
        raise FileNotFoundError("no active building")

    monkeypatch.setattr(store, "writable_input_dir", _boom)
    assert store.conflicting_input_file("abacws#anything") is None


# ── the endpoint refuses, and says which graph to use ────────────────────────
def test_the_upload_endpoint_names_the_graph_to_use_instead():
    """A refusal that does not say what to do instead just moves the problem."""
    src = Path(__file__).resolve().parents[1] / "orchestrator" / "main.py"
    text = src.read_text(encoding="utf-8")
    idx = text.index("clash = conflicting_input_file(body.graph_uri)")
    window = text[idx : idx + 1200]
    assert "graph_uri_for_filename(clash)" in window
    assert "success=False" in window
    # and it must come BEFORE the write
    assert window.index("success=False") < window.index("await upload_ttl(")


# ── and the ones already in the graph are surfaced at boot ──────────────────
@pytest.mark.asyncio
async def test_a_file_in_two_graphs_is_reported(monkeypatch):
    """The admin upload now refuses to create one; this finds the ones that
    already exist. It reports rather than drops — unattended startup is the wrong
    place to decide which copy is the real one."""
    from orchestrator.services import ttl_uploader

    graphs = {
        "urn:ontosage:ttl:bldg1_plant_points.ttl": 592,
        "abacws#bldg1_plant_points": 592,
        "urn:ontosage:ttl:bldg1_enhancements.ttl": 1080,
    }

    async def _fake():
        return graphs

    monkeypatch.setattr(
        "orchestrator.services.ontology_manager.list_named_graphs", _fake, raising=True
    )
    out = await ttl_uploader.audit_shadowed_graphs()
    assert out["ok"]
    assert len(out["shadowed"]) == 1
    found = out["shadowed"][0]
    assert found["file"] == "bldg1_plant_points"
    assert found["canonical"] == "urn:ontosage:ttl:bldg1_plant_points.ttl"
    assert found["duplicates"] == ["abacws#bldg1_plant_points"]


@pytest.mark.asyncio
async def test_a_clean_graph_set_reports_nothing(monkeypatch):
    from orchestrator.services import ttl_uploader

    async def _fake():
        return {
            "urn:ontosage:ttl:bldg1_enhancements.ttl": 1080,
            "urn:ontosage:custom:policies": 12,
        }

    monkeypatch.setattr(
        "orchestrator.services.ontology_manager.list_named_graphs", _fake, raising=True
    )
    assert (await ttl_uploader.audit_shadowed_graphs())["shadowed"] == []


@pytest.mark.asyncio
async def test_two_hand_named_graphs_are_left_alone(monkeypatch):
    """Without a canonical file graph there is nothing to say somebody's two
    graphs are a mistake rather than a deliberate arrangement."""
    from orchestrator.services import ttl_uploader

    async def _fake():
        return {"a#policies": 5, "b#policies": 7}

    monkeypatch.setattr(
        "orchestrator.services.ontology_manager.list_named_graphs", _fake, raising=True
    )
    assert (await ttl_uploader.audit_shadowed_graphs())["shadowed"] == []


@pytest.mark.asyncio
async def test_graphdb_being_down_does_not_break_startup(monkeypatch):
    from orchestrator.services import ttl_uploader

    async def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "orchestrator.services.ontology_manager.list_named_graphs", _boom, raising=True
    )
    out = await ttl_uploader.audit_shadowed_graphs()
    assert out["ok"] is False and out["shadowed"] == []


def test_the_audit_actually_runs_on_every_boot():
    """Five capabilities in this codebase were correct, tested, and had no
    invoker (lessons.md #87). An audit nobody calls is the sixth."""
    import inspect

    from orchestrator.services import ttl_uploader

    src = inspect.getsource(ttl_uploader.run_idempotent_uploads)
    assert "await audit_shadowed_graphs()" in src
