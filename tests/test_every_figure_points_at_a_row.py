# -*- coding: utf-8 -*-
"""Claim binding (A2): the prose may say only what the fetched rows support.

**What this file is defending.** From the hand read of 147 live answers on 2026-09-17, the
largest defect family (C7, 17 rows) is prose that carries the right evidence and an invented
verdict — *"Each of the 20 records contains a mapped opening and a granted role, so none lack
the basic evidence of ownership, purpose"*, where the question asked which were orphaned and
no field records ownership or purpose at all. The countermeasure that shipped first was a
line in a prompt. This module is the structural one, and these are its pins.

**The tests are written in the direction the mandate points.** A binder that strips a correct
figure is worse than the defect it was built for, so the false-positive cases here
(``test_a_correctly_quoted_*``) are load-bearing in a way the detection cases are not: each
one is a real answer shape from the recorded bank that an earlier draft of the binder
condemned. They are kept as regression pins, with the measurement that found them named.
"""

from __future__ import annotations

import pytest

from orchestrator.services import claim_binder as cb

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_figures_from_a_previous_test():
    """Start every case with an empty computed-figure record.

    Outside an HTTP request there is no ``TracingMiddleware`` to give each turn its own trace
    id, so a whole pytest session shares one. Without this, a case that renders a metrics
    block leaves its counts where the NEXT case's binder finds them — and
    ``test_a_turn_with_no_recorded_evidence_condemns_nothing`` failed exactly that way, in a
    full run and not in isolation.
    """
    from orchestrator.services.evidence import computed

    computed.reset()
    yield
    computed.reset()


def _rows(rows):
    """A lane result in the shape the sparql/register lanes hand up."""
    return {"sparql_result": {"success": True, "results": {"data": rows}}}


# ── the mode flag ────────────────────────────────────────────────────────────


def test_the_documented_default_is_record_only():
    """Flag absent means RECORD: count and log, change nothing. The demo runs on this."""
    assert cb.current_mode({}) == cb.MODE_RECORD


def test_the_flag_turns_enforcement_on_and_a_typo_does_not_turn_it_off():
    assert cb.current_mode({"CLAIM_BINDING_ENABLED": "true"}) == cb.MODE_ENFORCE
    assert cb.current_mode({"CLAIM_BINDING_MODE": "enforce"}) == cb.MODE_ENFORCE
    assert cb.current_mode({"CLAIM_BINDING_MODE": "off"}) == cb.MODE_OFF
    # a typo must fall back to the measurement, never to silence
    assert cb.current_mode({"CLAIM_BINDING_MODE": "enfroce"}) == cb.MODE_RECORD


def test_record_mode_never_changes_the_answer():
    answer = "There are 9,999 sensors on floor 12."
    text, rec = cb.run(answer, _rows([{"label": "a"}]), mode=cb.MODE_RECORD)
    assert text == answer
    assert rec["counts"]["unbound"] >= 1, "it must still MEASURE what it did not change"
    assert rec["changed"] is False


# ── the claim grammar ────────────────────────────────────────────────────────


def test_a_number_carries_its_unit_and_its_subject():
    (claim,) = [c for c in cb.extract_claims("The mean was 21.5 °C.") if c.kind == "numeric"]
    assert claim.value == 21.5
    assert claim.unit == "°C"
    assert claim.decimals == 1


def test_a_date_is_one_claim_and_not_three_numbers():
    claims = [c for c in cb.extract_claims("Due on 18 September 2026.") if c.kind == "numeric"]
    assert len(claims) == 1
    assert claims[0].iso_date == "2026-09-18"


def test_a_non_breaking_hyphen_does_not_shatter_a_date():
    """Measured on the recorded bank: the model writes U+2011, and "2026-06-16" arrived as
    three separate unbound claims (2026, 06, 16) until the dashes were normalised."""
    claims = [c for c in cb.extract_claims("Proven on 2026‑06‑16.") if c.kind == "numeric"]
    assert [c.iso_date for c in claims] == ["2026-06-16"]


def test_an_equipment_tag_is_a_name_not_four_figures():
    """ "MCC-0-way-3 (LI-AHU-00)" is one identifier. An earlier draft read four claims out of
    it and reported an asset's own name as unevidenced arithmetic."""
    claims = cb.extract_claims("Isolated at MCC-0-way-3 (LI-AHU-00) per AEP-001.")
    assert [c for c in claims if c.kind == "numeric"] == []


def test_the_follow_up_trailer_is_not_the_answer():
    """The response node appends its own suggestions. "Which of these are on floor 3?" is a
    QUESTION; counting it as a claim made the binder measure its own scaffolding."""
    answer = "12 records.\n\n---\n**You might also ask:** Which of these are on floor 3?"
    nums = [c for c in cb.extract_claims(answer) if c.kind == "numeric"]
    assert [c.raw for c in nums] == ["12"]


def test_a_clock_time_is_one_claim():
    claims = [c for c in cb.extract_claims("Open until 22:00.") if c.kind == "numeric"]
    assert [c.raw for c in claims] == ["22:00"]
    assert claims[0].unit == "time"


# ── BOUND ────────────────────────────────────────────────────────────────────


def test_a_value_in_a_row_binds():
    rep = cb.analyse("The reading was 21.5 °C.", _rows([{"value": 21.5}]), mode=cb.MODE_RECORD)
    (c,) = [c for c in rep.claims if c.kind == "numeric"]
    assert c.binding == "bound"
    assert "sparql_result" in c.evidence_path


def test_rounding_is_judged_at_the_precision_the_claim_was_written_to():
    """ "21.5" binds to a stored 21.4979 and not to a stored 22.1. The tolerance is the
    claim's own decimal places — stated, not hidden in a comparison."""
    assert cb.analyse("It was 21.5 °C.", _rows([{"v": 21.4979}])).claims[0].binding == "bound"
    assert cb.analyse("It was 21.5 °C.", _rows([{"v": 22.1}])).claims[0].binding == "unbound"


def test_a_figure_inside_a_text_cell_still_counts_as_evidence():
    """``valueBand: "100k-250k"`` carries 100 and 250. Measured: without this tier the binder
    called a correctly quoted cost band an invention eight times in one answer."""
    rep = cb.analyse(
        "Replacement sits in the 100k to 250k band.",
        _rows([{"valueBand": "100k-250k"}]),
    )
    assert all(c.binding == "bound" for c in rep.claims if c.kind == "numeric")


def test_a_short_number_does_not_bind_to_the_digits_of_a_timestamp():
    """THE guard on the guard. A substring test bound "3" against "2026-08-03T11:31:24" and
    declared it evidenced. A check that accepts any digit occurring anywhere is not a check."""
    rep = cb.analyse("There are 3 outstanding.", _rows([{"dueDate": "2026-08-03T11:31:24"}]))
    (c,) = [c for c in rep.claims if c.kind == "numeric"]
    assert c.binding == "unbound"


def test_an_opening_hour_inside_a_compound_cell_binds():
    """ "Mon-Sun 07:00-22:00" evidences both 07:00 and 22:00. The strict boundary rejected
    every opening hour in the workspace register and reported a correct answer as invented."""
    rep = cb.analyse("It is open 07:00 to 22:00.", _rows([{"openingHours": "Mon-Sun 07:00-22:00"}]))
    assert all(c.binding == "bound" for c in rep.claims if c.kind == "numeric")


# ── DERIVED ──────────────────────────────────────────────────────────────────


def test_a_row_count_is_derived_and_says_so():
    rep = cb.analyse("The records show 3 assets.", _rows([{"a": "x"}, {"a": "y"}, {"a": "z"}]))
    (c,) = [c for c in rep.claims if c.kind == "numeric"]
    assert c.binding == "derived"
    assert c.operation == "count"
    assert "rows" in c.reason or "sparql_result" in c.reason


def test_a_group_count_is_derived_from_the_field_it_groups_on():
    """ "72 completed (done) records" out of 82 is a count over a group. Until this existed,
    every correct group count in a register answer read as an invention."""
    rows = [{"recordStatus": "done"}] * 4 + [{"recordStatus": "open"}] * 2
    rep = cb.analyse("4 records are done and 2 are open.", _rows(rows))
    nums = [c for c in rep.claims if c.kind == "numeric"]
    assert [c.binding for c in nums] == ["derived", "derived"]
    assert nums[0].operation == "count_where"
    assert "recordStatus" in nums[0].inputs


def test_a_mean_is_only_derived_when_the_prose_says_it_is_a_mean():
    """Trying every aggregate over every column until one matches would 'explain' an invented
    number about as often as a real one, and the explanation would be a coincidence."""
    rows = [{"temperature": 20.0}, {"temperature": 22.0}]
    said = cb.analyse("The average temperature is 21.0 °C.", _rows(rows))
    assert said.claims[0].binding == "derived" and said.claims[0].operation == "mean"
    unsaid = cb.analyse("The temperature is 21.0 °C.", _rows(rows))
    assert unsaid.claims[0].binding == "unbound"


def test_a_derived_figure_names_its_operation_and_its_inputs():
    rows = [{"kwh": 10.0}, {"kwh": 15.0}]
    rep = cb.analyse("The total was 25 kWh.", _rows(rows))
    (c,) = [c for c in rep.claims if c.kind == "numeric"]
    assert c.operation == "sum"
    assert c.inputs and "kwh" in c.inputs[0]
    assert "25" in c.reason or "sum" in c.reason


# ── UNBOUND: the C7 family ───────────────────────────────────────────────────

ORPHANED = (
    "The query results do not show any permission groups that are truly orphaned.\n"
    "Each of the 20 records contains a mapped opening and a granted role, so none lack the "
    "basic evidence of ownership, purpose or access point that would make them orphaned."
)

ORPHAN_ROWS = [
    {"recordId": f"APG-{i:03d}", "controlsOpening": "Main Entrance", "grantedToRole": "staff"}
    for i in range(1, 21)
]


def test_the_worst_recorded_answer_of_2026_09_17_is_caught():
    """The C7 headline. The counts are right (20 rows), the fields are right, and the VERDICT
    is about ownership and purpose — which no fetched field is about."""
    rep = cb.analyse(ORPHANED, _rows(ORPHAN_ROWS))
    unbound = [c for c in rep.claims if c.binding == "unbound"]
    assert unbound, "the invented verdict must not pass"
    assert any(c.kind == "inference" for c in unbound)
    assert any("ownership" in c.reason for c in unbound)
    # and the count itself is correctly recognised, not swept up with the invention
    assert any(c.raw == "20" and c.binding == "derived" for c in rep.claims)


def test_a_property_no_field_records_is_not_evidence():
    """ "Several assets list probable containment features" — nothing records containment."""
    rep = cb.analyse(
        "Every asset has a proven isolation point, so all are protected by containment bunds.",
        _rows([{"isolationPoint": "MCC-0", "recordStatus": "active"}]),
    )
    assert any(c.binding == "unbound" for c in rep.claims)


def test_a_figure_from_nowhere_is_unbound():
    rep = cb.analyse("Consumption reached 4,812 kWh.", _rows([{"kwh": 10.0}]))
    (c,) = [c for c in rep.claims if c.kind == "numeric"]
    assert c.binding == "unbound"
    assert c.reason


# ── the false positives that a binder must never produce ─────────────────────


def test_an_honest_decline_is_not_a_fabrication():
    """The one behaviour this project worked hardest to teach its lanes. An earlier draft
    flagged "the records do not contain any information about vehicle usage" as an
    unsupported universal — punishing exactly the answer that is wanted."""
    rep = cb.analyse(
        "The building's records do not contain any information about vehicle usage.",
        _rows([{"label": "Air Handling Unit"}]),
    )
    assert not [c for c in rep.claims if c.binding == "unbound"]


def test_a_clause_about_something_the_evidence_never_covers_is_out_of_scope_not_false():
    """ "All refer to the building at the university" is about the answer's own framing."""
    rep = cb.analyse(
        "These all refer to the same campus directory listing.",
        _rows([{"label": "Air Handling Unit", "onFloor": "0"}]),
    )
    assert not [c for c in rep.claims if c.binding == "unbound"]


def test_a_turn_with_no_recorded_evidence_condemns_nothing():
    """A document or capability answer's evidence is a passage, not rows. Judging its figures
    against an empty index would strip correct answers wholesale."""
    rep = cb.analyse("The policy allows 3 guests per visitor.", {})
    assert rep.evidence_available is False
    assert {c.binding for c in rep.claims} == {"skipped"}


def test_a_list_marker_is_not_a_claim():
    rep = cb.analyse("1. First item\n2. Second item", _rows([{"a": 1}]))
    assert not [c for c in rep.claims if c.binding == "unbound"]


# ── enforcement ──────────────────────────────────────────────────────────────


def test_enforce_removes_the_sentence_and_says_so():
    answer = "The building holds 7 meters. Consumption reached 4,812 kWh."
    text, rec = cb.run(answer, _rows([{"kwh": 10.0}] * 7), mode=cb.MODE_ENFORCE)
    assert "4,812" not in text
    assert "7 meters" in text, "a bound sentence must survive untouched"
    assert "left out of this answer" in text
    assert rec["changed"] is True
    assert rec["notes"]


def test_enforce_removes_the_whole_sentence_not_just_the_number():
    """An answer with a number cut out of it reads as a fabrication with a hole in it, and the
    surrounding clause is usually the part that was invented."""
    text, _ = cb.run(
        "The mean was 99.9 °C across the floor.", _rows([{"v": 1.0}]), mode=cb.MODE_ENFORCE
    )
    assert "across the floor" not in text


def test_enforce_never_returns_an_empty_answer():
    text, _ = cb.run("It was 4,812 kWh.", _rows([{"v": 1.0}]), mode=cb.MODE_ENFORCE)
    assert text.strip()
    assert "could not" in text or "left out" in text or "not going to state" in text


def test_enforce_caveats_an_unsupported_verdict_rather_than_deleting_it():
    """Asymmetric on purpose. A lexical test is strong enough to FLAG a verdict and not strong
    enough to delete a sentence of prose on its own."""
    text, rec = cb.run(ORPHANED, _rows(ORPHAN_ROWS), mode=cb.MODE_ENFORCE)
    assert "none lack" in text, "the verdict is flagged, not silently deleted"
    assert "unconfirmed" in text


def test_no_user_visible_text_names_how_the_data_was_produced():
    """Standing owner rule. None of this module's wording may leak provenance vocabulary."""
    blob = " ".join(
        [cb._REMOVED_ONE, cb._REMOVED_MANY, cb._CAVEAT_UNIVERSAL, cb._NOTHING_LEFT]
    ).lower()
    for banned in ("simulated", "synthetic", "fake", "dummy", "mock", "placeholder"):
        assert banned not in blob


def test_no_building_literal_lives_in_this_module():
    from pathlib import Path

    src = Path(cb.__file__).read_text(encoding="utf-8").lower()
    for literal in ("abacws", "bldg1", "bldg2", "cardiff", "5.02"):
        assert literal not in src


# ── the report object ────────────────────────────────────────────────────────


def test_every_decision_is_explainable():
    """The mandate: a binder whose verdicts cannot be read back is not reviewable."""
    rep = cb.analyse(ORPHANED, _rows(ORPHAN_ROWS))
    for c in rep.claims:
        assert c.reason, f"no reason recorded for {c.raw!r}"
        assert c.binding in ("bound", "derived", "unbound", "skipped")
        if c.binding == "derived":
            assert c.operation


def test_the_counts_cannot_disagree_with_the_claim_list():
    rep = cb.analyse(ORPHANED, _rows(ORPHAN_ROWS))
    counts = rep.counts()
    assert counts["total"] == len(rep.claims)
    assert (
        counts["bound"] + counts["derived"] + counts["unbound"] + counts["skipped"]
        == counts["total"]
    )


def test_the_record_is_json_serialisable():
    import json

    _, rec = cb.run(ORPHANED, _rows(ORPHAN_ROWS), mode=cb.MODE_RECORD)
    json.loads(json.dumps(rec))


def test_the_binder_never_raises_on_a_hostile_bus():
    for payload in ({"sql_result": None}, {"sparql_result": {"results": "x"}}, {"dossier": 3}):
        text, rec = cb.run("It was 5 °C.", payload)
        assert text == "It was 5 °C."
        assert "counts" in rec or "error" in rec


# ── the wiring ───────────────────────────────────────────────────────────────


def test_it_is_wired_at_the_one_chokepoint_and_before_the_rows_are_dropped():
    """The response node pops `sparql_result`/`sql_result` at the end of the turn. A binder
    that ran after that would bind every figure against nothing and condemn the lot."""
    import inspect

    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    assert "claim_binder" in src
    polish = src.index("polish_answer")
    bind = src.index("claim_binder")
    cleanup = src.index("_bulky_keys")
    assert polish < bind < cleanup
    # It must read the bus off the state, not a local bound in a try block a thousand lines
    # earlier: a NameError there is swallowed by the fail-open handler, and a binder that
    # quietly did nothing looks exactly like a binder that found nothing.
    call = src[bind : src.index("\n", src.index("_bind_claims(", bind))]
    assert "state.intermediate_results" in src[bind : bind + 1200]
    assert "_bind_claims(final_response, _bus)" in call or "_bus" in call
