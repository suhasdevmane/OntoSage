# -*- coding: utf-8 -*-
"""V5-T05: compliance-register generator — frozen-date unit tests."""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import rdflib
import yaml

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_NS = "http://ontosage.org/capabilities#"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "gen_compliance", _REPO / "scripts" / "generate_compliance_register.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rendered():
    mod = _load_module()
    template = yaml.safe_load(
        (_REPO / "config" / "compliance_register_template.yaml").read_text(encoding="utf-8")
    )
    building = {"id": "testbldg", "namespace": "http://example.org/testbldg#", "prefix": "bldg"}
    now = datetime(2026, 8, 15, 12, 0, 0)
    ttl = mod.render(building, template, now)
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return ttl, g, now, template


def test_all_items_have_current_and_history(rendered):
    ttl, g, now, template = rendered
    checks = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(_NS + "ComplianceCheck")))
    n_items = len(template["items"])
    assert len(checks) > n_items  # history + current per item
    currents = [c for c in checks if str(c).endswith("_current")]
    assert len(currents) == n_items


def test_forced_overdue_items_are_overdue(rendered):
    ttl, g, now, template = rendered
    due = rdflib.URIRef(_NS + "dueDate")
    completed = rdflib.URIRef(_NS + "completedDate")
    for iid in template["dev_overdue_items"]:
        node = rdflib.URIRef(f"http://example.org/testbldg#compliance_{iid}_current")
        due_val = datetime.strptime(str(g.value(node, due))[:19], "%Y-%m-%dT%H:%M:%S")
        assert due_val < now, f"{iid} current check should be overdue"
        assert g.value(node, completed) is None


def test_history_cycles_are_completed_and_dated(rendered):
    ttl, g, now, _ = rendered
    status = rdflib.URIRef(_NS + "recordStatus")
    completed = rdflib.URIRef(_NS + "completedDate")
    done = [s for s, o in g.subject_objects(status) if str(o) == "done"]
    assert done and all(g.value(s, completed) is not None for s in done)


def test_every_instance_declares_simulated(rendered):
    ttl, g, _, _ = rendered
    sim = rdflib.URIRef(_NS + "isSimulated")
    checks = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(_NS + "ComplianceCheck")))
    assert all((c, sim, rdflib.Literal(True)) in g for c in checks)


def test_deterministic_output(rendered):
    ttl, _, now, template = rendered
    mod = _load_module()
    building = {"id": "testbldg", "namespace": "http://example.org/testbldg#", "prefix": "bldg"}
    again = mod.render(building, template, now)
    assert again == ttl


def test_overdue_sparql_shape(rendered):
    """The exact query the compliance lane will run returns the forced items."""
    _, g, now, template = rendered
    q = f"""
    PREFIX ontosage: <{_NS}>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?c WHERE {{
        ?c a ontosage:ComplianceCheck ; ontosage:dueDate ?due ; ontosage:recordStatus "open" .
        FILTER NOT EXISTS {{ ?c ontosage:completedDate ?any }}
        FILTER (?due < "{now.strftime('%Y-%m-%dT%H:%M:%S')}"^^xsd:dateTime)
    }}"""
    overdue = {str(r[0]).rsplit("_current", 1)[0].rsplit("#compliance_", 1)[-1] for r in g.query(q)}
    assert overdue == set(template["dev_overdue_items"])
