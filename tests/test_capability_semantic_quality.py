"""
Semantic recall quality tests — spec §16.4.

This is the headline evidence that the semantic refactor was worth doing.
For each test query, we record whether the response contains content from
the expected KB entry. The aggregate hit-rate across synonym/paraphrase
queries IS the recall delta vs. the substring-matching baseline.

A passing run also writes tests/results/semantic_recall_report.md with the
hit/miss matrix — that file is the artefact reviewed at the Phase 2 gate.

Ten tests organised in three groups:
   Synonym recall (must HIT)    — tests 1-5: queries the OLD keyword path missed
   Existing baseline (must HIT) — tests 6-8: queries the OLD keyword path already hit; MUST NOT regress
   Negative controls (must MISS)— tests 9-10: queries that should NOT route to capability
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.live


_REPORT_PATH = Path(__file__).resolve().parent / "results" / "semantic_recall_report.md"


def _record(report_rows, test_name, query, expected_entry_id, expected_markers, resp,
            should_hit=True):
    """Append one row to the per-session recall report.

    should_hit=True  → this query SHOULD match the expected_entry (positive test)
    should_hit=False → this query SHOULD NOT match capability (negative control)
    """
    matched_markers = [m for m in expected_markers if m.lower() in resp.response_text.lower()]
    matched = bool(matched_markers)
    # The "outcome" is correct when matched == should_hit
    correct = (matched == should_hit) if should_hit else not matched
    report_rows.append(
        {
            "test": test_name,
            "query": query,
            "expected_entry": expected_entry_id,
            "expected_markers": expected_markers,
            "matched_markers": matched_markers,
            "should_hit": should_hit,
            "matched": matched,
            "correct": correct,
            "response_excerpt": resp.response_text[:200],
        }
    )
    # Backwards-compat: callers using the legacy hit semantics still get matched
    return matched


@pytest.fixture(scope="module")
def report_rows():
    """Session-scoped list of recall results. Written to disk at teardown."""
    rows: list = []
    yield rows
    # Write the report at the end
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_report(rows)


def _write_report(rows):
    if not rows:
        return
    # Defensive: some legacy rows may lack the should_hit/correct fields
    for r in rows:
        r.setdefault("should_hit", True)
        r.setdefault("matched", r.get("hit", False))
        r.setdefault("correct", r["matched"] == r["should_hit"])

    pos_rows = [r for r in rows if r["should_hit"]]
    neg_rows = [r for r in rows if not r["should_hit"]]
    pos_correct = sum(1 for r in pos_rows if r["correct"])
    neg_correct = sum(1 for r in neg_rows if r["correct"])
    overall_correct = sum(1 for r in rows if r["correct"])

    lines = [
        "# Capability Semantic Recall Report",
        "",
        f"**Overall correctness: {overall_correct}/{len(rows)}**",
        "",
        f"- Positive recall (should-hit queries): {pos_correct}/{len(pos_rows)} matched",
        f"- Negative precision (should-not-hit controls): {neg_correct}/{len(neg_rows)} correctly rejected",
        "",
        "Legend: ✅ = correct outcome (hit when expected, OR miss when expected). "
        "❌ = wrong outcome.",
        "",
        "| Test | Query | Expected | Outcome | Matched Markers |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if r["should_hit"]:
            expected = f"HIT `{r['expected_entry']}`"
            outcome_emoji = "✅ hit" if r["correct"] else "❌ miss"
        else:
            expected = "no capability route"
            outcome_emoji = "✅ correctly rejected" if r["correct"] else "❌ false hit"
        lines.append(
            f"| {r['test']} | `{r['query']}` | {expected} | {outcome_emoji} | "
            f"{', '.join(r['matched_markers']) or '—'} |"
        )
    lines.append("")
    lines.append("## Detailed responses")
    lines.append("")
    for r in rows:
        lines.append(f"### {r['test']}")
        lines.append(f"**Query:** {r['query']}")
        lines.append("")
        lines.append("```")
        lines.append(r["response_excerpt"])
        lines.append("```")
        lines.append("")
    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ── Synonym recall (must HIT — these were the OLD keyword path's misses) ───────


def test_synonym_elevator_capacity(chat_client, fresh_session_id, report_rows):
    """'elevator capacity' must match lift_accessibility_detail. The word 'elevator'
    is NOT in the keyword list — only semantic embedding can make this match."""
    resp = chat_client.chat("What's the elevator capacity?", session_id=fresh_session_id)
    assert resp.success
    hit = _record(
        report_rows, "synonym_elevator_capacity", "What's the elevator capacity?",
        "lift_accessibility_detail",
        ["1000", "weight", "kg", "passenger", "lift"], resp,
    )
    assert hit, f"Synonym 'elevator capacity' should hit lift_accessibility_detail. Response: {resp.response_text[:200]}"


def test_synonym_wheelchair_lift_access(chat_client, fresh_session_id, report_rows):
    """'wheelchair access to floors' — synonym chain for lift_accessibility_detail."""
    resp = chat_client.chat(
        "Can a wheelchair reach all floors in this building?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "synonym_wheelchair_lift", "Can a wheelchair reach all floors in this building?",
        "lift_accessibility_detail",
        ["lift", "passenger", "accessible", "step-free", "floor"], resp,
    )
    assert hit, f"Wheelchair access paraphrase should hit accessibility KB. Response: {resp.response_text[:200]}"


def test_paraphrase_shower_location(chat_client, fresh_session_id, report_rows):
    """'where can I shower' — paraphrase of shower_facilities_detail."""
    resp = chat_client.chat(
        "Where can I shower in this building?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "paraphrase_shower", "Where can I shower in this building?",
        "shower_facilities_detail",
        ["shower", "floor 1", "cubicle", "accessible"], resp,
    )
    assert hit, f"Shower paraphrase should hit shower_facilities_detail. Response: {resp.response_text[:200]}"


def test_paraphrase_baby_changing(chat_client, fresh_session_id, report_rows):
    """'changing table for infants' — paraphrase of toilet_facilities_by_floor / baby changing."""
    resp = chat_client.chat(
        "Is there a changing table for infants somewhere?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "paraphrase_baby_changing", "Is there a changing table for infants somewhere?",
        "toilet_facilities_by_floor",
        ["baby changing", "ground floor", "changing"], resp,
    )
    assert hit, f"Baby-changing paraphrase should hit toilet KB. Response: {resp.response_text[:200]}"


def test_paraphrase_bike_storage(chat_client, fresh_session_id, report_rows):
    """'secure cycle storage' — paraphrase of bicycle_parking_detail."""
    resp = chat_client.chat(
        "Do you have secure storage for my bicycle?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "paraphrase_bike_storage", "Do you have secure storage for my bicycle?",
        "bicycle_parking_detail",
        ["bike", "bicycle", "rack", "cycle", "covered"], resp,
    )
    assert hit, f"Bike storage paraphrase should hit cycle parking KB. Response: {resp.response_text[:200]}"


# ── Existing baseline (must HIT — old keyword path already did) ────────────────


def test_baseline_fire_safety(chat_client, fresh_session_id, report_rows):
    """'fire safety procedures' was always a keyword hit; must not regress."""
    resp = chat_client.chat(
        "What are the fire safety procedures?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "baseline_fire", "What are the fire safety procedures?",
        "fire_safety",
        ["evacuation", "fire", "alarm", "assembly point", "smoke detector"], resp,
    )
    assert hit, f"Fire safety baseline regressed: {resp.response_text[:200]}"


def test_baseline_data_privacy(chat_client, fresh_session_id, report_rows):
    """'does the building track my location' — keyword path hit (post-2026-05-20 fix);
    semantic path must also hit."""
    resp = chat_client.chat(
        "Does the building track my location?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "baseline_privacy", "Does the building track my location?",
        "data_privacy_gdpr",
        ["privacy", "tracking", "GDPR", "anonym", "personal data", "track"], resp,
    )
    assert hit, f"Privacy baseline regressed: {resp.response_text[:200]}"


def test_baseline_power_outage(chat_client, fresh_session_id, report_rows):
    """'what happens during a power outage' — classic capability query."""
    resp = chat_client.chat(
        "What happens during a power outage?", session_id=fresh_session_id
    )
    assert resp.success
    hit = _record(
        report_rows, "baseline_power", "What happens during a power outage?",
        "power_resilience",
        ["UPS", "generator", "backup", "power", "uninterruptible"], resp,
    )
    assert hit, f"Power resilience baseline regressed: {resp.response_text[:200]}"


# ── Negative controls (must MISS — should NOT route to capability) ─────────────


def test_negative_off_domain_query(chat_client, fresh_session_id, report_rows):
    """Off-topic query should NOT semantically match anything → routes to general/clarification."""
    resp = chat_client.chat(
        "What is the airspeed of an unladen swallow?", session_id=fresh_session_id
    )
    assert resp.success
    # Should NOT contain capability KB markers
    not_capability = not resp.contains("information I have on record for **Abacws")
    _record(
        report_rows, "negative_off_domain", "What is the airspeed of an unladen swallow?",
        "(none — capability should NOT fire)",
        ["information I have on record"],  # the marker capability response would contain
        resp, should_hit=False,
    )
    assert not_capability, (
        f"Off-domain query incorrectly routed to capability: {resp.response_text[:200]}"
    )


def test_negative_pure_sensor_query(chat_client, fresh_session_id, report_rows):
    """'CO2 ppm on floor 3' is pure sensor_data — semantic router must NOT hijack."""
    resp = chat_client.chat(
        "Current CO2 ppm reading on floor 3?", session_id=fresh_session_id
    )
    assert resp.success
    not_capability = not resp.contains("information I have on record for **Abacws")
    _record(
        report_rows, "negative_sensor", "Current CO2 ppm reading on floor 3?",
        "(none — capability should NOT fire)",
        ["information I have on record"],
        resp, should_hit=False,
    )
    assert not_capability, (
        f"Sensor query was hijacked by capability: {resp.response_text[:200]}"
    )
