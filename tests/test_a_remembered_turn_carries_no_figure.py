# -*- coding: utf-8 -*-
"""W5-01 — the rolling session summary compresses old turns and states no measurement.

WHAT WAS MEASURED, AND WHY THIS FILE EXISTS
-------------------------------------------
Read from the source on 2026-09-29, before any change: ``TurnMemoryService.get_older_context``
ran ``ORDER BY turn_index DESC OFFSET 20 LIMIT 30``. At turn 60 that returns turns 40 down to
11, so **turns 1-10 were dropped with no trace** — the tracker's acceptance for W5-01 ("a
60-turn conversation still answers a question about turn 3") could not be met by construction,
and nothing said so, because the block that came back looked perfectly healthy.

The second defect is the one worth a whole test file. Each of those older lines carried
``result_summary[:150]``, and ``_extract_result_summary`` fills ``result_summary`` from the
analytics lane's ``formatted_response`` — the ANSWER, verbatim, measurements included. The
existing pin for that behaviour asserted it as correct: ``test_conversation_memory_e2e.py``
required ``"22.3" in ctx`` for a row reading ``"Room 5.02: 22.3 deg C current reading"``. So a
figure produced twenty turns earlier was fed back into the prompt with no time basis and no
statement that it was stale. Design contract #4: a remembered number restated as current is a
fabrication, and it is the kind that reads perfectly.

The guarantee these tests pin is structural, not a filter. ``TurnNote`` has no field for the
answer. The only thing an answer may contribute is one token from ``OUTCOMES``. A redactor
can have a hole; an absent field cannot — which is why the measurement tests below are a
second line and not the first.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.services import session_summary as ss
from orchestrator.services.publication_gate import (
    has_quantitative_claim,
    redact_quantities,
)

pytestmark = pytest.mark.unit


def _row(turn_index: int, question: str, intent: str = "sensor_data", answer: str = "ok"):
    return {
        "turn_index": turn_index,
        "user_query": question,
        "intent": intent,
        "result_summary": answer,
    }


def _notes(rows):
    return [ss.note_from_row(r) for r in rows]


def _conversation(n: int, answer: str = "The reading is 1,240 ppm."):
    """A conversation of ``n`` turns, each about a different room."""
    return [_row(i, f"what is the co2 in room 5.{i:02d}", answer=answer) for i in range(1, n + 1)]


# ── nothing from an ANSWER may appear, except one word ──────────────────────────────────


def test_a_past_answers_numbers_never_reach_the_summary():
    """The exact defect: a figure from turn 1's ANSWER, recalled at turn 60."""
    rows = _conversation(60, answer="Room 5.02 is 22.3 deg C and 1,240 ppm right now.")
    block = ss.build(_notes(rows))
    assert "22.3" not in block
    assert "1,240" not in block
    assert "deg C" not in block


def test_the_only_thing_an_answer_contributes_is_a_closed_vocabulary_token():
    """Every outcome in the rendered block is one of three words, whatever the answer said."""
    rows = [
        _row(1, "co2 in room 5.01", answer="It is 1,240 ppm."),
        _row(2, "co2 in room 5.02", answer="I don't have readings for that room."),
        _row(3, "co2 in room 5.03", answer=""),
    ]
    block = ss.build(_notes(rows))
    outcomes = [line.rsplit(" -> ", 1)[-1] for line in block.splitlines() if " -> " in line]
    assert outcomes == ["answered", "declined", "no answer recorded"]
    assert set(outcomes) <= set(ss.OUTCOMES)


def test_a_turn_note_has_no_field_for_the_answer():
    """The structural guarantee. If this ever gains a field, the redaction tests are alone."""
    note = ss.note_from_row(_row(1, "co2 in 5.01", answer="1,240 ppm"))
    assert set(vars(note)) == {"turn_index", "question", "intent", "outcome"}
    assert "1,240" not in repr(note)


def test_a_decline_is_recorded_as_a_decline_and_not_as_an_answer():
    """Reuses publication_gate.is_decline — the project's ONE decline classifier."""
    assert ss.outcome_of("I don't have readings for Room 9.99.") == "declined"
    assert ss.outcome_of("That room does not exist in this building.") == "declined"
    assert ss.outcome_of("The mean was steady across the window.") == "answered"
    assert ss.outcome_of("") == "no answer recorded"
    assert ss.outcome_of(None) == "no answer recorded"


# ── the user's own question keeps its subject and loses its figures ─────────────────────


def test_a_measurement_in_the_users_own_question_is_redacted():
    block = ss.build(_notes([_row(1, "is the co2 in room 5.01 above 1000 ppm")]))
    assert "1000 ppm" not in block
    assert "room 5.01" in block


def test_an_identifier_is_not_a_measurement_and_survives():
    """floor 3 and room 5.01 are identifiers; the BUG-191 lesson, one definition of both."""
    kept = redact_quantities("compare floor 3 with floor 4 for room 5.01 and AHU-1")
    assert "floor 3" in kept and "floor 4" in kept and "room 5.01" in kept and "AHU-1" in kept


@pytest.mark.parametrize(
    "text",
    [
        "the reading was 1,240 ppm",
        "22.5 °C in the lab",
        "48 kWh yesterday and 1200 ppm now",
        "80 % humidity, 350 lux, 45 dBA",
        "12 34 ppm 56 ppm",
        "100 200 kwh",
        "occupancy of 12 people",
    ],
)
def test_redaction_leaves_nothing_a_measurement_detector_can_find(text):
    assert has_quantitative_claim(text) is True
    assert has_quantitative_claim(redact_quantities(text)) is False


def test_the_rendered_summary_states_no_measurement_however_the_rows_are_built():
    rows = [
        _row(1, "is co2 above 1200 ppm in room 5.01", answer="It is 1,240 ppm, above 1000 ppm."),
        _row(2, "was it over 22.5 °C yesterday", answer="Peak 24.8 °C at 14:00."),
        _row(3, "energy over 48 kWh?", answer="Total 61.2 kWh."),
    ]
    assert has_quantitative_claim(ss.build(_notes(rows))) is False


# ── compression instead of a cliff ──────────────────────────────────────────────────────


def test_turn_three_survives_to_turn_sixty():
    """The tracker's acceptance, as a unit. The OLD reader dropped turns 1-10 at turn 60."""
    rows = _conversation(60)
    rows[2] = _row(3, "where is the nearest defibrillator on floor 2")
    block = ss.build(_notes(rows))
    assert "defibrillator" in block
    assert "Turns 1-50 covered:" in block


def test_the_compressed_era_names_its_turn_range_so_a_turn_can_be_located():
    block = ss.build(_notes(_conversation(40)))
    assert "Turns 1-30 covered:" in block


def test_the_oldest_subjects_are_the_ones_the_compressed_line_keeps():
    """First-appearance order, not frequency.

    The detail window already carries the recent end, so the compressed head is the only
    record of the oldest turns. Ranking by frequency would let a subject repeated forty
    times at the end evict turn 3's subject, which is the one thing this row exists to keep.
    """
    rows = [_row(1, "where is the defibrillator")]
    rows += [_row(i, "what is the co2 in the atrium") for i in range(2, 41)]
    block = ss.build(_notes(rows))
    era = [line for line in block.splitlines() if line.startswith("Turns ")][0]
    assert "defibrillator" in era
    assert era.index("defibrillator") < era.index("atrium")


def test_a_conversation_inside_the_detail_window_has_no_compressed_line():
    block = ss.build(_notes(_conversation(4)))
    assert "covered:" not in block
    assert block.count("\n") == 4  # header + four detail lines


def test_nothing_to_remember_produces_nothing():
    assert ss.build([]) == ""
    assert ss.build(_notes([_row(1, "", intent="", answer="")])) == ""


# ── bounds ──────────────────────────────────────────────────────────────────────────────


def test_the_block_is_bounded_however_long_the_conversation():
    """500 turns of 10,000-character questions — the store's retention cap, worst case."""
    rows = [_row(i, "why is it " + ("stuffy " * 1400), intent="x" * 200) for i in range(1, 501)]
    block = ss.build(_notes(rows))
    assert len(block) <= ss.SUMMARY_MAX_CHARS
    assert block.startswith(ss.HEADER)


def test_the_number_of_detail_lines_is_capped():
    block = ss.build(_notes(_conversation(500)))
    assert len([ln for ln in block.splitlines() if ln.startswith("Turn ")]) == ss.DETAIL_TURNS


def test_the_compressed_line_caps_its_subjects_and_says_how_many_it_left_out():
    rows = [_row(i, f"tell me about subject{i:03d}") for i in range(1, 61)]
    era = [ln for ln in ss.build(_notes(rows)).splitlines() if ln.startswith("Turns ")][0]
    assert era.count(";") >= ss.MAX_TOPICS  # MAX_TOPICS entries + the "and N more" tail
    assert "and 38 more" in era


def test_the_declared_bounds_leave_the_backstop_unused():
    """Structural maximum < the hard cut, so the final truncation never fires in practice.

    Fails when a constant is widened without re-checking the arithmetic — which is the only
    way the backstop in `build` can ever be reached.
    """
    detail_line = len("Turn 99999 [") + ss.INTENT_MAX_CHARS + len("] asked: ")
    detail_line += ss.QUESTION_MAX_CHARS + len(" -> no answer recorded")
    era = len("Turns 10000-99999 covered: ") + ss.MAX_TOPICS * (ss.TOPIC_MAX_CHARS + 2)
    era += len("; and 999 more") + len(" (999 answered, 999 declined).")
    worst = len(ss.HEADER) + era + ss.DETAIL_TURNS * detail_line + ss.DETAIL_TURNS + 1
    assert worst <= ss.SUMMARY_MAX_CHARS


# ── the injected block is replaced, never stacked ───────────────────────────────────────


def test_an_earlier_injected_block_is_stripped_before_the_new_one_goes_in():
    """The routes that restore history from Redis would otherwise stack one block per turn."""
    from shared.models import Message

    messages = [
        Message(role="system", content=ss.HEADER + "\nTurn 1 [x] asked: a -> answered"),
        Message(role="user", content="and there?"),
    ]
    kept = ss.strip_previous(messages)
    assert [m.role for m in kept] == ["user"]


def test_stripping_leaves_a_system_message_that_is_not_ours_alone():
    from shared.models import Message

    messages = [Message(role="system", content="You are a building assistant.")]
    assert len(ss.strip_previous(messages)) == 1


def test_stripping_handles_plain_dicts_and_an_empty_history():
    assert ss.strip_previous([]) == []
    assert ss.strip_previous([{"role": "system", "content": ss.HEADER + "\nx"}]) == []
    assert ss.strip_previous([{"role": "user", "content": "hi"}]) == [
        {"role": "user", "content": "hi"}
    ]


# ── the store side ──────────────────────────────────────────────────────────────────────


def _service_over(rows):
    """A TurnMemoryService whose pool returns ``rows``, plus the captured fetch args."""
    from orchestrator.services.turn_memory import TurnMemoryService

    captured = {}

    async def fetch(sql, *args):
        captured["sql"] = sql
        captured["args"] = args
        return rows

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return TurnMemoryService(pool=pool), captured


# ── the skip moved from SQL to Python, and these tests had to move with it ──────────────
#
# Until BUG-941 the skip was ``OFFSET $2`` and these tests asserted the ARGUMENT. Three of
# them were vacuous while they did so, and it is worth saying how: ``_service_over`` returns
# a fixed row list whatever SQL it is handed, so ``OFFSET 20`` over one row returned that
# row here and nothing at all from a real Postgres. The tests pinned a parameter that the
# fake then ignored, and the behaviour they were named for was never exercised.
#
# ``get_session_context`` fetches every surviving row once and slices in Python, because the
# recall lane needs all of them and the summary needs all but the newest few — one query,
# two readers. The slice is what the OFFSET did, so the semantics are unchanged against a
# real database; what changed is that the fake can no longer hide them, and these tests now
# assert the OUTCOME of the skip rather than the argument that used to implement it.


@pytest.mark.asyncio
async def test_the_store_truncates_every_text_column_before_it_crosses_the_wire():
    """500 rows of unbounded TEXT once per turn, on four routes, is the cost this avoids."""
    svc, captured = _service_over([_row(1, "co2 in 5.01")])
    await svc.get_session_summary("conv-1", skip_recent=0)
    sql = " ".join(captured["sql"].split())
    assert "LEFT(user_query," in sql and "LEFT(result_summary," in sql


@pytest.mark.asyncio
async def test_the_skipped_turns_are_the_ones_the_raw_history_still_shows():
    """The default offset is a TURN count, not CONVERSATION_MAX_MESSAGES.

    It was ``skip_recent=CONVERSATION_MAX_MESSAGES`` (20), a count of MESSAGES in Redis,
    while the raw history that reaches a prompt is six messages — three turns. Turns 4
    through 20 were in NEITHER, which is a seventeen-turn hole that both halves reported as
    healthy. Six messages is three user turns plus three replies, so three is exact.

    Asserted on the RESULT now: the three newest turns are absent from the block and the
    older ones are present. The previous version read the SQL argument, which a fake that
    ignores OFFSET cannot contradict.
    """
    from orchestrator.services import session_summary as mod

    assert mod.RECENT_TURNS_KEPT_RAW == 3
    rows = [_row(i, f"subject{i}") for i in range(6, 0, -1)]  # newest first, as SQL returns
    svc, _ = _service_over(rows)
    block = await svc.get_session_summary("conv-1")
    for kept in ("subject1", "subject2", "subject3"):
        assert kept in block, f"{kept} should be in the summary"
    for skipped in ("subject4", "subject5", "subject6"):
        assert skipped not in block, f"{skipped} is still in the raw window"


@pytest.mark.asyncio
async def test_the_scan_reaches_every_row_the_store_still_holds():
    """The scan limit must not re-introduce the cliff one level down.

    It is above the Postgres retention cap in the same module, so every surviving turn is
    seen and COMPRESSED rather than dropped.
    """
    from orchestrator.services import turn_memory as tm

    svc, captured = _service_over([_row(1, "co2 in 5.01")])
    await svc.get_session_summary("conv-1")
    assert captured["args"][1] == tm._MAX_OLDER_SCAN
    assert tm._MAX_OLDER_SCAN >= tm._MAX_TURNS_PER_CONVERSATION


@pytest.mark.asyncio
async def test_rows_arrive_newest_first_and_are_rendered_oldest_first():
    """The SQL orders DESC; a reversal bug would make every compressed line nonsense."""
    rows = [
        _row(i, q)
        for i, q in ((6, "f"), (5, "e"), (4, "d"), (3, "lifts"), (2, "showers"), (1, "bike racks"))
    ]
    svc, _ = _service_over(rows)
    block = await svc.get_session_summary("conv-1")
    assert block.index("bike") < block.index("showers") < block.index("lifts")


@pytest.mark.asyncio
async def test_the_recall_lane_gets_every_turn_while_the_prompt_gets_the_older_ones():
    """BUG-941: the two readers of one fetch want different slices, and both must be served.

    The prompt block skips the newest turns because the raw message window still shows them.
    The recall lane must NOT skip them — "what did I just ask?" is a question about exactly
    those turns — so it receives every row, and from the same single query.
    """
    rows = [_row(i, f"subject{i}") for i in range(6, 0, -1)]
    svc, captured = _service_over(rows)
    block, notes = await svc.get_session_context("conv-1")
    assert [n.turn_index for n in notes] == [1, 2, 3, 4, 5, 6]
    assert "subject6" in notes[-1].question and "subject6" not in block
    assert captured["sql"].count("$") == 2, "one fetch, two parameters: id and scan cap"


@pytest.mark.asyncio
async def test_no_postgres_means_no_summary_and_no_exception():
    from orchestrator.services.turn_memory import TurnMemoryService

    assert await TurnMemoryService(pool=None).get_session_summary("conv-1") == ""


@pytest.mark.asyncio
async def test_a_failing_store_degrades_to_no_memory_rather_than_no_answer():
    from orchestrator.services.turn_memory import TurnMemoryService

    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=RuntimeError("pool exhausted"))
    assert await TurnMemoryService(pool=pool).get_session_summary("conv-1") == ""


@pytest.mark.asyncio
async def test_an_empty_store_produces_nothing_rather_than_an_empty_header():
    svc, _ = _service_over([])
    assert await svc.get_session_summary("conv-1") == ""
