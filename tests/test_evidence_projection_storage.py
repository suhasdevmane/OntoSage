"""D9 — a bounded evidence projection is written to turn_memory on every turn.

The projection must describe the record without becoming a copy of it. These tests pin the
size cap and the field set, and that save_turn really writes the projection to the new column.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.services.answer_provenance import (
    PROJECTION_MAX_SOURCES,
    for_reader,
    project_for_storage,
)
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


def _big_record(n_sources: int = 500) -> dict:
    return {
        "status": "observed",
        "operation": "observation",
        "sources": [
            {
                "source_id": f"uuid-{i}",
                "kind": "sensor",
                "store": "sensordb",
                "owner": "BMS " * 40,  # long free text must be cut
                "observed_at": "2026-10-06T09:00:00",
                "label": "x" * 5000,  # not a projected field at all
                "readings": list(range(200)),  # not a projected field at all
            }
            for i in range(n_sources)
        ],
        "latest_evidence_at": "2026-10-06T09:00:00",
        "retrieved_at": "2026-10-06T09:01:00",
        "gates_applied": [f"gate_{i}" for i in range(60)],
        "gates_advisory": ["gate_x: " + "why " * 200],
        "claim_binding": {
            "mode": "shadow",
            "lane": "sql",
            "evidence_available": True,
            "counts": {"total": 4, "bound": 3, "derived": 0, "unbound": 1, "skipped": 0},
            "claims": [{"raw": "a" * 3000}],  # the claim list must never be stored
        },
    }


def test_projection_caps_sources_and_keeps_the_true_total():
    proj = project_for_storage(_big_record(500))
    assert len(proj["sources"]) == PROJECTION_MAX_SOURCES == 25
    assert proj["sources_total"] == 500


def test_projection_size_is_bounded_regardless_of_record_size():
    proj = project_for_storage(_big_record(5000))
    assert len(json.dumps(proj)) < 12_000


def test_projection_keeps_only_identity_fields_per_source():
    proj = project_for_storage(_big_record(3))
    for src in proj["sources"]:
        assert set(src) == {"source_id", "kind", "store", "owner", "observed_at"}
    assert "readings" not in json.dumps(proj)
    assert "claims" not in proj["claim_binding"]


def test_free_text_is_cut_and_gate_lists_are_capped():
    proj = project_for_storage(_big_record(1))
    assert len(proj["sources"][0]["owner"]) <= 200
    assert len(proj["gates_applied"]) == 20
    assert len(proj["gates_advisory"][0]) <= 200


def test_claim_binding_is_counts_only():
    proj = project_for_storage(_big_record(1))
    assert proj["claim_binding"] == {
        "mode": "shadow",
        "counts": {"total": 4, "bound": 3, "derived": 0, "unbound": 1, "skipped": 0},
    }


def test_empty_or_missing_record_projects_to_none():
    assert project_for_storage(None) is None
    assert project_for_storage({}) is None


def test_remedy_is_stripped_for_non_admin_readers_only():
    rec = {"status": "not_assessable", "remedy": "connect the stream"}
    proj = project_for_storage(rec)
    assert for_reader(proj, is_admin=True)["remedy"] == "connect the stream"
    assert "remedy" not in for_reader(proj, is_admin=False)


def _state_with_record(record: dict) -> ConversationState:
    return ConversationState(
        conversation_id="conv-d9",
        user_id="alice",
        user_message="how many people are in room 1.04?",
        building_id="bldg1",
        messages=[Message(role="user", content="q")],
        intermediate_results={"intent": "sensor_data", "evidence_record": record},
    )


@pytest.mark.asyncio
async def test_save_turn_writes_the_projection_to_the_evidence_column():
    from orchestrator.services.turn_memory import TurnMemoryService

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=3)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )

    await TurnMemoryService(pool=pool).save_turn(_state_with_record(_big_record(40)))

    insert = [c for c in conn.execute.call_args_list if "INSERT INTO turn_memory" in c.args[0]]
    assert len(insert) == 1
    assert "evidence" in insert[0].args[0].split("VALUES")[0]
    stored = json.loads(insert[0].args[-1])
    assert stored["sources_total"] == 40
    assert len(stored["sources"]) == 25


@pytest.mark.asyncio
async def test_save_turn_stores_null_when_the_turn_carries_no_record():
    from orchestrator.services.turn_memory import TurnMemoryService

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    state = _state_with_record({})
    state.intermediate_results.pop("evidence_record")
    await TurnMemoryService(pool=pool).save_turn(state)

    insert = [c for c in conn.execute.call_args_list if "INSERT INTO turn_memory" in c.args[0]]
    assert insert[0].args[-1] is None


def test_schema_adds_the_evidence_column_idempotently():
    from pathlib import Path

    src = Path("orchestrator/postgres_manager.py").read_text(encoding="utf-8")
    assert "ALTER TABLE turn_memory ADD COLUMN IF NOT EXISTS evidence JSONB" in src
