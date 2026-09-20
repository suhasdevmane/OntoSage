# -*- coding: utf-8 -*-
"""Row 2D-04: the register oracle computes truth from the tables, and its checker needs no judge.

Two halves are pinned here. GENERATION: every register table under the documents is parsed, and
each question's expected count / ids / values come straight from the rows. CHECKING: an answer
is scored on fact recall, FALSE ABSENCE (the defect class that matters most), invented ids and a
decline where the facts exist - and the checker is itself tested with ground-truth phrasing (must
pass) and corrupted answers (each must fail for the right reason).

Small fixture tables carry the exact-number assertions; the real documents carry the "every
register found yields questions" assertion and are skipped when no building's documents exist.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "register_oracle.py"


def _load():
    spec = importlib.util.spec_from_file_location("register_oracle", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["register_oracle"] = mod
    spec.loader.exec_module(mod)
    return mod


ro = _load()

FIXTURE = """---
record_type: widget
owner: "Widget Team"
tables:
  - name: "Widget register"
    maps_to: widgets
---

# Widget register

## Time profiles

| profile | hours |
|---|---|
| `CORE` | 07:00-19:00 |
| `H24` | Continuous |

## Widget register

| code | name | kind | floor | status | owner | last_tested_on | next_test_due | evidence_ref | note |
|:--|---|---|---|---|---|---|---|---|---|
| WGT-001 | Alpha panel | alarm | 0 | Active | Ops Lead | 2026-01-10 | 2026-07-10 | EV-1 | |
| WGT-002 | Beta panel | alarm | 1 | Overdue | Ops Lead | 2026-01-11 | 2026-02-11 | EV-2 | late test |
| WGT-003 | Gamma door | door | 1 | Overdue | Fire Lead | 2026-01-12 | 2026-02-12 | | |
| WGT-004 | Delta door | door | 2 | Defective | Fire Lead | 2026-01-13 | 2026-07-13 | EV-4 | |
| WGT-005 | Epsilon pump | pump | 2 | Active | Ops Lead | 2026-01-14 | 2026-07-14 | EV-5 | |
| WGT-006 | Zeta pump | pump | 3 | Active | Ops Lead | 2026-01-15 | 2026-07-15 | EV-6 | |

**6 widgets.**

## A table that is not a register

| item | quantity |
|---|---|
| bolts | 4 |
| nuts | 6 |
"""

TWO_REGISTERS = """# Two registers in one file

| code | name | status |
|---|---|---|
| AAA-01 | First | Open |
| AAA-02 | Second | Closed |
| AAA-03 | Third | Open |

Some prose between the tables.

| ref | title | status | owner |
|---|---|---|---|
| BBB-1 | One | Done | Ann |
| BBB-2 | Two | Done | Bob |
| BBB-3 | Three | Pending | Ann |
"""

MESSY = """| code | name | status | note |
|:---:|---|---|---|
| ZZ-1 | Has \\| a pipe | Open | |
| ZZ-2 | Short row | Open |
| ZZ-3 | Fine | Closed | ok |
| ZZ-4 | **Bold** | Open | `code` |
"""


@pytest.fixture()
def docs(tmp_path: Path) -> Path:
    d = tmp_path / "documents"
    d.mkdir()
    (d / "widgets.md").write_text(FIXTURE, encoding="utf-8")
    return d


@pytest.fixture()
def regs(docs: Path):
    return ro.load_registers(docs)


@pytest.fixture()
def entries(regs) -> List[Dict[str, Any]]:
    return ro.generate(regs, n=500, seed=7)


def _find(entries: List[Dict[str, Any]], template: str, **flt: str) -> Dict[str, Any]:
    for e in entries:
        if e["template"] == template and all(e["filters"].get(k) == v for k, v in flt.items()):
            return e
    raise AssertionError(f"no {template} entry with filters {flt}")


def _score(regs, entry: Dict[str, Any], answer: str, **kw: Any) -> Dict[str, Any]:
    return ro.score_answer(entry, answer, regs[entry["register"]], **kw)


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------


def test_only_register_tables_are_registers(regs):
    assert list(regs) == [
        "widgets"
    ], "the profile/hours lookup and the item/quantity table are not registers"
    reg = regs["widgets"]
    assert len(reg.rows) == 6
    assert reg.noun == "widgets" and reg.title == "Widget register"


def test_column_roles_are_read_from_the_header_and_the_values(regs):
    reg = regs["widgets"]
    assert (reg.id_col, reg.status_col, reg.name_col, reg.owner_col) == (
        "code",
        "status",
        "name",
        "owner",
    )
    assert reg.date_cols == ["last_tested_on", "next_test_due"]
    assert reg.numeric_cols == ["floor"]
    # kind has 3 distinct values in 6 rows; floor has 4 in 6 and is too fine to slice by
    assert reg.kind_cols == ["kind"]
    assert reg.id_prefixes == {"WGT"}


def test_two_registers_in_one_file_get_distinct_keys(tmp_path):
    (tmp_path / "pair.md").write_text(TWO_REGISTERS, encoding="utf-8")
    regs = ro.load_registers(tmp_path)
    assert list(regs) == ["pair", "pair#2"]
    assert regs["pair"].id_col == "code" and regs["pair#2"].id_col == "ref"
    assert regs["pair#2"].owner_col == "owner"


def test_escaped_pipes_short_rows_and_markup_do_not_break_a_table(tmp_path):
    (tmp_path / "messy.md").write_text(MESSY, encoding="utf-8")
    reg = ro.load_registers(tmp_path)["messy"]
    assert [r["code"] for r in reg.rows] == ["ZZ-1", "ZZ-2", "ZZ-3", "ZZ-4"]
    assert reg.rows[0]["name"] == "Has | a pipe"
    assert reg.rows[1]["note"] == "", "a short row is padded, not dropped"
    assert reg.rows[3]["name"] == "Bold" and reg.rows[3]["note"] == "code"
    assert len(reg.anomalies) == 1 and "3 cells" in reg.anomalies[0]


def test_a_table_needs_an_id_like_first_column_and_a_status_column(tmp_path):
    (tmp_path / "nope.md").write_text(
        "| name | colour | status |\n|---|---|---|\n| red | r | ok |\n| blue | b | ok |\n| green | g | ok |\n\n"
        "| code | a | b |\n|---|---|---|\n| X-1 | 1 | 2 |\n| X-2 | 3 | 4 |\n| X-3 | 5 | 6 |\n",
        encoding="utf-8",
    )
    assert ro.load_registers(tmp_path) == {}


def test_documents_fall_back_to_a_parked_building_and_prefer_the_active_one(tmp_path, monkeypatch):
    (tmp_path / "bldg2" / "documents").mkdir(parents=True)
    monkeypatch.setattr(ro, "REPO", tmp_path)
    assert ro.default_doc_dir() == tmp_path / "bldg2" / "documents"
    (tmp_path / "input" / "documents").mkdir(parents=True)
    assert ro.default_doc_dir() == tmp_path / "input" / "documents"


def test_documents_directory_resolves_without_an_active_building():
    got = ro.default_doc_dir()
    assert got.name == "documents"
    assert got.parent.name == "input" or got.parent.name.startswith("bldg"), got


# ---------------------------------------------------------------------------------------------
# Generation: expected facts come from the rows
# ---------------------------------------------------------------------------------------------


def test_expected_facts_are_computed_from_the_rows(regs):
    cands = ro.enumerate_candidates(regs["widgets"], seed=1)

    def one(tpl: str, **flt: str):
        hits = [c for c in cands[tpl] if all(c.filters.get(k) == v for k, v in flt.items())]
        assert len(hits) == 1, (tpl, flt, len(hits))
        return hits[0].expected

    assert {c.filters["status"]: c.expected["count"] for c in cands["count_status"]} == {
        "Active": 3,
        "Overdue": 2,
        "Defective": 1,
    }
    assert one("list_status", status="Overdue")["ids"] == ["WGT-002", "WGT-003"]
    assert one("list_facet_status", status="Overdue", kind="alarm")["ids"] == ["WGT-002"]
    assert one("list_facet_status", status="Overdue", kind="door")["ids"] == ["WGT-003"]
    assert one("count_facet_status", status="Active", kind="pump")["count"] == 2
    # a (kind, status) pair with no rows is a real "none" question, not a missing one
    zero = one("any_exists", status="Overdue", kind="pump")
    assert zero["mode"] == "none" and zero["count"] == 0
    assert one("any_exists", status="Overdue", kind="door")["mode"] == "yes"
    assert one("count_facet", kind="door")["count"] == 2
    assert one("owner_facet", kind="door")["values"] == ["Fire Lead"]
    assert one("owner_facet", kind="alarm")["values"] == ["Ops Lead"]
    assert [c.expected["ids"] for c in cands["blank_field"]] == [["WGT-003"]]
    assert cands["blank_field"][0].slots["label"] == "evidence reference"
    assert cands["count_total"][0].expected["count"] == 6
    due = {c.slots["rec_id"]: c.expected["values"] for c in cands["when_next_due"]}
    assert due["WGT-002"] == ["2026-02-11"] and len(due) == 6
    last = {c.slots["rec_id"]: c.expected["values"] for c in cands["when_last_done"]}
    assert last["WGT-005"] == ["2026-01-14"]
    owner = {c.slots["rec_id"]: c.expected["values"] for c in cands["owner_record"]}
    assert owner["WGT-003"] == ["Fire Lead"]


def test_a_list_question_is_only_asked_when_the_list_is_readable(tmp_path):
    rows = "\n".join(
        f"| Q-{i:03d} | Item {i} | {'Open' if i < 20 else 'Shut'} |" for i in range(30)
    )
    (tmp_path / "big.md").write_text(
        "| code | name | status |\n|---|---|---|\n" + rows + "\n", encoding="utf-8"
    )
    reg = ro.load_registers(tmp_path)["big"]
    cands = ro.enumerate_candidates(reg, 1)
    assert {c.filters["status"] for c in cands["count_status"]} == {"Open", "Shut"}
    assert {c.filters["status"] for c in cands["list_status"]} == {
        "Shut"
    }, "20 Open ids are not a list anyone asks for; 10 Shut ids are"


def test_generation_is_seeded_balanced_and_restrictable(regs):
    a = ro.generate(regs, n=40, seed=5)
    assert a == ro.generate(regs, n=40, seed=5)
    assert [e["question"] for e in a] != [e["question"] for e in ro.generate(regs, n=40, seed=6)]
    assert len(a) == 40 and len({e["question"] for e in a}) == 40
    personas = [e["persona"] for e in a]
    assert set(personas) == set(ro.PERSONAS)
    assert (
        max(personas.count(p) for p in ro.PERSONAS) - min(personas.count(p) for p in ro.PERSONAS)
        <= 1
    )
    templates = {e["template"] for e in a}
    assert len(templates) >= 10, templates
    assert ro.generate(regs, n=5, seed=1, only=["nothing_like_this"]) == []
    assert {e["register"] for e in ro.generate(regs, n=5, seed=1, only=["widg"])} == {"widgets"}
    assert [e["id"] for e in a][:3] == ["RO-0001", "RO-0002", "RO-0003"]


def test_weights_tilt_the_register_balance(tmp_path):
    (tmp_path / "pair.md").write_text(TWO_REGISTERS, encoding="utf-8")
    (tmp_path / "widget_register.md").write_text(FIXTURE, encoding="utf-8")
    regs = ro.load_registers(tmp_path)
    assert set(regs) == {"pair", "pair#2", "widget_register"}

    def share(rows: List[Dict[str, Any]]) -> float:
        return sum(1 for r in rows if r["register"] == "widget_register") / len(rows)

    even = ro.generate(regs, n=30, seed=1)
    by_key = ro.generate(regs, n=30, seed=1, weights={"widget_register": 8.0})
    by_noun = ro.generate(regs, n=30, seed=1, weights={"widgets": 8.0})
    assert share(by_key) > share(even) + 0.2
    # registers a weights file does not name take its "_default"
    others = ro.generate(regs, n=30, seed=1, weights={"widget_register": 1.0, "_default": 8.0})
    assert share(others) < share(even) - 0.05
    assert [r["question"] for r in by_noun] == [
        r["question"] for r in by_key
    ], "a noun works as a key"


def test_generation_stops_when_the_pool_is_exhausted(regs):
    everything = ro.generate(regs, n=100000, seed=1)
    assert 40 < len(everything) < 100000


def test_five_wordings_ask_the_same_thing(regs):
    cand = next(c for c in ro.enumerate_candidates(regs["widgets"], 1)["list_facet_status"])
    qs = [ro.render_question(cand, p) for p in ro.PERSONAS]
    assert len(set(qs)) == 5
    for q in qs:
        assert "widgets" in q and cand.slots["facet"]["value"] in q and q.endswith(("?", "."))
        assert "overdue" in q.lower() or "defective" in q.lower() or "active" in q.lower()
    assert all(not q.lstrip().startswith("#") for q in qs), "ask_questions.py skips '#' lines"


def test_outputs_feed_ask_questions_unchanged(regs, tmp_path):
    rows = ro.generate(regs, n=12, seed=2)
    jl, tx = ro.write_oracle(rows, tmp_path / "out" / "oracle.v1")
    assert (
        jl.name == "oracle.v1.jsonl" and tx.name == "oracle.v1.txt"
    ), "a dotted prefix keeps its dots"
    lines = tx.read_text(encoding="utf-8").splitlines()
    assert lines == [r["question"] for r in rows]
    parsed = [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines()]
    assert [p["question"] for p in parsed] == lines, "ask_questions.py --jsonl reads ['question']"
    assert all({"id", "question", "register", "template", "expected"} <= set(p) for p in parsed)
    assert all({"count", "ids", "values", "property"} <= set(p["expected"]) for p in parsed)


REAL = ro.default_doc_dir()
_HAVE_REAL = REAL.is_dir() and any(REAL.glob("*_register.md"))


@pytest.mark.skipif(not _HAVE_REAL, reason="no building's documents on this checkout")
def test_every_real_register_is_found_and_yields_at_least_three_questions():
    real = ro.load_registers(REAL)
    assert len(real) >= 25
    for must in ("fire_safety", "maintenance_log", "access_permission_register"):
        assert must in real
    for key, reg in real.items():
        assert len(reg.rows) >= 3 and reg.status_col and reg.id_col
        assert len(set(reg.ids)) == len(reg.ids), f"{key}: duplicate ids"
        got = {t: v for t, v in ro.enumerate_candidates(reg, 1).items() if v}
        assert sum(len(v) for v in got.values()) >= 3, key
        assert "count_total" in got and "count_status" in got, key


@pytest.mark.skipif(not _HAVE_REAL, reason="no building's documents on this checkout")
def test_real_counts_agree_with_a_plain_text_recount():
    """An independent check: count the '| Overdue |' lines in the file itself."""
    real = ro.load_registers(REAL)
    for key, status in (("fire_safety", "Overdue"), ("maintenance_log", "Pending")):
        raw = (REAL / f"{key}.md").read_text(encoding="utf-8").splitlines()
        want = sum(1 for ln in raw if ln.startswith("|") and f"| {status} |" in ln)
        cand = next(
            c
            for c in ro.enumerate_candidates(real[key], 1)["count_status"]
            if c.filters["status"] == status
        )
        assert cand.expected["count"] == want > 0, key


@pytest.mark.skipif(not _HAVE_REAL, reason="no building's documents on this checkout")
def test_the_default_run_is_two_hundred_and_fifty_balanced_questions():
    real = ro.load_registers(REAL)
    rows = ro.generate(real, n=250, seed=1)
    assert len(rows) == 250 and len({r["question"] for r in rows}) == 250
    per_reg = [sum(1 for r in rows if r["register"] == k) for k in real]
    assert max(per_reg) - min(per_reg) <= 1, "balanced across registers"
    per_tpl = {t: sum(1 for r in rows if r["template"] == t) for t in {r["template"] for r in rows}}
    assert len(per_tpl) == len(ro._TEMPLATES) and min(per_tpl.values()) >= 10, per_tpl


# ---------------------------------------------------------------------------------------------
# Reading an answer
# ---------------------------------------------------------------------------------------------


def test_ids_survive_non_breaking_hyphens_case_and_spacing():
    rx = ro.id_regex(["FSA-027", "FSA-001"])
    text = ro.normalise("FSA" + ro.NB_HYPHEN + "027, fsa 001 and **FSA–027**")
    assert {ro.id_tokens(m.group(0)) for m in rx.finditer(text)} == {("FSA", 27), ("FSA", 1)}
    assert ro.id_tokens("INC-2026-005") == ("INC", 2026, 5)
    inc = ro.id_regex(["INC-2026-001", "INC-2026-002"])
    assert inc.search("see INC-2026-012 for the failure") and not inc.search("2026-09-16")
    assert not ro.id_regex(["FSA-027"]).search("BS 5839 and FSAX-9")


def test_dates_are_found_in_every_common_format():
    from datetime import date

    d = date(2026, 9, 18)
    for text in (
        "due 2026-09-18",
        "due 18 Sep 2026",
        "due 18 September 2026",
        "due 18th of September, 2026",
        "due September 18, 2026",
        "due Sep 18 2026",
        "due 18/09/2026",
        "due 2026/09/18",
        "due 18.09.2026",
        "due 2026" + ro.NB_HYPHEN + "09" + ro.NB_HYPHEN + "18",
    ):
        assert d in ro.dates_in(text), text
    assert ro.dates_in("released in version 2026.9") == set()
    assert date(2026, 9, 5) in ro.dates_in("05/09/2026") and date(2026, 5, 9) in ro.dates_in(
        "05/09/2026"
    )
    assert ro.fmt_date("2026-09-18", 1) == "18 Sep 2026"
    for style in range(5):
        assert d in ro.dates_in(ro.fmt_date("2026-09-18", style))


def test_counts_are_read_as_digits_or_words_but_not_from_ids_dates_or_list_numbers():
    rx = ro.id_regex(["WO-008", "WO-013"])
    ints, decs = ro.numbers_in("There are Three of 24 items; 1,200 kWh; 3.6 hours.", rx)
    assert {3, 24, 1200} <= ints and 3 not in {
        i for i in ro.numbers_in("WO-008 on 2026-09-18 at 10:30", rx)[0]
    }
    assert ro.numbers_in("WO-008 on 2026-09-18 at 10:30", rx)[0] == set()
    assert ro.numbers_in("1. WO-008\n2. WO-013\n- 3) x", rx)[0] == set()
    assert ro.numbers_in("twenty-one and forty", None)[0] == {21, 40}
    from decimal import Decimal

    assert Decimal("3.6") in decs and 3 not in ro.numbers_in("3.6 hours", None)[0]
    assert (
        ro.number_word(7) == "seven"
        and ro.number_word(34) == "thirty-four"
        and ro.number_word(675) == "675"
    )


def test_a_value_that_only_repeats_the_question_is_not_an_answer():
    """Found by the selfcheck at n=1500: the record's own name carried the value it was asked for."""
    echo = ["Zeta pump", "WGT-006"]
    assert not ro.value_present("pump", "The kind of the Zeta pump is unknown.", None, echo)
    assert ro.value_present("pump", "The Zeta pump is a pump.", None, echo)
    # a value that CONTAINS the record's name is not hidden by it
    assert ro.value_present(
        "Emergency Planning Officer",
        "The Emergency Planning is owned by the Emergency Planning Officer.",
        None,
        ["Emergency Planning"],
    )
    assert not ro.value_present(
        "Room 3.26 - Meeting Room", "It is the Meeting room 3.26.", None, ["Meeting room 3.26"]
    )
    assert ro.value_present(
        "Room 3.26 - Meeting Room", "Room 3.26 - Meeting Room", None, ["Meeting room 3.26"]
    )
    assert not ro.value_present(
        "1",
        "Seated rests of the Reception to Level 1 Atrium: none.",
        None,
        ["Reception to Level 1 Atrium"],
    )
    assert ro.value_present(
        "1", "Reception to Level 1 Atrium has 1 seated rest.", None, ["Reception to Level 1 Atrium"]
    )
    assert ro.value_present("-1.0", "The remaining life is -1.0 years (–1.0).")
    assert ro.value_present(
        "security@example.ac.uk", "Contact security@example.ac.uk", None, ["Security"]
    )


def test_a_category_named_like_a_column_word_is_not_a_structural_claim(tmp_path):
    (tmp_path / "inc.md").write_text(
        "| ref | summary | category | status |\n|---|---|---|---|\n"
        "| INC-1 | a | property damage | Open |\n| INC-2 | b | slip | Open |\n"
        "| INC-3 | c | slip | Closed |\n| INC-4 | d | fire | Closed |\n",
        encoding="utf-8",
    )
    regs = ro.load_registers(tmp_path)
    es = ro.generate(regs, n=200, seed=1)
    e = _find(es, "any_exists", status="Closed", category="property damage")
    assert e["expected"]["mode"] == "none"
    text = "No. There are no incident records of category property damage that are closed."
    assert ro.score_answer(e, text, regs["inc"])["pass"]


def test_cell_values_are_matched_as_dates_numbers_or_loose_text():
    assert ro.value_present("2026-02-11", "Due on 11 Feb 2026.")
    assert not ro.value_present("2026-02-11", "Due on 12 Feb 2026.")
    assert ro.value_present("3.6", "It took 3.6 hours") and not ro.value_present(
        "3.6", "It took 36 hours"
    )
    assert ro.value_present("M and E Maintenance Supervisor", "Owner: M&E Maintenance Supervisor")
    assert ro.value_present(
        "Room 0.10 - Building Management Office", "in Room 0.10 – Building Management Office."
    )
    assert not ro.value_present(
        "Room 0.10 - Building Management Office", "in the Building Management Office"
    )
    assert ro.value_present("FIRE_EVAC, LOCKDOWN", "Overrides: FIRE_EVAC and LOCKDOWN")
    assert not ro.value_present("Fire Lead", "Ops Lead")


# ---------------------------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------------------------


def test_ground_truth_phrasing_passes_for_every_generated_question(regs, entries):
    assert len(entries) > 40
    for k, e in enumerate(entries):
        for style in range(4):
            sc = _score(regs, e, ro.render_truth(e, k + style))
            assert sc["pass"], (e["template"], e["question"], ro.render_truth(e, k + style), sc)


def test_each_corruption_fails_for_the_right_reason(regs, entries):
    hit = dict.fromkeys(ro.CORRUPTIONS, 0)
    for e in entries:
        for kind in ro.CORRUPTIONS:
            made = ro.corrupt(e, kind, regs[e["register"]])
            if made is None:
                continue
            hit[kind] += 1
            answer, want = made
            sc = _score(regs, e, answer)
            assert not sc["pass"] and want in sc["reasons"], (kind, e["template"], answer, sc)
    assert all(v > 0 for v in hit.values()), hit


def test_selfcheck_passes_on_the_fixture_and_on_the_real_documents(regs):
    ok, lines = ro.selfcheck(regs, n=80, seed=3)
    assert ok, "\n".join(lines)
    assert any("ground truth: " in ln and "100.0%" in ln for ln in lines)
    if _HAVE_REAL:
        ok, lines = ro.selfcheck(ro.load_registers(REAL), n=250, seed=1)
        assert ok, "\n".join(lines)


def test_a_wrong_count_names_the_expected_count(regs, entries):
    e = _find(entries, "count_status", status="Overdue")
    good = _score(regs, e, "There are 2 widgets that are overdue.")
    assert good["pass"] and good["reasons"] == []
    bad = _score(regs, e, "There are 9 widgets that are overdue.")
    assert bad["reasons"] == ["WRONG_COUNT"] and bad["evidence"]["expected_count"] == 2
    assert _score(regs, e, "Two of the six widgets are overdue.")["pass"]


def test_a_number_in_the_place_the_question_named_is_not_the_count(regs, entries):
    """'8 items on floor 1' must not pass for a count of 1 (found by the checker's own selfcheck)."""
    e = _find(entries, "count_facet_status", status="Overdue", kind="alarm")
    assert e["expected"]["count"] == 1
    assert not _score(regs, e, "There are 8 widgets on floor 1 that are overdue, at Level 1.")[
        "pass"
    ]
    assert _score(regs, e, "There is 1 widget on floor 1 that is overdue.")["pass"]
    cnt = ro.numbers_in("8 on floor 1, the 1st, room 5.04 and 4-hourly", None, True, ["4-hourly"])[
        0
    ]
    assert cnt == {8}
    assert 1 in ro.numbers_in("8 on floor 1")[0], "unmasked reading keeps every number"


def test_listing_the_right_records_without_a_number_still_answers_how_many(regs, entries):
    e = _find(entries, "count_status", status="Overdue")
    sc = _score(regs, e, "Overdue:\n1. WGT-002\n2. WGT-003")
    assert sc["pass"] and "COUNT_IMPLICIT" in sc["warnings"]
    assert not _score(regs, e, "Overdue:\n1. WGT-002")["pass"]


def test_missing_ids_are_named_and_names_count_as_mentions(regs, entries):
    e = _find(entries, "list_status", status="Overdue")
    sc = _score(regs, e, "Only WGT-002 is overdue.")
    assert sc["reasons"] == ["MISSING_IDS"] and sc["evidence"]["missing_ids"] == ["WGT-003"]
    assert _score(regs, e, "The Beta panel and the Gamma door are overdue.")["pass"]
    assert _score(regs, e, "wgt 002 and wgt-003")["pass"]
    assert _score(regs, e, "WGT" + ro.NB_HYPHEN + "002 and WGT" + ro.NB_HYPHEN + "003")["pass"]


def test_false_absence_is_a_claim_that_a_column_or_value_the_table_holds_is_missing(regs, entries):
    own = _find(entries, "owner_record")
    prop = own["expected"]["values"][0]
    for claim in (
        "The register has no ownership field for this record.",
        "The register does not record who owns it.",
        "There is no owner recorded, so I cannot say.",
        "The building only records sensor counts.",
    ):
        sc = _score(regs, own, claim)
        assert "FALSE_ABSENCE" in sc["reasons"], (claim, sc)
    assert _score(regs, own, f"It is owned by {prop}.")["pass"]

    lst = _find(entries, "list_status", status="Overdue")
    for claim in (
        "The register does not record a status for these widgets.",
        "There are no overdue widgets.",
        "The records do not contain any information about overdue widgets.",
    ):
        assert "FALSE_ABSENCE" in _score(regs, lst, claim)["reasons"], claim

    due = _find(entries, "when_next_due")
    assert (
        "FALSE_ABSENCE" in _score(regs, due, "There is no next test due date recorded.")["reasons"]
    )
    assert (
        "FALSE_ABSENCE"
        in _score(regs, due, "The register does not have a due date column.")["reasons"]
    )


def test_a_true_absence_or_a_row_level_none_is_not_a_false_absence(regs, entries):
    lst = _find(entries, "list_status", status="Overdue")
    ok = "WGT-002 and WGT-003 are overdue."
    for extra in (
        # a value the register does not hold, in quotes: the register really has no such state
        'The register does not record an "escalated" state.',
        # a per-row 'none': some rows, not the register
        "1 record has no evidence reference recorded (WGT-003).",
        "Two widgets have no note recorded.",
        "| WGT-003 | Gamma door | none recorded |",
        "I don't think that's an issue.",
    ):
        sc = _score(regs, lst, ok + "\n" + extra)
        assert "FALSE_ABSENCE" not in sc["reasons"], (extra, sc)
    blank = _find(entries, "blank_field")
    assert _score(regs, blank, "WGT-003 (Gamma door) has no evidence reference recorded.")["pass"]
    assert _score(
        regs, blank, "Only WGT-003 carries no evidence reference; the rest all have one."
    )["pass"]
    assert (
        "FALSE_ABSENCE"
        in _score(regs, blank, "The register has no evidence reference column.")["reasons"]
    )


def test_true_statements_made_after_the_right_facts_are_not_false_absences(regs, entries):
    """Sentences taken from real answers of earlier live runs (docs/phase0), each true and each
    once flagged by an earlier version of this checker."""
    lst = _find(entries, "list_status", status="Overdue")
    ok = "WGT-002 and WGT-003 are overdue. "
    for extra in (
        "The register does not contain any other records that are overdue for test.",
        "No other assets in the register are overdue or lack evidence.",
        "It does not contain any additional details about the inspection outcome beyond the status field.",
        "They only record the booking status (confirmed, provisional, cancelled).",
        "The record's status is at risk, meaning the target is not currently on track.",
        "Only this asset has an empty evidence reference field, meaning the register does not contain "
        "a record of the test evidence for it.",
        "*Next test due 2026-05-05 (overdue) - no evidence reference recorded*",
    ):
        sc = _score(regs, lst, ok + extra)
        assert "FALSE_ABSENCE" not in sc["reasons"], (extra, sc)
    # ...but the same words as a whole-answer denial are still caught
    assert (
        "FALSE_ABSENCE" in _score(regs, lst, "The building only records sensor counts.")["reasons"]
    )
    assert (
        "FALSE_ABSENCE"
        in _score(regs, lst, "They only record booking status and dates.")["reasons"]
    )


def test_the_refuge_point_ownership_answers_of_bug_835_are_caught(regs, entries):
    """BUG-835 in miniature: the register has an owner column and the answer says it has not."""
    own = _find(entries, "owner_record")
    for sentence in (
        "The widget register, which lists panels, does not contain an owner field.",
        "*Owner:* not recorded in the Widget register",
        "The Widget register does not contain a field for ownership, so the records do not state who owns them.",
    ):
        sc = _score(regs, own, "WGT-004 is defective.\n" + sentence)
        assert "FALSE_ABSENCE" in sc["reasons"] and "MISSING_VALUES" in sc["reasons"], sentence
        assert sc["evidence"]["false_absence"]


def test_a_column_named_like_a_hedge_word_is_still_a_column(tmp_path):
    (tmp_path / "svc.md").write_text(
        "| code | name | status | remaining_life_years |\n|---|---|---|---|\n"
        "| S-1 | a | Open | 3 |\n| S-2 | b | Open | 4 |\n| S-3 | c | Shut | 5 |\n",
        encoding="utf-8",
    )
    regs = ro.load_registers(tmp_path)
    e = _find(ro.generate(regs, n=100, seed=1), "field_of_record")
    text = f"The {regs['svc'].noun} register has no remaining life years field, so this cannot be said."
    assert "FALSE_ABSENCE" in ro.score_answer(e, text, regs["svc"])["reasons"]


def test_invented_ids_are_this_registers_shape_that_the_table_does_not_hold(regs, entries):
    e = _find(entries, "list_status", status="Overdue")
    sc = _score(regs, e, "WGT-002, WGT-003 and WGT-099 are overdue.")
    assert sc["reasons"] == ["INVENTED_IDS"] and sc["evidence"]["invented_ids"] == ["WGT-099"]
    assert _score(regs, e, "WGT-002, WGT-003 (see INC-2026-012 and EV-2, BS 5839-1).")["pass"]
    assert ro.mint_invented_id(regs["widgets"]) not in regs["widgets"].ids


def test_a_decline_is_a_failure_only_when_the_facts_exist_and_are_missing(regs, entries):
    e = _find(entries, "list_status", status="Overdue")
    sc = _score(regs, e, "I couldn't find that in the building's records.")
    assert "DECLINED" in sc["reasons"] and "MISSING_IDS" in sc["reasons"]
    partial = _score(
        regs, e, "WGT-002 and WGT-003 are overdue, but I cannot say when they became so."
    )
    assert partial["pass"], "a caveat beside the right facts is not a decline"
    assert _score(regs, e, "")["reasons"] == ["NO_ANSWER"]
    assert _score(regs, e, "WGT-002 WGT-003", status="TIMEOUT")["reasons"] == ["NO_ANSWER"]


def test_says_none_when_records_exist_is_wrong_none(regs, entries):
    e = _find(entries, "any_exists", status="Overdue", kind="alarm")
    assert e["expected"]["mode"] == "yes"
    assert _score(regs, e, "Yes - WGT-002 is overdue.")["pass"]
    assert _score(regs, e, "Yes.")["pass"]
    sc = _score(regs, e, "No, none are overdue.")
    assert "WRONG_NONE" in sc["reasons"]


def test_a_none_question_accepts_every_way_of_saying_none_and_rejects_a_decline(regs, entries):
    e = _find(entries, "any_exists", status="Overdue", kind="pump")
    assert e["expected"]["mode"] == "none"
    for good in (
        "No. None of the pump widgets are overdue.",
        "There are no overdue pumps.",
        "The register does not record any overdue pumps.",
        "0 pumps are overdue.",
        "No - all pumps (WGT-005, WGT-006) are active; none is overdue.",
    ):
        assert _score(regs, e, good)["pass"], good
    for bad in (
        "I could not find any information about overdue pumps.",
        "Yes, WGT-005 is overdue.",
        "There is no information available.",
        "The register has no status field for pumps.",
    ):
        assert not _score(regs, e, bad)["pass"], bad


def test_extra_real_ids_warn_unless_strict(regs, entries):
    e = _find(entries, "list_status", status="Overdue")
    text = "Overdue: WGT-002 and WGT-003. (Active: WGT-001.)"
    soft = _score(regs, e, text)
    assert (
        soft["pass"]
        and soft["warnings"] == ["EXTRA_IDS"]
        and soft["evidence"]["extra_ids"] == ["WGT-001"]
    )
    strict = _score(regs, e, text, strict_extra=True)
    assert not strict["pass"] and strict["reasons"] == ["EXTRA_IDS"]


def test_dates_are_accepted_in_any_format_and_a_wrong_date_fails(regs, entries):
    e = next(
        x
        for x in entries
        if x["template"] == "when_next_due" and x["expected"]["ids"] == ["WGT-002"]
    )
    for text in (
        "2026-02-11",
        "11 Feb 2026",
        "February 11, 2026",
        "11 February 2026",
        "11/02/2026",
    ):
        assert _score(regs, e, f"It is next due on {text}.")["pass"], text
    sc = _score(regs, e, "It is next due on 2026-02-12.")
    assert sc["reasons"] == ["MISSING_VALUES"] and sc["evidence"]["missing_values"] == [
        "2026-02-11"
    ]


def test_owner_of_a_kind_needs_every_owner(regs, entries):
    e = _find(entries, "owner_facet", kind="door")
    assert _score(regs, e, "Fire Lead owns them.")["pass"]
    assert not _score(regs, e, "Ops Lead owns them.")["pass"]


# ---------------------------------------------------------------------------------------------
# Scoring a run file
# ---------------------------------------------------------------------------------------------


def _run_rows(entries: List[Dict[str, Any]], regs, bad_every: int = 3) -> List[Dict[str, Any]]:
    rows = []
    for k, e in enumerate(entries):
        if k % bad_every == 0:
            made = ro.corrupt(e, "false_absence", regs[e["register"]])
            answer = made[0] if made else "I could not find that."
        else:
            answer = ro.render_truth(e, k)
        rows.append(
            {
                "q": "  " + e["question"].replace(" ", "  ", 1),
                "run": 1,
                "secs": 1.0,
                "status": "OK",
                "answer": answer,
            }
        )
    return rows


def test_a_run_file_is_joined_to_the_oracle_by_question_text(regs, entries):
    sub = entries[:30]
    run = _run_rows(sub, regs)
    run.append({"q": "a question the oracle never asked", "answer": "x", "status": "OK"})
    scored = ro.score_run(sub[:-2], run, regs)
    assert len(scored["results"]) == 28
    assert scored["unmatched_run_rows"] == 3
    assert scored["not_asked"] == []
    sm = ro.summarise(scored)
    bad = sum(1 for k in range(28) if k % 3 == 0)
    assert sm["scored"] == 28 and sm["passed"] == 28 - bad
    assert sm["defects"]["FALSE_ABSENCE"] >= bad - 1
    assert sm["pass_ci95"][0] < sm["pass_rate"] < sm["pass_ci95"][1]
    assert {r["register"] for r in sm["by_register"]} == {"widgets"}
    assert {r["template"] for r in sm["by_template"]} <= set(ro._TEMPLATES)
    assert sum(r["n"] for r in sm["by_persona"]) == 28


def test_a_register_file_that_changed_after_generation_is_reported_stale(docs, entries, regs):
    assert all(e["source"] == {"file": "widgets.md", "sha1": regs["widgets"].sha1} for e in entries)
    sub = entries[:6]
    run = _run_rows(sub, regs, bad_every=99)
    fresh = ro.score_run(sub, run, regs)
    assert fresh["stale_registers"] == []
    assert "WARNING" not in ro.format_report(fresh)
    (docs / "widgets.md").write_text(FIXTURE.replace("Ops Lead", "Ops Chief"), encoding="utf-8")
    later = ro.load_registers(docs)
    stale = ro.score_run(sub, run, later)
    assert stale["stale_registers"] == ["widgets"]
    text = ro.format_report(stale)
    assert (
        "WARNING" in text
        and "widgets" in text
        and ro.summarise(stale)["stale_registers"] == ["widgets"]
    )


def test_repeats_of_a_question_are_each_scored(regs, entries):
    e = _find(entries, "count_total")
    run = [
        {"q": e["question"], "run": 1, "status": "OK", "answer": ro.render_truth(e, 0)},
        {"q": e["question"], "run": 2, "status": "OK", "answer": "I couldn't find that."},
    ]
    scored = ro.score_run([e], run, regs)
    assert [r["score"]["pass"] for r in scored["results"]] == [True, False]


def test_the_report_names_every_failure_with_its_reason(regs, entries):
    run = _run_rows(entries[:12], regs)
    text = ro.format_report(ro.score_run(entries[:12], run, regs))
    assert "REGISTER ORACLE  scored 12 answers" in text and "PASS " in text
    assert "FALSE_ABSENCE" in text and "BY REGISTER" in text and "BY TEMPLATE" in text
    assert "FAILING QUESTIONS (4)" in text and text.count("      Q: ") == 4
    assert "absence claim:" in text
    assert (
        text.count("      Q: ")
        == ro.format_report(ro.score_run(entries[:12], run, regs), max_fails=2).count("      Q: ")
        + 2
    )


def test_the_command_line_generates_scores_and_selfchecks(docs, tmp_path, capsys):
    prefix = tmp_path / "o" / "oracle"
    assert ro.main(["--docs", str(docs), "--n", "30", "--seed", "4", "--out", str(prefix)]) == 0
    assert "[written] 30 questions across 1 registers" in capsys.readouterr().out
    oracle = ro.read_jsonl(Path(f"{prefix}.jsonl"))
    assert len(oracle) == 30
    regs = ro.load_registers(docs)
    run = tmp_path / "run.jsonl"
    run.write_text(
        "".join(json.dumps(r) + "\n" for r in _run_rows(oracle, regs, bad_every=5)),
        encoding="utf-8",
    )
    out_json = tmp_path / "score.json"
    rc = ro.main(
        [
            "--docs",
            str(docs),
            "--score",
            str(run),
            "--oracle",
            f"{prefix}.jsonl",
            "--json",
            str(out_json),
        ]
    )
    shown = capsys.readouterr().out
    assert rc == 0 and "PASS 24/30 = 80.0%" in shown
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["summary"]["scored"] == 30 and len(payload["rows"]) == 30
    assert sum(1 for r in payload["rows"] if not r["pass"]) == 6
    assert ro.main(["--docs", str(docs), "--selfcheck", "--n", "40"]) == 0
    assert "selfcheck PASSED" in capsys.readouterr().out
    assert ro.main(["--docs", str(docs), "--list"]) == 0
    assert "widgets" in capsys.readouterr().out
    assert (
        ro.main(["--docs", str(docs), "--n", "5", "--register", "zzz", "--out", str(prefix)]) == 2
    )


def test_the_tool_cannot_reach_the_network_or_the_orchestrator():
    """Not a runtime guard: the module imports nothing that can open a socket or call a model."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "redis",
        "asyncio",
        "subprocess",
        "orchestrator",
        "shared",
        "openai",
        "ollama",
    }
    assert not (imported & forbidden), imported & forbidden
