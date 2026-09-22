# -*- coding: utf-8 -*-
"""Rows added where demand outruns data (row 2D-11 follow-up).

`docs/REACH_2026-09-19.md` section 3.2 ranks the held registers by questions per record: a
register with many questions and few records is the cheapest data to add. Three were extended,
each with placeholders DERIVED from what the building already states rather than invented:

* `SustainabilityTarget` 5 -> 8: a recycling target tied to the waste returns, a travel target and
  a paper target. The recycling row's status must agree with the recorded recycled share.
* `PublicEvent` 12 -> 17: Mathematics events beside the Computer Science ones (the building houses
  both schools), in venues the register already uses, never double-booked.
* `ClosurePeriod` 3 -> 10 (a new TTL): the planned carpet deep cleans fall on the days the planned
  maintenance schedule says they are due, plus the bank holiday and Christmas closure the building's
  working-hours topic describes. No lift, entrance, escape route or plant is closed.

`WorkspaceProfile` (ranked second) was NOT extended: every seminar, meeting and laboratory room in
the graph is one of the 132 whose identity the held-back room correction changes, and the 84 rooms
it leaves alone are private academic offices. `AccessibleRoute` (ranked fourth) was not extended
either: a wrong step-free route strands a person, so it needs a survey, not a placeholder.
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

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
NS = "http://example.org/building#"
TODAY = date(2026, 9, 18)


def _find(name):
    for path in [REPO / "input" / "documents" / name, *sorted(REPO.glob(f"*/documents/{name}"))]:
        if path.is_file():
            return path
    pytest.skip(f"{name} is in no building folder of this checkout")


def _rows(name, heading):
    body = parse_front_matter(_find(name).read_text(encoding="utf-8"))[1]
    for h, rows in parse_tables(body):
        if heading in h.lower():
            return rows
    raise AssertionError(f"{name}: no table under {heading!r}")


# ── sustainability targets ─────────────────────────────────────────────────────────────────


def test_the_target_register_lifts_and_holds_eight_targets():
    result = lift_document(_find("sustainability_targets.md"), NS, MAPPINGS)
    assert not result.errors, result.errors[:3]
    assert result.instances == 8


def test_every_target_carries_a_baseline_a_future_date_and_an_authority():
    for r in _rows("sustainability_targets.md", "target register"):
        assert float(r["baseline_value"]) > 0 and float(r["target_value"]) > 0, r["reference"]
        assert date.fromisoformat(r["target_date"]) > TODAY, r["reference"]
        assert r["authority"] and r["baseline_period"], r["reference"]


def test_the_recycling_target_agrees_with_the_recycled_share_the_returns_record():
    """A target 'At risk' must not sit beside a recorded share that has already met it, and a share
    below its own baseline would say the target is worse than 'At risk'."""
    target = next(
        r
        for r in _rows("sustainability_targets.md", "target register")
        if r["reference"] == "SUS-RECYCLE-2027"
    )
    returns = [
        r
        for r in _rows("waste_returns_register.md", "waste returns register")
        if r["status"] != "Pending"
    ]
    total = sum(float(r["tonnes"]) for r in returns)
    recycled = sum(float(r["tonnes"]) for r in returns if r["stream"] != "General waste")
    share = 100 * recycled / total
    assert float(target["baseline_value"]) < share < float(target["target_value"]), share
    assert target["status"] == "At risk"


# ── public events ──────────────────────────────────────────────────────────────────────────


def _events():
    return _rows("public_event_register.md", "public event register")


def test_the_event_register_lifts_and_holds_seventeen_events():
    result = lift_document(_find("public_event_register.md"), NS, MAPPINGS)
    assert not result.errors, result.errors[:3]
    assert result.instances == 17


def test_no_event_starts_before_its_doors_or_ends_before_it_starts():
    for e in _events():
        assert e["doors_open"] <= e["starts"] < e["ends"], e["event"]


def test_no_venue_is_held_by_two_scheduled_events_at_overlapping_times():
    live = [e for e in _events() if e["status"] in ("scheduled", "moved")]
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            if a["venue"] == b["venue"] and a["date"] == b["date"]:
                assert a["ends"] <= b["starts"] or b["ends"] <= a["starts"], (
                    a["event"],
                    b["event"],
                )


def test_event_codes_are_unique_and_the_new_ones_follow_on():
    codes = [e["event"] for e in _events()]
    assert len(set(codes)) == len(codes)
    assert codes[-1] == "EVT-2026-0057" and "EVT-2026-0053" in codes


def test_the_new_events_use_only_venues_the_register_already_used():
    old = {e["venue"] for e in _events() if e["event"] <= "EVT-2026-0052"}
    new = {e["venue"] for e in _events() if e["event"] > "EVT-2026-0052"}
    assert new <= old, sorted(new - old)


def test_the_building_houses_two_schools_and_the_events_say_so():
    titles = " ".join(e["title"] for e in _events())
    assert "School of Computer Science" in titles and "Mathematics" in titles


# ── planned closures ───────────────────────────────────────────────────────────────────────


def _closures():
    from rdflib import Graph

    ttl = REPO / "input" / "bldg1_closures_planned.ttl"
    if not ttl.is_file():
        for path in sorted(REPO.glob("*/bldg1_closures_planned.ttl")):
            ttl = path
    if not ttl.is_file():
        pytest.skip("bldg1_closures_planned.ttl is in no building folder of this checkout")
    g = Graph()
    g.parse(str(ttl), format="turtle")
    q = """PREFIX o: <http://ontosage.org/capabilities#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?s ?label ?on ?why ?a ?b WHERE {
      ?s a o:ClosurePeriod ; rdfs:label ?label ; o:appliesTo ?on ; o:closureReason ?why ;
         o:startedAt ?a ; o:endedAt ?b }"""
    return [
        {
            "iri": str(r.s).rsplit("#", 1)[-1],
            "label": str(r.label),
            "on": str(r.on).rsplit("#", 1)[-1],
            "why": str(r.why),
            "a": datetime.fromisoformat(str(r.a)),
            "b": datetime.fromisoformat(str(r.b)),
        }
        for r in g.query(q)
    ]


def test_seven_closures_parse_and_each_ends_after_it_starts():
    """The `sim` assertion went with D1 (2026-09-22): a closure is a closure."""
    rows = _closures()
    assert len(rows) == 7
    for c in rows:
        assert c["b"] > c["a"], c["iri"]


def test_each_carpet_closure_falls_on_or_after_the_day_its_service_is_due():
    schedule = {r["code"]: r for r in _rows("service_schedules.md", "planned service schedule")}
    for c in _closures():
        m = re.search(r"\((?:planned maintenance )?(SVC-\d+)\)", c["why"])
        if not m:
            continue
        due = date.fromisoformat(schedule[m.group(1)]["next_due"])
        assert timedelta(0) <= c["a"].date() - due <= timedelta(days=30) or c["a"].date() == due, (
            c["iri"],
            due,
        )
        assert "carpet" in schedule[m.group(1)]["task"].lower()


def test_the_floor_a_closure_names_is_the_floor_the_schedule_names():
    schedule = {
        r["code"]: r["scope"] for r in _rows("service_schedules.md", "planned service schedule")
    }
    for c in _closures():
        m = re.search(r"(SVC-\d+)", c["why"])
        if m and c["on"].startswith("Floor"):
            assert re.search(rf"\b{c['on'][5:]}\b", schedule[m.group(1)]), (
                c["iri"],
                schedule[m.group(1)],
            )


def test_no_closure_touches_a_lift_an_entrance_an_escape_route_or_plant():
    banned = re.compile(
        r"lift|entrance|escape|fire|plant|generator|boiler|chiller|stair", re.IGNORECASE
    )
    for c in _closures():
        assert not banned.search(c["label"] + " " + c["why"]), c["iri"]


def test_a_floor_is_not_closed_twice_at_once_including_the_closures_already_held():
    existing = REPO / "input" / "bldg1_synthetic_hours.ttl"
    text = existing.read_text(encoding="utf-8") if existing.is_file() else ""
    old = re.findall(
        r"ontosage:appliesTo bldg:(Floor\d).*?startedAt \"([^\"]+)\".*?endedAt \"([^\"]+)\"",
        text,
        re.S,
    )
    spans = [(f, datetime.fromisoformat(a), datetime.fromisoformat(b)) for f, a, b in old] + [
        (c["on"], c["a"], c["b"]) for c in _closures()
    ]
    for i, (fa, a1, b1) in enumerate(spans):
        for fb, a2, b2 in spans[i + 1 :]:
            if fa == fb:
                assert b1 <= a2 or b2 <= a1, (fa, a1, a2)
