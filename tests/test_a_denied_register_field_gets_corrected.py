# -*- coding: utf-8 -*-
"""W19 (2026-09-18): a narration that denies a term the census found present gets a correction.

38 of 96 weird answers in the 2026-09-18 hand read denied a field or record the register
actually holds — "the register does not record whether a shared desk is officially available"
over rows that do; "no field states how the consequence of a leak is minimised" printed above
the isolation-point column that names it. Six prompt-wording waves asked the model not to do
this and did not stop it, because a prompt is a request. `false_absence_corrections` is a check,
run on the model's OWN finished narration, exactly like the existing `completeness_line` guard.
"""

from orchestrator.services.register_facts import false_absence_corrections


def _rows(*dicts):
    return list(dicts)


def test_denies_a_field_the_register_actually_holds():
    """The AD-058 shape: 'does not contain any drainage information' over an isolation column."""
    rows = _rows(
        {
            "record": "AEP-001",
            "label": "Water supply riser isolation",
            "isolationPoint": "Valve V12, plant room B0",
            "recordStatus": "active",
        },
        {
            "record": "AEP-002",
            "label": "Drainage containment bund",
            "isolationPoint": "Bund drain valve, level -1",
            "recordStatus": "active",
        },
    )
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register records isolation details for the assets that are relevant to "
        "water-supply, containment and discharge. It does **not** contain any drainage "
        "information, nor any field that explicitly states how the consequence of a leak is "
        "minimised."
    )
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Which water-supply, drainage, containment and isolation details minimise the "
        "consequence of leaks, blockages or uncontrolled discharge?",
        register_label="Asset Isolation Register",
    )
    assert out, "expected a correction: 'drainage' appears in row AEP-002's own label"
    assert "AEP-002" in out or "drainage" in out.lower()


def test_denies_a_field_by_name_that_is_present():
    """The CT-066 shape: a category word is denied in the same block that names it."""
    rows = _rows(
        {
            "record": "WCP-008",
            "category": "Laboratory glass",
            "recordStatus": "active",
        },
        {
            "record": "WCP-016",
            "category": "Confidential shredding",
            "recordStatus": "active",
        },
    )
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register contains no other records that identify a different collection "
        "category beyond batteries and WEEE."
    )
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Where is the current approved point for batteries, WEEE or other special category "
        "I may encounter?",
        register_label="Waste Point Register",
    )
    assert out
    assert "category" in out.lower()


def test_cross_sentence_paraphrase_is_a_known_limit_not_caught():
    """Documents the conservative boundary: a denial that paraphrases (not names) a present
    field, with the field surfacing only in a LATER sentence/table, is not corrected by this
    same-sentence guard. That cross-sentence contradiction is C7's shape and is W23's job
    (typed composition), not this guard's — this guard trades recall for zero false positives.
    """
    rows = _rows(
        {"record": "REG-001", "approvedWindow": "Mon-Fri 07:00-19:00", "recordStatus": "active"}
    )
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register does not record any information about systems starting late, nor any "
        "scheduled start-or-stop times.\n\n| Record | Approved window |\n|---|---|\n"
        "| REG-001 | Mon-Fri 07:00-19:00 |"
    )
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Which systems started late against today's approved schedule?",
        register_label="Operating Regime Register",
    )
    assert out == ""


def test_no_correction_when_the_term_really_is_absent():
    """A genuinely-absent field must not be flagged — the guard fails open."""
    rows = _rows({"record": "REG-001", "recordStatus": "active", "owner": "Estates"})
    columns = sorted({k for r in rows for k in r})
    narration = "The register does not record a carbon offset figure for this asset."
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "What is the carbon offset figure for this asset?",
        register_label="Asset Register",
    )
    assert out == ""


def test_no_correction_without_an_absence_sentence():
    """A narration that just answers, without any denial, is left untouched."""
    rows = _rows({"record": "REG-001", "approvedWindow": "07:00-19:00", "recordStatus": "active"})
    columns = sorted({k for r in rows for k in r})
    narration = "REG-001 runs from 07:00 to 19:00."
    out = false_absence_corrections(
        narration, rows, columns, "What is the approved window for REG-001?", register_label="X"
    )
    assert out == ""


def test_empty_inputs_fail_open():
    assert false_absence_corrections("", [{"a": "1"}], ["a"], "q") == ""
    assert false_absence_corrections("text", [], [], "q") == ""


# ── 2026-09-18, after 39 unscripted live answers: the note must not restate the answer ──────────


def test_no_note_when_the_answer_already_cites_the_record_that_carries_the_term():
    """The batteries case, live. The answer cited WCP-017 and then said "no OTHER record lists a
    place for batteries"; the first version added "batteries — appears in WCP-017"."""
    rows = _rows(
        {"record": "WCP-017", "label": "WEEE and batteries bin", "recordStatus": "active"},
        {"record": "WCP-018", "label": "General waste", "recordStatus": "active"},
    )
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The building's records show one dedicated spot for batteries: the WEEE and batteries "
        "bin (record WCP\u2011017). No other record in the register lists a place for batteries."
    )  # note the NON-BREAKING hyphen the model wrote in the id
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Where do I put batteries for recycling?",
        register_label="Waste Point Register",
    )
    assert out == ""


def test_no_note_when_the_answer_already_names_the_field_in_its_own_words():
    rows = _rows({"record": "REG-001", "approvedException": "Runs to 22:00", "recordStatus": "active"})
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register does not record any information about systems starting late. It does "
        "record the approved exception for each system."
    )
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Which systems started late against today's approved schedule?",
        register_label="Operating Regime Register",
    )
    assert out == ""


def test_the_note_still_fires_when_the_answer_shows_no_trace_of_what_was_found():
    rows = _rows(
        {"record": "WCP-008", "category": "Laboratory glass", "recordStatus": "active"},
        {"record": "WCP-016", "category": "Confidential shredding", "recordStatus": "active"},
    )
    columns = sorted({k for r in rows for k in r})
    narration = "The register contains no other records that identify a different collection category."
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Where is the current approved point for batteries, WEEE or other special category?",
        register_label="Waste Point Register",
    )
    assert out.startswith("\n\n**Also recorded in this register:**")
    assert "category" in out.lower()


def test_the_note_never_prints_an_internal_field_name():
    """`dependsOnLift` was printed at a visitor by the first wording (codebook class C3)."""
    rows = _rows({"record": "RTE-001", "dependsOnLift": "Lift A", "recordStatus": "open"})
    columns = sorted({k for r in rows for k in r})
    narration = "The records do not contain any other information about lift accessibility."
    out = false_absence_corrections(
        narration,
        rows,
        columns,
        "Is there a lift I can use if I can't take stairs?",
        register_label="Circulation Register",
    )
    assert out, "the answer shows no trace of the field, so the note should fire"
    assert "dependsOnLift" not in out
    assert "depends on lift" in out.lower()


# ── status values: the demo script's "How many open work orders are there, and which are overdue?" ──


def _work_orders():
    return _rows(
        {"record": "WO-008", "label": "Electrical inspection", "recordStatus": "open"},
        {"record": "WO-013", "label": "Insulation resistance test", "recordStatus": "open"},
        {"record": "WO-020", "label": "Filter change", "recordStatus": "closed"},
    )


def test_no_note_for_a_status_value_the_answer_already_uses():
    rows = _work_orders()
    columns = sorted({k for r in rows for k in r})
    narration = (
        "There are 3 work-order records.\n\n**Open work orders**\n- WO-008 Electrical inspection\n"
        "- WO-013 Insulation resistance test\n\nThe register does not contain any field that "
        "records an overdue state, so it cannot say which open orders are overdue."
    )
    out = false_absence_corrections(
        narration, rows, columns, "How many open work orders are there, and which are overdue?",
        register_label="Work Order Register",
    )
    assert out == "", out


def _regime_rows():
    return _rows(
        {"record": "REG-001", "approvedException": "Runs to 22:00", "recordStatus": "active"},
        {"record": "REG-002", "approvedException": "Extended to 22:00", "recordStatus": "active"},
        {"record": "REG-008", "approvedException": "", "recordStatus": "active"},
    )


def test_the_field_said_the_other_way_round_counts_as_shown():
    """BUG-819: 'Exception approved' is the field 'approved exception' said backwards. The
    demo-script question about HVAC exceptions got the note 'exception — recorded as approved
    exception' appended under seven bullets that began 'Exception approved'."""
    rows = _regime_rows()
    columns = sorted({k for r in rows for k in r})
    narration = (
        "- **REG-001** Runs to 22:00. *Exception approved* - the record states the hours.\n"
        "- **REG-002** Extended to 22:00. *Exception approved* - approved by the School.\n\n"
        "Of those, 2 have an approved exception recorded, while the parking ventilation does "
        "not have an exception."
    )
    out = false_absence_corrections(
        narration, rows, columns, "Which HVAC systems run outside normal hours, and is each "
        "exception approved?", register_label="Operating Regime Register",
    )
    assert out == "", out


def test_one_word_of_a_two_word_field_is_not_enough_to_count_as_shown():
    rows = _regime_rows()
    columns = sorted({k for r in rows for k in r})
    narration = (
        "Systems here are approved by the School.\n\n"
        "The register does not record any exception for the parking ventilation."
    )
    out = false_absence_corrections(
        narration, rows, columns, "Which HVAC systems have an exception?",
        register_label="Operating Regime Register",
    )
    assert out.startswith("\n\n**Also recorded in this register:**"), out


def test_no_note_points_at_records_that_have_no_identifier():
    """BUG-824: 'service - appears in ?, ?' under a correct answer about lifts in service."""
    rows = _rows(
        {"label": "Passenger Lift 1", "note": "In service since 2021", "state": "operational"},
        {"label": "Goods Lift", "note": "In service since 2021", "state": "operational"},
    )
    columns = sorted({k for r in rows for k in r})
    narration = "None of the lifts are out of order. No record indicates any lift is unavailable."
    out = false_absence_corrections(
        narration, rows, columns, "Are any lifts out of service?", register_label="Lift Register"
    )
    assert "?" not in out, out


def test_a_word_the_answer_already_uses_outside_a_denial_is_not_corrected():
    """BUG-824: 'planned - appears in Planned Maintenance - Floor 2 ...' printed under a table
    that had just listed those two planned-maintenance events."""
    rows = _rows(
        {"record": "EV-1", "label": "Planned Maintenance - Floor 2", "state": "done"},
        {"record": "EV-2", "label": "Planned Maintenance - Floor 5", "state": "done"},
    )
    columns = sorted({k for r in rows for k in r})
    narration = (
        "The register records two planned-maintenance events, both in the past.\n\n"
        "No record in the register contains a future date for planned maintenance."
    )
    out = false_absence_corrections(
        narration, rows, columns, "When is the next planned maintenance?",
        register_label="Events Register",
    )
    assert out == "", out


def test_a_status_value_note_says_what_it_is_in_plain_words():
    rows = _work_orders()
    columns = sorted({k for r in rows for k in r})
    narration = "The register does not record whether an open item is urgent."
    out = false_absence_corrections(
        narration, rows, columns, "Is any open item urgent?", register_label="Work Order Register"
    )
    assert "*open* — is a status this register records" in out, out
    assert "record status as a recorded value" not in out
