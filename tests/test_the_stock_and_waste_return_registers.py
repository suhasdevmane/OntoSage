# -*- coding: utf-8 -*-
"""The stores register and the waste returns register hold together (row 2D-11).

Two registers were added because the 2,960 stakeholder questions ask for them and the building
held nothing that could answer:

* `stock_register.md` (`ontosage:StockItem`) - spares, consumables, loan equipment and surplus
  stock by store. Contractors ask "which spares and consumables are confirmed available, and
  where are they held"; caretakers ask what to replenish before the next shift.
* `waste_returns_register.md` (`ontosage:WasteReturn`) - the contractor's monthly return in
  tonnes. Asked "how much waste did we produce this month?", the system said the quantity was not
  recorded and then listed bins "belonging to the month", a marking that does not exist.

Both are placeholders authored to be CONSISTENT with what the building already states, and each
check below is a place where two parts of the system could otherwise hold two answers to one
question: a status that contradicts its own numbers, a summary sentence that miscounts its own
table, a stream the collection point register has never heard of, a diversion figure below the
baseline a target that is "on track" is measured from.

Nothing here touches a live service. The documents are read from whichever building folder holds
them (`input/` while a building is active, `<building>/` when parked).
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from orchestrator.services.record_documents import (  # noqa: E402
    lift_document,
    parse_front_matter,
    parse_tables,
)

MAPPINGS = REPO / "ontology" / "record_documents"
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
NS = "http://example.org/building#"

#: The day the placeholders were authored. A count on a shelf is never dated after it.
AUTHORED = date(2026, 9, 18)

_FAKE_WORDS = re.compile(
    r"\b(simulated|synthetic|fictional|not\s+real|fake|dummy)\b", re.IGNORECASE
)


def _find(name: str) -> Path:
    """A document by file name, in the active building or a parked one."""
    candidates = [REPO / "input" / "documents" / name] + sorted(REPO.glob(f"*/documents/{name}"))
    for path in candidates:
        if path.is_file():
            return path
    return Path()


def _need(name: str) -> Path:
    path = _find(name)
    if not path.is_file():
        pytest.skip(f"{name} is in no building folder of this checkout")
    return path


def _rows(name: str, heading_contains: str) -> List[Dict[str, str]]:
    body = parse_front_matter(_need(name).read_text(encoding="utf-8"))[1]
    for heading, rows in parse_tables(body):
        if heading_contains in heading.lower():
            return rows
    raise AssertionError(f"{name} has no table under a heading containing {heading_contains!r}")


def _stock() -> List[Dict[str, str]]:
    return _rows("stock_register.md", "stock register")


def _returns() -> List[Dict[str, str]]:
    return _rows("waste_returns_register.md", "waste returns register")


def _schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


# ── they lift, completely ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected_type",
    [("stock_register.md", "stock_item"), ("waste_returns_register.md", "waste_return")],
)
def test_each_document_lifts_every_row_and_nothing_is_dropped(name, expected_type):
    """The lift is all-or-nothing: one bad cell would silently cost the whole register."""
    path = _need(name)
    result = lift_document(path, NS, MAPPINGS)
    assert result.record_type == expected_type
    assert not result.errors, result.errors[:5]
    tables = parse_tables(parse_front_matter(path.read_text(encoding="utf-8"))[1])
    data_rows = sum(len(rows) for _, rows in tables)
    assert result.instances == data_rows > 0


def test_every_lifted_record_carries_the_simulated_declaration():
    """The audit trail the wording rule leaves alone: the flag rides every triple."""
    for name in ("stock_register.md", "waste_returns_register.md"):
        result = lift_document(_need(name), NS, MAPPINGS)
        flags = [v for (_, p, v) in result.triples if p.endswith("isSimulated")]
        assert flags and all(v is True for v in flags), name


# ── the TBox and the vocabulary ────────────────────────────────────────────────────────────────


def test_both_classes_are_declared_beneath_a_record_root():
    text = _schema_text()
    assert re.search(r"ontosage:StockItem\s+rdfs:subClassOf\s+ontosage:Record\b", text)
    assert re.search(r"ontosage:WasteReturn\s+rdfs:subClassOf\s+ontosage:IntervalRecord\b", text)


def _declared_terms(cls: str) -> List[str]:
    text = _schema_text()
    m = re.search(
        rf"ontosage:{cls}\s+ontosage:layTerms\s+((?:[^.]|\.\d)*?)\s*\.\s*\n", text, re.DOTALL
    )
    assert m, f"{cls} declares no layTerms statement"
    return [t.strip().lower() for t in re.findall(r'"([^"]+)"', m.group(1))]


#: Bare words each class deliberately does NOT claim, and why. Every one was measured on the
#: 2,960 catalogue questions with scripts/register_reach.py before it was left out.
_REFUSED = {
    "StockItem": {
        "spares": "'unavailable spares' in a risk question is not a stock question",
        "stock": "a bare 'stock' is also a market, a stockpile and a livestock term",
        "replenishment": "reached leadership and emergency questions that only mention it",
        "replenish": "as 'replenishment'",
        "assistive listening": "an accessibility ARRANGEMENT for a talk is not a receiver loan",
        "batteries": "'where can I recycle batteries' is a waste-point question",
        "toner": "a bare item name is not evidence the question is about stock",
        "adapters": "'adapter' is also the SQL and storage adapter layer",
        "surplus": "'surplus energy' is a generation question",
        "borrow": "'can I borrow a room' is a booking question",
        "redeploy": "a staffing word",
        "supplies": "'water supplies' and 'power supply'",
        "filters": "'when were the air filters changed' is a service-schedule question",
        "belts": "belt changes are permits and service tasks",
    },
    "WasteReturn": {
        "waste": "owned by the collection point register; a bare 'waste' would take every bin question",
        "tonnes": "'tonnes of CO2' is a carbon question",
        "recycling": "owned by the collection point register",
        "recycle": "'where can I recycle X' is a waste-point question",
        "weight": "a bare 'weight' is a load, a person and a plant question",
        "returns": "a finance word",
    },
}


@pytest.mark.parametrize("cls", sorted(_REFUSED))
def test_the_vocabulary_refuses_the_bare_words_that_were_measured_to_hijack(cls):
    declared = set(_declared_terms(cls))
    claimed = sorted(w for w in _REFUSED[cls] if w in declared)
    assert not claimed, (
        f"{cls} now claims {claimed}. Each was measured over-capturing questions that are about "
        f"something else: " + "; ".join(f"{w} ({_REFUSED[cls][w]})" for w in claimed)
    )


@pytest.mark.parametrize("cls", ["StockItem", "WasteReturn"])
def test_every_lay_term_is_long_enough_to_be_scored(cls):
    """`_terms_for` discards a term of three characters or fewer, silently."""
    short = [t for t in _declared_terms(cls) if len(t) <= 3]
    assert not short, f"{cls} declares terms the router discards: {short}"


# ── the stock register ────────────────────────────────────────────────────────────────────────


def test_stock_kinds_are_the_four_declared_kinds_and_the_summary_counts_them():
    rows = _stock()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"consumable", "spare", "loan", "surplus"}
    text = _need("stock_register.md").read_text(encoding="utf-8")
    summary = re.search(r"\*\*(\d+) entries across (\d+) kinds - (.*?) held in (\d+) stores", text)
    assert summary, "the closing sentence no longer states its counts"
    assert int(summary.group(1)) == len(rows)
    assert int(summary.group(2)) == len(kinds)
    assert int(summary.group(4)) == len({r["store"] for r in rows})
    for label, kind in (
        ("consumables", "consumable"),
        ("spares", "spare"),
        ("loan lines", "loan"),
        ("surplus lines", "surplus"),
    ):
        m = re.search(rf"(\d+) {label}", summary.group(3))
        assert m and int(m.group(1)) == sum(1 for r in rows if r["kind"] == kind), label


def test_a_stock_status_agrees_with_its_own_quantities():
    """In stock is at or above the minimum; Low and On order are below it; surplus has none."""
    problems = []
    for r in _stock():
        on_hand, minimum, status = int(r["on_hand"]), int(r["minimum"]), r["status"]
        if status == "In stock" and on_hand < minimum:
            problems.append(f"{r['code']}: In stock but {on_hand} < {minimum}")
        if status in ("Low", "On order") and on_hand >= minimum:
            problems.append(f"{r['code']}: {status} but {on_hand} >= {minimum}")
        if status == "On order" and not r["next_due"]:
            problems.append(f"{r['code']}: On order with no delivery date")
        if status == "Out of stock" and on_hand != 0:
            problems.append(f"{r['code']}: Out of stock with {on_hand} on hand")
        if (r["kind"] == "surplus") != (status == "Available for reuse"):
            problems.append(f"{r['code']}: kind {r['kind']} with status {status}")
        if r["kind"] == "surplus" and minimum != 0:
            problems.append(f"{r['code']}: surplus with a minimum of {minimum}")
    assert not problems, problems


def test_the_low_lines_the_prose_names_are_exactly_the_lines_below_minimum():
    rows = _stock()
    below = {r["code"] for r in rows if int(r["on_hand"]) < int(r["minimum"])}
    assert len(below) == 5 and {r["status"] for r in rows if r["code"] in below} == {
        "Low",
        "On order",
    }
    text = _need("stock_register.md").read_text(encoding="utf-8")
    assert "Five lines are below their minimum" in text


def test_a_shelf_is_never_counted_in_the_future_and_codes_are_unique():
    rows = _stock()
    counted = [date.fromisoformat(r["last_counted"]) for r in rows]
    assert max(counted) <= AUTHORED
    assert len({r["code"] for r in rows}) == len(rows)


def test_every_stock_accountable_role_is_one_the_directory_names():
    """Roles, never people, and the SAME roles the department directory holds."""
    directory = _find("department_directory.md")
    if not directory.is_file():
        pytest.skip("no department directory in this checkout")
    body = parse_front_matter(directory.read_text(encoding="utf-8"))[1]
    roles = set()
    for _, rows in parse_tables(body):
        roles |= {r.get("accountable_role", "") for r in rows if r.get("accountable_role")}
    assert roles, "the department directory has no accountable_role column"
    owners = {r["accountable_role"] for r in _stock()}
    assert not (owners - roles), f"roles the directory does not know: {sorted(owners - roles)}"


def test_nothing_safety_critical_is_stocked_here():
    """The class comment promises it. Held elsewhere, or not held, and never as ordinary stock."""
    banned = re.compile(
        r"extinguisher|first[- ]aid|defibrillator|\baed\b|emergency light|coshh|chemical|asbestos|"
        r"fire (?:door|alarm|blanket)|sharps|breathing|respirator|harness",
        re.IGNORECASE,
    )
    hits = [
        r["code"]
        for r in _stock()
        if banned.search(" ".join([r["item"], r["used_for"], r["note"], r["category"]]))
    ]
    assert not hits, hits


def test_a_loan_line_says_how_many_are_out_and_never_who_has_them():
    person = re.compile(
        r"@|\b0\d{3}[ ]?\d{3}[ ]?\d{4}\b|\bborrowed by\b|\bloaned to\b", re.IGNORECASE
    )
    for r in _stock():
        if r["kind"] == "loan":
            assert not person.search(" ".join(r.values())), r["code"]


# ── the waste returns register ────────────────────────────────────────────────────────────────

STREAMS = {
    "General waste",
    "Mixed recycling",
    "Paper and card",
    "Food waste",
    "Confidential paper",
    "WEEE",
}


def test_every_month_has_one_line_per_stream_and_no_line_twice():
    rows = _returns()
    seen = set()
    for r in rows:
        key = (r["month"], r["stream"])
        assert key not in seen, key
        seen.add(key)
    months = sorted({r["month"] for r in rows})
    assert months == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    for month in months:
        assert {r["stream"] for r in rows if r["month"] == month} == STREAMS, month


def test_a_period_is_the_calendar_month_it_names():
    import calendar

    for r in _returns():
        y, m = (int(x) for x in r["month"].split("-"))
        assert r["period_start"] == f"{y}-{m:02d}-01", r["code"]
        assert r["period_end"] == f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}", r["code"]


def test_only_a_pending_month_lacks_a_weight_and_a_pending_month_has_no_zero():
    for r in _returns():
        if r["status"] == "Pending":
            assert (
                r["tonnes"] == "" and r["diverted_pct"] == ""
            ), f"{r['code']}: a blank is the finding for a return not yet issued; a zero is a false one"
        else:
            assert float(r["tonnes"]) > 0 and 0 <= float(r["diverted_pct"]) <= 100, r["code"]


def test_only_the_current_month_is_pending():
    pending = {r["month"] for r in _returns() if r["status"] == "Pending"}
    assert pending == {"2026-09"}


def test_an_estimated_weight_and_a_query_are_present_and_stated_in_their_own_note():
    rows = _returns()
    estimated = [r for r in rows if r["weighing"].lower().startswith("estimated")]
    queried = [r for r in rows if r["status"] == "Query"]
    assert len(estimated) == 1 and "estimated" in estimated[0]["note"].lower()
    assert len(queried) == 1 and "invoice" in queried[0]["note"].lower()


def test_the_closing_sentence_states_figures_the_rows_reproduce():
    """The sentence is what gets quoted as the headline, so it is computed, not asserted."""
    rows = _returns()
    issued = [r for r in rows if r["status"] != "Pending"]
    total = sum(float(r["tonnes"]) for r in issued)
    diverted = sum(float(r["tonnes"]) * float(r["diverted_pct"]) / 100 for r in issued)
    aug = [r for r in issued if r["month"] == "2026-08"]
    aug_total = sum(float(r["tonnes"]) for r in aug)
    aug_div = sum(float(r["tonnes"]) * float(r["diverted_pct"]) / 100 for r in aug)
    by_month: Dict[str, float] = {}
    for r in issued:
        by_month[r["month"]] = by_month.get(r["month"], 0.0) + float(r["tonnes"])
    peak = max(by_month, key=by_month.get)

    text = _need("waste_returns_register.md").read_text(encoding="utf-8")
    m = re.search(
        r"\*\*(\d+) entries: .*?The six issued months total ([\d.]+) tonnes, of which ([\d.]+) tonnes "
        r"\(([\d.]+)%\) were diverted from landfill\. August 2026, the latest complete month, was "
        r"([\d.]+) tonnes with ([\d.]+)% diverted; the heaviest month was (\w+ \d{4}) at ([\d.]+) tonnes",
        text,
        re.DOTALL,
    )
    assert m, "the closing sentence no longer states its figures"
    assert int(m.group(1)) == len(rows)
    assert float(m.group(2)) == pytest.approx(total, abs=0.006)
    assert float(m.group(3)) == pytest.approx(diverted, abs=0.006)
    assert float(m.group(4)) == pytest.approx(100 * diverted / total, abs=0.06)
    assert float(m.group(5)) == pytest.approx(aug_total, abs=0.006)
    assert float(m.group(6)) == pytest.approx(100 * aug_div / aug_total, abs=0.06)
    assert m.group(7) == "May 2026" and peak == "2026-05"
    assert float(m.group(8)) == pytest.approx(by_month[peak], abs=0.006)


def test_every_stream_is_one_the_collection_point_register_records():
    """One vocabulary for streams: a return for a stream no bin serves would be a stray."""
    path = _find("waste_collection_register.md")
    if not path.is_file():
        pytest.skip("no waste collection point register in this checkout")
    body = parse_front_matter(path.read_text(encoding="utf-8"))[1]
    recorded = set()
    for _, rows in parse_tables(body):
        recorded |= {r.get("stream_record", "") for r in rows}
    assert STREAMS <= recorded, sorted(STREAMS - recorded)


def test_the_contractor_is_the_one_the_contract_register_names_for_waste():
    path = _find("contract_register.md")
    if not path.is_file():
        pytest.skip("no contract register in this checkout")
    body = parse_front_matter(path.read_text(encoding="utf-8"))[1]
    waste = [
        r for _, rows in parse_tables(body) for r in rows if "waste" in r.get("scope", "").lower()
    ]
    assert waste, "the contract register names no waste contract"
    assert {r["contractor"] for r in _returns()} == {waste[0]["provider"]}
    text = _need("waste_returns_register.md").read_text(encoding="utf-8")
    assert waste[0]["reference"] in text, "the prose must cite the contract by its reference"


def test_recorded_diversion_is_not_below_the_baseline_an_on_track_target_starts_from():
    """SUS-WASTE-2027 is 'On track'. A recorded diversion under its own baseline would say otherwise."""
    path = _find("sustainability_targets.md")
    if not path.is_file():
        pytest.skip("no sustainability target register in this checkout")
    body = parse_front_matter(path.read_text(encoding="utf-8"))[1]
    target = [
        r for _, rows in parse_tables(body) for r in rows if r.get("reference") == "SUS-WASTE-2027"
    ]
    if not target:
        pytest.skip("SUS-WASTE-2027 is no longer in the target register")
    baseline, goal = float(target[0]["baseline_value"]), float(target[0]["target_value"])
    issued = [r for r in _returns() if r["status"] != "Pending"]
    for month in sorted({r["month"] for r in issued}):
        rows = [r for r in issued if r["month"] == month]
        # Weighted by tonnage, never the mean of the stream percentages: the result is a percentage.
        share = sum(float(r["tonnes"]) * float(r["diverted_pct"]) for r in rows) / sum(
            float(r["tonnes"]) for r in rows
        )
        assert (
            baseline <= share <= goal
        ), f"{month}: diverted {share:.1f}% outside {baseline}-{goal}"


# ── both documents ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["stock_register.md", "waste_returns_register.md"])
def test_every_cross_reference_names_a_record_that_exists(name):
    """A note that cites PTW-2026-0417 or CL-2026-011 is a claim about another register."""
    text = _need(name).read_text(encoding="utf-8")
    body = parse_front_matter(text)[1]
    refs = set(
        re.findall(
            r"\b(?:CL-\d{4}-\d{3}|SVC-\d{2}|PTW-\d{4}-\d{4}|AEP-\d{3}|WCP-\d{3}|CON-\d{4}-\d{3})\b",
            body,
        )
    )
    assert refs, f"{name} cites nothing - expected cross-references to the existing registers"
    corpus = ""
    for doc in (REPO / "input" / "documents", *REPO.glob("*/documents")):
        if doc.is_dir():
            for path in doc.glob("*.md"):
                if path.name != name:
                    corpus += path.read_text(encoding="utf-8", errors="replace")
    if not corpus:
        pytest.skip("no other register documents in this checkout")
    missing = sorted(r for r in refs if r not in corpus)
    assert not missing, f"{name} cites records no other register holds: {missing}"


@pytest.mark.parametrize("name", ["stock_register.md", "waste_returns_register.md"])
def test_the_body_never_calls_the_data_fake_and_the_front_matter_still_declares_it(name):
    text = _need(name).read_text(encoding="utf-8")
    front, body = parse_front_matter(text)
    assert front.get("simulated") is True
    assert not _FAKE_WORDS.search(body), _FAKE_WORDS.search(body).group(0)


@pytest.mark.parametrize("name", ["stock_register.md", "waste_returns_register.md"])
def test_no_row_names_a_room_or_a_person(name):
    """Not room-bound (the room identity correction is held back and would change every room
    name), and roles rather than people."""
    text = _need(name).read_text(encoding="utf-8")
    body = parse_front_matter(text)[1]
    assert not re.search(
        r"\bRoom\s+\d", body
    ), "a room number would need the held-back room cascade"
    assert not re.search(r"@|\b\d{3}\s?\d{4}\s?\d{4}\b", body)


@pytest.mark.parametrize("name", ["stock_register.md", "waste_returns_register.md"])
def test_the_date_rolling_tool_leaves_these_registers_where_they_are(name):
    """refresh_record_dates rolls CADENCED obligations forward. A shelf count, a delivery date
    and a month's return are dated facts, so a run a month later must not rewrite them: moving
    a count date would record a count that never happened."""
    from datetime import datetime

    from scripts.refresh_record_dates import Report, load_mappings, refresh_register

    path = _need(name)
    changed = refresh_register(
        path, load_mappings(MAPPINGS), datetime(2026, 10, 30, 12, 0), Report()
    )
    assert changed is None or changed == path.read_text(
        encoding="utf-8"
    ), f"{name} would be rewritten by scripts/refresh_record_dates.py"
