# -*- coding: utf-8 -*-
"""CAVEAT-817: the control lane must not read internal point identifiers to the person it is
declining.

"Open the windows on floor 3" and "Turn off the lights in Room 1.06" were declined correctly and
then answered *"the points this building lets me write are: `AHU-F5-SP`, `LIGHTING-3F-SP`,
`VAV-501-SP`"*. The decline stays a decline; what changes is that the list names each point the
way the operator described it, says what a valid request looks like, and accepts that name.

A label comes from the building's own config, then from the graph, and only then from expanding
the identifier where the expansion is certain (``SP`` is a setpoint; ``501`` is NOT "room 5.01").
"""

import pytest

from orchestrator.services import writable_points as wp

pytestmark = pytest.mark.unit

URIS = ["urn:bldgX:VAV-501-SP", "urn:bldgX:LIGHTING-3F-SP", "urn:bldgX:AHU-F5-SP"]
LABELS = {
    "urn:bldgX:VAV-501-SP": "Room 5.01 VAV box setpoint",
    "urn:bldgX:LIGHTING-3F-SP": "Floor 3 lighting scene setpoint",
    "urn:bldgX:AHU-F5-SP": "Floor 5 air handling unit supply-air temperature setpoint",
}


def _points(configured=LABELS, graph=None):
    return wp.build_points(URIS, configured=configured, graph_labels=graph)


# ── labels ──────────────────────────────────────────────────────────────────


def test_an_identifier_is_expanded_only_where_the_expansion_is_certain():
    assert wp.humanise("AHU-F5-SP") == "Air handling unit F5 setpoint"
    assert wp.humanise("LIGHTING-3F-SP") == "LIGHTING 3F setpoint"
    # 501 stays 501: reading it as "room 5.01" would state a location nobody recorded
    assert wp.humanise("VAV-501-SP") == "Variable air volume box 501 setpoint"
    assert "5.01" not in wp.humanise("VAV-501-SP")


def test_the_operators_own_label_outranks_the_graph_which_outranks_the_identifier():
    graph = {"urn:bldgX:AHU-F5-SP": "Plant AHU 5", "urn:bldgX:VAV-501-SP": "From the graph"}
    pts = {p.local: p for p in wp.build_points(URIS, configured={"urn:bldgX:VAV-501-SP": "Mine"}, graph_labels=graph)}
    assert pts["VAV-501-SP"].label == "Mine"  # config first
    assert pts["AHU-F5-SP"].label == "Plant AHU 5"  # then the graph
    assert pts["LIGHTING-3F-SP"].label == "LIGHTING 3F setpoint"  # then the name itself
    assert pts["LIGHTING-3F-SP"].labelled is False


def test_a_configured_label_may_be_keyed_by_the_bare_local_name_too():
    pts = wp.build_points(URIS, configured={"AHU-F5-SP": "Roof plant"})
    assert {p.local: p.label for p in pts}["AHU-F5-SP"] == "Roof plant"


# ── the decline ─────────────────────────────────────────────────────────────


def test_a_fully_labelled_building_shows_no_internal_identifier_at_all():
    text = wp.needs_detail_message(missing="which writable point and the value to set", points=_points())
    for identifier in ("VAV-501-SP", "LIGHTING-3F-SP", "AHU-F5-SP", "urn:"):
        assert identifier not in text, identifier
    assert "Room 5.01 VAV box setpoint" in text
    assert "Floor 3 lighting scene setpoint" in text


def test_the_decline_says_nothing_was_queued_and_that_approval_is_still_required():
    text = wp.needs_detail_message(missing="the value to set", points=_points())
    assert text.startswith("Nothing has been queued")
    assert "the value to set" in text
    assert "facility manager approves" in text


def test_the_decline_shows_what_a_valid_request_looks_like_using_a_real_point():
    text = wp.needs_detail_message(missing="x", points=_points())
    assert "for example: *Set Room 5.01 VAV box setpoint to [value]*" in text
    assert "<" not in text  # a markdown renderer would swallow an angle-bracket placeholder


def test_an_unlabelled_point_keeps_its_identifier_because_that_is_all_there_is():
    text = wp.needs_detail_message(missing="x", points=_points(configured={}))
    assert "Air handling unit F5 setpoint (`AHU-F5-SP`)" in text
    assert "Set VAV-501-SP to [value]" in text  # the example uses a name a request can carry


def test_a_named_thing_that_is_not_writable_is_declined_by_name_and_no_other_point_is_suggested():
    text = wp.needs_detail_message(missing="x", points=_points(), named_device="the windows")
    assert text.startswith("I can't control **the windows**")
    assert "nothing has been queued" in text
    assert "set the windows" not in text.lower()


def test_a_building_with_no_writable_points_says_so_and_lists_nothing():
    text = wp.needs_detail_message(missing="x", points=[])
    assert "no setpoints" in text and "- " not in text


# ── naming a point in a request ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, local",
    [
        ("Set VAV-501-SP to 21", "VAV-501-SP"),  # by identifier, as before
        ("set vav 501 sp to 21", "VAV-501-SP"),
        ("Set Room 5.01 VAV box setpoint to 21", "VAV-501-SP"),  # by the label it was shown as
        ("Set the VAV box in Room 5.01 to 21", "VAV-501-SP"),
        ("Set the lighting scene on floor 3 to 50", "LIGHTING-3F-SP"),
        (
            "Set floor 5 air handling unit supply air temperature to 20",
            "AHU-F5-SP",
        ),
    ],
)
def test_a_request_may_name_a_point_by_identifier_or_by_the_label_it_was_shown_as(question, local):
    match = wp.match_point(question, _points())
    assert match is not None and match.local == local


@pytest.mark.parametrize(
    "question",
    [
        "Open the windows on floor 3.",  # not a writable point
        "Turn off the lights in Room 1.06.",
        "Set the temperature to 21",  # a word that several labels share names no point
        "Turn down the heating on floor 5",
        "Set floor 3 to 50",  # not every identifying word is present
        "",
    ],
)
def test_a_request_that_names_no_writable_point_matches_none(question):
    assert wp.match_point(question, _points()) is None


def test_two_points_matching_equally_is_ambiguous_and_asks_rather_than_guesses():
    pts = wp.build_points(
        ["urn:b:AAA-1-SP", "urn:b:AAA-2-SP"],
        configured={"urn:b:AAA-1-SP": "Floor 2 supply fan setpoint", "urn:b:AAA-2-SP": "Floor 2 supply fan setpoint"},
    )
    assert wp.match_point("Set the floor 2 supply fan to 40", pts) is None


def test_the_queued_target_line_shows_the_label_beside_the_identifier():
    labelled = _points()[0]
    assert wp.queued_target(labelled) == "**Room 5.01 VAV box setpoint** (`VAV-501-SP`)"
    unlabelled = _points(configured={})[0]
    assert wp.queued_target(unlabelled) == "`VAV-501-SP`"


# ── where the labels come from ──────────────────────────────────────────────


def test_labels_are_read_from_the_building_config(tmp_path, monkeypatch):
    cfg = tmp_path / "building.yaml"
    cfg.write_text(
        "actuation:\n  driver: sim\n  points_writable:\n    - urn:bldgX:VAV-501-SP\n"
        "  point_labels:\n    urn:bldgX:VAV-501-SP: Room 5.01 VAV box setpoint\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("shared.config.resolve_building_file", lambda bid, name: cfg)
    assert wp.configured_labels("bldgX") == {"urn:bldgX:VAV-501-SP": "Room 5.01 VAV box setpoint"}


def test_a_building_with_no_labels_block_or_no_file_yields_none_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.config.resolve_building_file", lambda bid, name: None)
    assert wp.configured_labels("bldgX") == {}
    cfg = tmp_path / "building.yaml"
    cfg.write_text("actuation:\n  driver: sim\n", encoding="utf-8")
    monkeypatch.setattr("shared.config.resolve_building_file", lambda bid, name: cfg)
    assert wp.configured_labels("bldgX") == {}


async def test_only_the_points_config_left_unlabelled_are_looked_up_in_the_graph(monkeypatch):
    monkeypatch.setattr(wp, "configured_labels", lambda bid: {"urn:bldgX:VAV-501-SP": "Mine"})
    asked = {}

    async def run_select(query, limit=0):
        asked["query"] = query
        return {"ok": True, "rows": [{"p": "urn:bldgX:AHU-F5-SP", "l": "Plant AHU 5"}]}

    pts = await wp.describe_points(URIS, "bldgX", run_select=run_select)
    labels = {p.local: p.label for p in pts}
    assert labels["VAV-501-SP"] == "Mine" and labels["AHU-F5-SP"] == "Plant AHU 5"
    assert "VAV-501-SP" not in asked["query"]  # already labelled, so not re-asked
    assert asked["query"].lstrip().startswith("PREFIX") and "SELECT" in asked["query"]


async def test_an_unreadable_graph_falls_back_to_the_identifier_never_raises(monkeypatch):
    monkeypatch.setattr(wp, "configured_labels", lambda bid: {})

    async def run_select(query, limit=0):
        raise RuntimeError("graphdb down")

    pts = await wp.describe_points(URIS, "bldgX", run_select=run_select)
    assert all(not p.labelled for p in pts)


# ── through the control agent itself ────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from orchestrator.agents.control_agent import ControlAgent  # noqa: E402
from shared.models import ConversationState, Message  # noqa: E402

BUILDING_URIS = ["urn:bldgX:AHU-F5-SP", "urn:bldgX:LIGHTING-3F-SP", "urn:bldgX:VAV-501-SP"]


async def _ask(question, monkeypatch, labels=LABELS, entities=None, role="facility_manager"):
    async def _no_graph(uris, run_select=None):
        return {}

    monkeypatch.setattr("orchestrator.services.writable_points.configured_labels", lambda bid: labels)
    monkeypatch.setattr("orchestrator.services.writable_points.graph_labels", _no_graph)
    state = ConversationState(conversation_id="c", user_message=question)
    state.messages = [Message(role="user", content=question)]
    state.intermediate_results.update(
        {"user_role": role, "user_id": "fm01", "building_id": "bldgX", "entities": entities or []}
    )
    driver = AsyncMock()
    driver.capabilities = AsyncMock(return_value=list(BUILDING_URIS))
    registry = MagicMock()
    registry.driver_for = MagicMock(return_value=driver)
    store = AsyncMock()
    store.create_pending = AsyncMock(return_value="ab12cd34")
    with patch("orchestrator.agents.control_agent.get_actuation_registry", return_value=registry), patch(
        "orchestrator.agents.control_agent.get_approval_store", return_value=store
    ):
        result = await ControlAgent().execute_command(state)
    return result, store


@pytest.mark.parametrize("question", ["Open the windows on floor 3.", "Turn off the lights in Room 1.06."])
async def test_the_two_demo_declines_show_no_identifier_and_queue_nothing(question, monkeypatch):
    # demo rehearsal run 1 D42 and tail A F37: the two questions that named the identifiers
    result, store = await _ask(question, monkeypatch)
    text = result["message"]
    assert result["status"] == "needs_detail"
    store.create_pending.assert_not_called()
    for identifier in ("AHU-F5-SP", "LIGHTING-3F-SP", "VAV-501-SP", "urn:"):
        assert identifier not in text
    assert "Floor 3 lighting scene setpoint" in text
    assert "for example: *Set" in text  # what a valid request looks like


async def test_a_named_window_is_declined_by_name_with_no_other_point_suggested(monkeypatch):
    result, store = await _ask(
        "Open the windows on floor 3.",
        monkeypatch,
        entities=[{"type": "device", "value": "the windows"}],
    )
    assert "I can't control **the windows**" in result["message"]
    store.create_pending.assert_not_called()


async def test_a_request_repeating_the_label_it_was_shown_is_queued_against_that_point(monkeypatch):
    result, store = await _ask("Set Floor 3 lighting scene setpoint to 50", monkeypatch)
    assert result["status"] == "pending_approval"
    assert store.create_pending.call_args.kwargs["point_uri"] == "urn:bldgX:LIGHTING-3F-SP"
    assert store.create_pending.call_args.kwargs["value"] == "50"
    # the confirmation names the point both ways: the plain label first, the identifier beside it
    assert "**Floor 3 lighting scene setpoint** (`LIGHTING-3F-SP`)" in result["message"]


async def test_the_old_identifier_request_still_works(monkeypatch):
    result, store = await _ask("Set VAV-501-SP to 21", monkeypatch)
    assert result["status"] == "pending_approval"
    assert store.create_pending.call_args.kwargs["point_uri"] == "urn:bldgX:VAV-501-SP"


async def test_a_label_with_no_value_asks_for_the_value_and_queues_nothing(monkeypatch):
    result, store = await _ask("Set Floor 3 lighting scene setpoint", monkeypatch)
    assert result["status"] == "needs_detail" and "the value to set" in result["message"]
    assert "which setpoint" not in result["message"]  # the point WAS named
    store.create_pending.assert_not_called()


async def test_a_role_without_control_permission_is_still_declined_before_any_of_this(monkeypatch):
    result, store = await _ask("Set Floor 3 lighting scene setpoint to 50", monkeypatch, role="occupant")
    assert result["status"] == "denied"
    store.create_pending.assert_not_called()
