# -*- coding: utf-8 -*-
"""The capture must read the key the API actually writes (the sixth apparatus bug).

`/chat` returns two evidence fields and they are different objects:

    "evidence"        — the older evidence DOSSIER, present on ~3% of answers, no gates on it
    "evidence_record" — the V6-T02 EvidenceRecord, which carries `gates_applied` and `status`

The capture read `evidence`. So `gates` and `answer_status` were empty on every row of every
capture ever taken — verified at 309/309 and 306/306 — and the regression gate's entire
discriminator is:

    a worsened answer is a TIGHTENING when a gate fired, and a REGRESSION when none did

With the column unconditionally empty, "no gate fired" was always true, so **every intended
tightening was classified as breakage**. The 0.55 retrieval-floor run reported 8 blocking
regressions that live probes show to be the floor working exactly as designed.

Same shape as BUG-236: one side writes `evidence_record`, the other reads `evidence`, and the
mismatch degrades to a plausible empty value rather than raising. Pinned here because a
cross-file key agreement is invisible from either file alone.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CAPTURE = (REPO / "scripts" / "capture_golden_baseline.py").read_text(encoding="utf-8")
MAIN = (REPO / "orchestrator" / "main.py").read_text(encoding="utf-8")


def test_the_api_still_writes_the_key_the_capture_reads():
    """If this changes, everything else in this file is testing the wrong contract."""
    assert '"evidence_record": updated_state.intermediate_results.get("evidence_record")' in MAIN


def test_the_capture_reads_evidence_record_not_evidence():
    assert 'data.get("evidence_record")' in CAPTURE, (
        "the capture is reading the dossier again — gates and answer_status will be empty on "
        "every row and every tightening will be reported as a regression"
    )
    assert 'ev = data.get("evidence")' not in CAPTURE


def test_gates_and_status_come_off_that_record():
    block = CAPTURE[CAPTURE.index('ev = data.get("evidence_record")') :][:1400]
    assert 'ev.get("gates_applied")' in block
    assert 'ev.get("status")' in block


def test_the_sha_excludes_fields_that_change_every_run():
    """`retrieved_at` is literally "now". Hashing it makes every sha differ by construction and
    say nothing about whether the evidence changed — the mistake BUG-184 was, where `plan_hash`
    was compared across runs when it could not be stable."""
    block = CAPTURE[CAPTURE.index("ev_sha = ") :][:800]
    for volatile in ("retrieved_at", "latest_evidence_at"):
        assert volatile in block, f"{volatile} is not excluded from the evidence sha"


def test_the_dossier_and_the_record_are_not_the_same_thing():
    """Both are returned, under adjacent names, on the same payload. That is precisely why one
    was read for the other, so the distinction is asserted rather than assumed."""
    assert '"evidence": updated_state.intermediate_results.get("evidence_dossier")' in MAIN
    assert re.search(r'"evidence_record":\s*updated_state', MAIN)


# ── every suppressor must name itself ────────────────────────────────────────

AGENT = (REPO / "orchestrator" / "agents" / "capability_agent.py").read_text(encoding="utf-8")


def test_the_retrieval_floor_names_itself():
    assert '"retrieval_floor"' in AGENT


def test_the_on_topic_guard_names_itself_too():
    """Two things suppress a document answer and only one of them used to say so.

    On the 0.55 floor run, 3 of 8 blocking findings were the on-topic guard rather than the
    floor: "which anchor points are certified for the abseil window clean" scores 0.5749 and
    clears the 0.55 floor outright, then the guard removes the HVAC CO2 table it retrieved —
    BUG-218's own motivating example, behaving correctly and reported as a regression purely
    for want of a name.
    """
    assert '"grounding_guard"' in AGENT, (
        "the on-topic guard suppresses answers without declaring a gate, so the regression "
        "gate cannot tell its tightenings from breakage"
    )
    block = AGENT[AGENT.index("_before_guard = len(doc_hits)") :][:1400]
    assert "if _before_guard and not doc_hits:" in block, (
        "the guard must declare only when it removed EVERYTHING — a partial filter leaves a "
        "document answer standing and is not a suppression"
    )


def test_both_suppressors_write_to_the_same_evidence_partial():
    """They must land on the key the assembler reads, or naming themselves achieves nothing."""
    for marker in ('"retrieval_floor"', '"grounding_guard"'):
        i = AGENT.index(marker)
        window = AGENT[max(0, i - 700) : i + 200]
        assert 'setdefault("evidence", {})' in window, f"{marker} does not reach the record"


def test_every_declared_column_is_actually_written():
    """csv.DictWriter fills a missing key with "" and says nothing, so a column can be declared,
    extracted, and never written — which is exactly what happened to `gates_advisory`: it was
    added to FIELDS and to the _ask return, omitted from the row dict in the main loop, and
    produced an empty column across a full 316-question run that read as "no gate would change
    anything". Same shape as BUG-238 one layer down: one side writes, the other doesn't read,
    and the gap degrades to a plausible value instead of an error.
    """
    fields_block = CAPTURE[CAPTURE.index("FIELDS") : CAPTURE.index("FIELDS") + 900]
    declared = set(re.findall(r'^\s+"(\w+)",\s*$', fields_block, re.M))
    assert "gates_advisory" in declared, "the column is not declared any more"

    row_block = CAPTURE[CAPTURE.index("w.writerow(") :]
    row_block = row_block[: row_block.index("fh.flush()")]
    written = set(re.findall(r'"(\w+)":', row_block))
    missing = declared - written
    assert not missing, (
        f"declared in FIELDS but never written to the row: {sorted(missing)} — DictWriter will "
        "emit these as empty strings on every row, silently"
    )
