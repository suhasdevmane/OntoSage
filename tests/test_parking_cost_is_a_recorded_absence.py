# -*- coding: utf-8 -*-
"""A parking price is recorded or it is absent — it is never written into prose (W3-03).

THE QUESTION. "How much does it cost to park here for a day?" (evidence pack #67) declines,
and the tracker row asked whether to add the tariff. Every record bldg1 holds was read on
2026-09-29 before deciding:

    ontosage:Tariff     4 instances, all utilities — electricity 2026 and 2025, gas, water.
                        No parking tariff.
    ontosage:CostLine   24 lines, all operating SPEND (electricity supply, cleaning contract,
                        lift maintenance, security staffing ...). A ledger of what the
                        building pays out. Not a price list; it could not hold a visitor
                        tariff whatever was added to it, so a decline that points a visitor
                        at it is pointing at the wrong record.
    documents/*.md      no parking charge. The one parking row is the stakeholder register's
                        car park attendant — "barrier state, permits, accessible bays, EV
                        chargers". Permits, not payment.
    Cap_transport_parking  the only record that speaks to paying to park, and it names an
                        ARRANGEMENT, not a rate: the university car park on Corbett Road
                        requires a permit for staff; on-street parking nearby is
                        pay-and-display.

So the honest outcome is a recorded absence, not a tariff. The owner has never said Abacws
has paid parking, and a number invented here would be read out to someone standing at a
barrier. The schema already settles it — ``ontosage:Tariff``'s own comment: "An invented unit
rate produces a confident wrong number, which is the failure mode this project guards against
hardest — so with no Tariff the honest answer is a decline that names the missing source."

WHAT THIS TEST PINS, and why it is not a bldg1 assertion. A building that DOES charge for
parking must be able to say so. What must never happen is a price appearing in prose with no
registered rate behind it, or a parking area that quietly says nothing about cost while the
question keeps being asked. Both are checked for whatever buildings the repo holds, so a
building with a real tariff passes by having one.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

rdflib = pytest.importorskip("rdflib")

REPO = Path(__file__).resolve().parent.parent

ONTOSAGE = "http://ontosage.org/capabilities#"
PARKING_AREA = rdflib.URIRef(ONTOSAGE + "ParkingArea")
TARIFF = rdflib.URIRef(ONTOSAGE + "Tariff")
COST_LINE = rdflib.URIRef(ONTOSAGE + "CostLine")
ANSWER_TEXT = rdflib.URIRef(ONTOSAGE + "answerText")
RDFS_LABEL = rdflib.URIRef("http://www.w3.org/2000/01/rdf-schema#label")

#: A money figure: "£3.50", "3.50 GBP", "$4", "4.00 per day". Deliberately loose — this is a
#: tripwire, and a false positive costs one reading of the line that tripped it.
_MONEY_RE = re.compile(
    r"[£$€]\s?\d|\b\d+(?:\.\d{1,2})?\s*(?:gbp|usd|eur|p|pence|pounds?)\b"
    r"|\b\d+(?:\.\d{1,2})?\s*(?:per|a|an|each)\s+(?:day|hour|week|month)\b",
    re.IGNORECASE,
)

#: Words that mean "paying to park", as opposed to a free BAY being available.
_CHARGE_WORDS = ("charge", "tariff", "cost", "fee", "price", "pay", "paid")

#: How the absence must be stated when nothing backs a rate. Any ONE of these reads as a
#: statement about the records rather than a silence.
_ABSENCE_PHRASES = (
    "no parking charge is recorded",
    "no charge is recorded",
    "no parking tariff",
    "cannot be quoted",
)


def _building_folders():
    """The active building (input/) plus every parked one, as the loaders resolve them."""
    folders = [REPO / "input"]
    folders += [
        d for d in sorted(REPO.glob("bldg[0-9]")) if d.is_dir() and (d / "building.yaml").exists()
    ]
    return [d for d in folders if d.is_dir()]


def _graph_for(folder: Path):
    """Every per-building TTL in one graph, skipping any file that will not parse.

    A file that does not parse is another test's failure (the TTL prefix check); swallowing
    it here keeps one broken file from reporting itself as a parking defect.
    """
    graph = rdflib.Graph()
    for path in sorted(folder.glob("bldg[0-9]_*.ttl")):
        if any(t in path.name.lower() for t in ("brick", "rec", "s223", "schema")):
            continue
        try:
            graph.parse(str(path), format="turtle")
        except Exception:
            continue
    return graph


def _parking_areas(graph):
    return list(graph.subjects(rdflib.RDF.type, PARKING_AREA))


def _a_registered_rate_covers_parking(graph) -> bool:
    """True when the BUILDING has actually registered a parking rate somewhere."""
    for cls in (TARIFF, COST_LINE):
        for subject in graph.subjects(rdflib.RDF.type, cls):
            text = " ".join(
                str(o) for o in graph.objects(subject, None) if isinstance(o, rdflib.Literal)
            ).lower()
            if "park" in text:
                return True
    return False


FOLDERS = _building_folders()


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_a_parking_area_without_a_registered_rate_says_so(folder):
    """The absence is STATED, not left as a search that came up empty.

    Before this, the question reached the cost register — 24 lines of operating spend — and
    was declined against a record that could never have held the answer, while the building's
    own transport record said what the arrangement actually is.
    """
    graph = _graph_for(folder)
    areas = _parking_areas(graph)
    if not areas:
        pytest.skip(f"{folder.name} declares no ontosage:ParkingArea")
    if _a_registered_rate_covers_parking(graph):
        pytest.skip(f"{folder.name} registers a parking rate; the absence rule does not apply")
    for area in areas:
        prose = " ".join(str(o) for o in graph.objects(area, ANSWER_TEXT)).lower()
        assert prose, f"{area} has no ontosage:answerText, so it can state nothing at all"
        assert any(p in prose for p in _ABSENCE_PHRASES), (
            f"{area} records a parking area with no registered rate behind it and does not "
            f"say so. 'How much does it cost to park here for a day?' then declines against "
            f"whatever register a word match happens to reach. State the absence: "
            f"one of {_ABSENCE_PHRASES}"
        )


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_no_parking_price_is_written_into_prose(folder):
    """A rate belongs in an ontosage:Tariff, with its authority and its validity period.

    A figure in prose has no authority, no period and no way to expire. This is the guard
    against the specific failure W3-03 exists to prevent: a helpful session filling in a
    plausible daily rate for a real building whose owner has never quoted one.
    """
    graph = _graph_for(folder)
    offenders = []
    for subject, _p, value in graph.triples((None, None, None)):
        if not isinstance(value, rdflib.Literal):
            continue
        text = str(value)
        low = text.lower()
        if "park" not in low or not any(w in low for w in _CHARGE_WORDS):
            continue
        # Only the sentence about parking is judged; a long record may carry other figures.
        for sentence in re.split(r"(?<=[.;])\s+", text):
            s_low = sentence.lower()
            if "park" in s_low and any(w in s_low for w in _CHARGE_WORDS):
                if _MONEY_RE.search(sentence):
                    offenders.append((str(subject), sentence.strip()))
    assert not offenders, (
        "a parking price is stated in prose with no ontosage:Tariff behind it:\n  "
        + "\n  ".join(f"{s}: {t}" for s, t in offenders)
        + "\nIf the owner confirmed a rate, register it as an ontosage:Tariff with its "
        "authority and validity period. If they did not, remove it."
    )


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_the_cost_register_is_spend_not_a_price_list(folder):
    """Named so the next reader does not "fix" the decline by adding a parking cost line.

    The register lives in ``documents/cost_line_register.md`` — a record document with a
    named owner ("Estates Finance Business Partner") and a named authority ("Cardiff
    University Finance — Estates ledger extract"). A visitor tariff written into it would be
    attributed to that authority, and it carries budget / actual / committed / accrued, so it
    would also be read back as money the building SPENDS: every total that sums the register
    would be wrong by the amount of it.
    """
    register = folder / "documents" / "cost_line_register.md"
    if not register.exists():
        pytest.skip(f"{folder.name} holds no cost register")
    text = register.read_text(encoding="utf-8", errors="replace")
    offending = [
        line
        for line in text.splitlines()
        if "park" in line.lower()
        and any(w in line.lower() for w in ("tariff", "charge", "fee", "visitor", "price"))
    ]
    assert not offending, (
        "a parking PRICE has been filed in the building's expenditure ledger:\n  "
        + "\n  ".join(offending)
        + "\nA rate is an ontosage:Tariff; this register is what the building spends."
    )


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_no_parking_price_is_written_into_a_record_document(folder):
    """The same tripwire over the record documents, which is where the registers live.

    ``documents/*.md`` are ingested into named graphs and answered from by record id, so a
    figure typed here is quoted with an owner's name attached to it. The tariff register's own
    text states the rule this enforces: "Where no tariff covers a period, no cost is stated —
    an assumed rate produces a confident wrong number."
    """
    docs = folder / "documents"
    if not docs.is_dir():
        pytest.skip(f"{folder.name} ships no record documents")
    offenders = []
    for path in sorted(docs.glob("*.md")):
        for n, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            low = line.lower()
            if "park" not in low or not any(w in low for w in _CHARGE_WORDS):
                continue
            # "EV charger", "charger fault" are equipment, not a price; the money pattern
            # is what decides, and these carry none.
            if _MONEY_RE.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "a parking charge appears in a record document with no registered tariff behind "
        "it:\n  " + "\n  ".join(offenders)
    )
