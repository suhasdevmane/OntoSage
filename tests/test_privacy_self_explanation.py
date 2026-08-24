# -*- coding: utf-8 -*-
"""The building explaining how it watches you (V6-T31).

The honest counterpart to enforcement: a system that refuses to explain its own surveillance
is not trustworthy even when its refusals are correct.

The dangerous failure mode is specific and is asserted against below: a transparency lane
that reads live data "just to be accurate" turns *"what do you know about me"* into a
disclosure. Explaining "we count people per room" is transparency; answering "there are 3
people in 2.15 and one is you" is the thing the policy exists to prevent.
"""

from pathlib import Path

import pytest
import yaml

from orchestrator.services.privacy.self_explanation import (
    combination_risk_note,
    explain,
    is_self_explanation_question,
    load_disclosure,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CFG = REPO / "config" / "privacy_disclosure.yaml"
MODULE = REPO / "orchestrator" / "services" / "privacy" / "self_explanation.py"


# ── recognising the question ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "what data do you collect about me",
        "how am I being monitored",
        "what do you know about me",
        "am I being tracked",
        "how long is my data kept",
        "what is the data retention period",
        "is there a camera in this room",
        "how do I challenge the monitoring",
    ],
)
def test_transparency_questions_are_recognised(q):
    assert is_self_explanation_question(q)


@pytest.mark.parametrize(
    "q",
    [
        "where is Dr Smith right now",
        "who was in room 2.15 yesterday",
        "how many people are on floor 3",
        "what is the temperature in room 2.15",
    ],
)
def test_questions_about_people_are_not_transparency_questions(q):
    """These must keep reaching the REFUSAL path.

    Softening a surveillance request into an explanation would be a comfortable-looking way
    to answer it.
    """
    assert not is_self_explanation_question(q)


# ── the disclosure itself ────────────────────────────────────────────────────


def test_disclosure_loads():
    d = load_disclosure()
    assert d.never_collected and d.retention and d.granularity


def test_it_states_granularity_as_well_as_protections():
    """'Anonymous' without 'per room, per minute' understates what a small space reveals."""
    text = explain("what do you know about me")
    assert "Room level" in text
    assert "one person" in text  # the single-occupancy caveat


def test_it_names_what_is_never_collected():
    text = explain("am I being tracked")
    for expected in ("facial recognition", "Bluetooth", "raw audio"):
        assert expected.lower() in text.lower()


def test_retention_periods_are_stated_with_reasons():
    text = explain("how long is my data kept")
    assert "30-90 days" in text
    assert "Not retained" in text or "not retained" in text


def test_the_challenge_route_is_always_offered():
    """A disclosure with no route to object is a notice, not accountability."""
    text = explain("how do I challenge the monitoring")
    assert "challenge" in text.lower()
    assert "data controller" in text.lower() or "data protection officer" in text.lower()


def test_declared_modalities_are_listed_when_supplied():
    text = explain("what do you collect", monitored_modalities=["temperature", "co2"])
    assert "temperature" in text and "co2" in text


def test_no_sensing_list_is_invented_when_none_is_supplied():
    """A building that measures three things discloses three, not a plausible set."""
    text = explain("what do you collect")
    assert "What is measured" not in text


def test_combination_risk_is_explained():
    """Without it, refusing a question whose inputs are each visible looks arbitrary."""
    note = combination_risk_note()
    assert "combination" in note.lower()
    assert "declined" in note.lower() or "policy is applied" in note.lower()


# ── the safety property ──────────────────────────────────────────────────────


def test_the_module_reads_declarations_not_data():
    """The load-bearing property.

    A transparency lane that queries live data to be "accurate" turns an explanation into a
    disclosure. Nothing here may reach a store, a graph or an adapter.
    """
    from scripts.check_building_literals import _prose_lines

    src = MODULE.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for forbidden in ("sparql", "select ", "adapter", "sql", "graphdb", "requests.", "cursor"):
        assert forbidden not in code, f"self-explanation must not reach data ({forbidden})"


def test_a_missing_disclosure_says_nothing_rather_than_reassuring(tmp_path, monkeypatch):
    """Inventing 'we protect your privacy' from an absent file is the worst failure here."""
    import orchestrator.services.privacy.self_explanation as mod

    monkeypatch.setattr(mod, "_PATH", tmp_path / "absent.yaml")
    mod.load_disclosure.cache_clear()
    try:
        text = mod.explain("what do you know about me", building_name="Some Building")
        assert "No privacy disclosure has been published" in text
        assert "protect" not in text.lower()
    finally:
        mod.load_disclosure.cache_clear()


def test_config_cites_its_source():
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    assert "11.1" in cfg["citation"] and "Table 13" in cfg["citation"]


def test_default_config_ships_no_fake_contact_route():
    """A placeholder contact is worse than an honest 'ask your data controller'."""
    cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    assert cfg["governance"]["challenge_route"] == ""
    assert cfg["governance"]["challenge_fallback"].strip()
