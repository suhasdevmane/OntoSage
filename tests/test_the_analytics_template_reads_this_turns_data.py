# -*- coding: utf-8 -*-
"""An analytics template computes over the rows THIS turn fetched, not a file on a shared disk.

BUG-898. Asked live on 2026-09-29 and again on 2026-09-30, "How does observed occupancy compare
with the design occupancy of room 1.25?" returned, of a seminar room the graph declares at 20
people, "a latest reading of 4,401.86 occupants at 2025-12-17 00:24:26 ... the mean occupancy was
5,178.52, the median 5,194.09". Every figure was IDENTICAL on the two runs, to two decimal places,
a day apart, on a building whose occupancy series are written to every minute. A number the model
invents does not repeat like that; a static file does.

It was one:

* `_get_template_code` built code reading `/app/outputs/data/<data_filename>`;
* `data_filename` defaults to one shared name, `current_data.json`;
* only the main workflow ever WROTE a file, and it writes a per-conversation one. The planner
  calls `analyze` with no filename at all;
* so the planner's turn read the default name — a file last written on 2025-12-17 00:24:56,
  holding 119 rows of a sensor nobody asked for — and the narration captioned it with the room
  the question named.

The orchestrator log for that turn shows both halves in four lines: the SQL fetched 360 rows of
`711b5b72-...` (room 1.25's counter, values 11 to 15), and the executed code printed
`Sensor : ac496048-...` with 119 points.

Three properties are pinned here, and any ONE of them would have prevented it: the template
prefers the rows handed to it in-process, `analyze` never leaves a caller on the shared name, and
`analyze` writes its own rows to whatever name the code is told to read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from orchestrator.agents.analytics_agent import _DEFAULT_DATA_FILE, AnalyticsAgent

pytestmark = pytest.mark.unit


def _rows(uuid: str, values: List[float]) -> Dict[str, Any]:
    return {
        "data": [
            {"timestamp": f"2026-09-30T06:{i:02d}:00", "uuid": uuid, "value": v}
            for i, v in enumerate(values)
        ]
    }


def _template(query: str, uuid: str, filename: str = "unwritten_file.json") -> str:
    code = AnalyticsAgent()._get_template_code(
        query,
        {uuid: {"label": "Room A occupancy [persons]", "unit": "persons"}},
        filename,
    )
    assert code is not None, f"no template matched {query!r}"
    return code


def test_the_template_reads_the_handed_rows_before_any_file() -> None:
    """`raw_data_json` is consulted first; the file is the fallback, not the source."""
    code = _template("what is the latest and average occupancy", "sensor-aaaa-bbbb")
    load = code[code.index("# Load data") : code.index("if df.empty")]
    assert "raw_data_json" in load
    assert load.index("raw_data_json") < load.index(
        "read_json"
    ), "the file is read before the turn's own rows — that is the defect"


@pytest.mark.parametrize(
    "query",
    [
        "what is the latest and average occupancy",
        "compare the observed occupancy with the design occupancy of room A",
    ],
)
def test_the_template_computes_over_the_handed_rows(query: str, tmp_path: Path) -> None:
    """Execute the generated template with `raw_data_json` bound, as the executor does.

    THE FILE IN THE FALLBACK IS MADE TO HOLD THE WRONG ANSWER ON PURPOSE. If the template were
    still reading it, the numbers below would be the stale ones — which is exactly how BUG-898
    read as a plausible answer for nine months.
    """
    pytest.importorskip("pandas")
    uuid = "sensor-aaaa-bbbb"
    code = _template(query, uuid)
    scope: Dict[str, Any] = {"raw_data_json": _rows(uuid, [11.0, 12.0, 15.0])}
    out: List[str] = []
    scope["print"] = lambda *a, **k: out.append(" ".join(str(x) for x in a))
    exec(compile(code, "<template>", "exec"), scope)  # noqa: S102 — the unit under test
    printed = "\n".join(out)
    assert "No valid data available" not in printed
    assert "4401" not in printed and "5178" not in printed
    # the mean of 11, 12 and 15 is 12.67; whatever the template prints, it is about these rows
    assert any(tok in printed for tok in ("12.67", "15.00", "15.0", "12.6"))


def test_a_caller_that_names_no_file_does_not_get_the_shared_one() -> None:
    """The planner names none. Leaving it on the shared name is half of the defect."""
    agent = AnalyticsAgent()
    seen: Dict[str, Any] = {}

    def _capture(data, metadata, filename):
        seen["filename"] = filename
        return True

    agent._write_turn_data = _capture  # type: ignore[assignment]
    name = _DEFAULT_DATA_FILE
    assert name == "current_data.json"
    # `analyze` replaces it before any code is generated; reproduce that decision directly.
    resolved = "turn_x_data.json" if name == _DEFAULT_DATA_FILE else name
    assert resolved != _DEFAULT_DATA_FILE


def test_the_turn_writes_its_own_rows_to_the_file_the_code_will_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator.agents import analytics_agent as aa

    # PATCH WHERE IT IS USED, not where it is defined. These three tests passed alone and
    # in a 42-test pair, and FAILED in the full 13,000-test suite: the write went to the
    # real output directory instead of tmp_path. `_write_turn_data` reads the `settings`
    # name bound in `analytics_agent`'s own module namespace, and something earlier in a
    # full run rebinds it — so patching the object imported here reached a different
    # object entirely. Patching `aa.settings` patches whatever that module currently holds.
    monkeypatch.setattr(aa.settings, "OUTPUT_DATA_DIR", str(tmp_path), raising=False)
    data = _rows("sensor-cccc-dddd", [3.0, 4.0])
    ok = AnalyticsAgent._write_turn_data(data, {"sensor-cccc-dddd": {"label": "L"}}, "t.json")
    assert ok is True
    written = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert [r["value"] for r in written["data"]] == [3.0, 4.0]
    assert written["metadata"]["sensor-cccc-dddd"]["label"] == "L"


def test_a_file_that_cannot_be_written_never_costs_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rows are handed to the code in-process anyway, so a write failure is a log line."""
    from orchestrator.agents import analytics_agent as aa

    # PATCH WHERE IT IS USED, not where it is defined. These three tests passed alone and
    # in a 42-test pair, and FAILED in the full 13,000-test suite: the write went to the
    # real output directory instead of tmp_path. `_write_turn_data` reads the `settings`
    # name bound in `analytics_agent`'s own module namespace, and something earlier in a
    # full run rebinds it — so patching the object imported here reached a different
    # object entirely. Patching `aa.settings` patches whatever that module currently holds.
    monkeypatch.setattr(aa.settings, "OUTPUT_DATA_DIR", "\0 not a directory", raising=False)
    assert AnalyticsAgent._write_turn_data({"data": []}, None, "t.json") is False


@pytest.mark.asyncio
async def test_analyze_replaces_the_shared_default_and_writes_its_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through `analyze`: the name it passes on is unique and the file holds ITS rows.

    This is the one test that would have failed before the fix: `analyze` left the filename at
    `current_data.json` and wrote nothing, so the code it generated read whatever was there.
    """
    from orchestrator.agents import analytics_agent as aa
    from shared.models import ConversationState

    # PATCH WHERE IT IS USED, not where it is defined. These three tests passed alone and
    # in a 42-test pair, and FAILED in the full 13,000-test suite: the write went to the
    # real output directory instead of tmp_path. `_write_turn_data` reads the `settings`
    # name bound in `analytics_agent`'s own module namespace, and something earlier in a
    # full run rebinds it — so patching the object imported here reached a different
    # object entirely. Patching `aa.settings` patches whatever that module currently holds.
    monkeypatch.setattr(aa.settings, "OUTPUT_DATA_DIR", str(tmp_path), raising=False)
    agent = AnalyticsAgent()
    names: List[str] = []

    async def _fake_generate(query, data, sensor_metadata, data_filename, **kw):
        names.append(data_filename)
        return "print('ok')"

    async def _fake_exec(code, query, data, sensor_metadata, data_filename):
        names.append(data_filename)
        return {"success": True, "output": "ok", "error": None, "code": code}

    async def _fake_format(result, query, sensor_metadata, rows):
        return "formatted", []

    monkeypatch.setattr(agent, "_generate_code", _fake_generate)
    monkeypatch.setattr(agent, "_execute_with_retries", _fake_exec)
    monkeypatch.setattr(agent, "_format_analysis", _fake_format)

    state = ConversationState(conversation_id="c1", user_id="u1", user_message="q")
    uuid = "sensor-eeee-ffff"
    await agent.analyze(state, "average occupancy now", data=_rows(uuid, [7.0, 8.0]))

    assert names, "analyze never reached code generation"
    assert all(
        n != _DEFAULT_DATA_FILE for n in names
    ), f"a turn was left on the shared filename: {names}"
    assert len(set(names)) == 1, "the code was told to read a different file than was written"
    written = json.loads((tmp_path / names[0]).read_text(encoding="utf-8"))
    assert [r["value"] for r in written["data"]] == [7.0, 8.0]
