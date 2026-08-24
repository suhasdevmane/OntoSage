# -*- coding: utf-8 -*-
"""Core code must carry no building literals (V6-T63, static half).

This runs in the ordinary unit suite so it fires on every commit, not at certification. That
matters more than usual for V6: the whole plan is developed against bldg1, so a
building-shaped assumption would otherwise stay invisible until somebody swapped buildings
weeks later.

It is not hypothetical. The pre-V6 baseline scan found two live defects:

* **BUG-214** - a prompt string asserting *"This building (Abacws) does NOT have energy meters
  or power consumption sensors"*, which named a building in core code, had become FALSE for
  that building once it gained energy metering, and was emitted for whichever building was
  active - so any other building was told it was Abacws.
* **BUG-215** - the alert store falling back to the literal ``"bldg1"``, so a building whose
  state carried no id read and wrote another building's user alerts.

Both are regression-tested below.
"""

from pathlib import Path

import pytest

from scripts.check_building_literals import scan

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ORCH = REPO / "orchestrator" / "workflow" / "_orchestrator.py"


def test_core_code_has_no_building_literals(capsys):
    """The gate itself. Failure output names the file, line and pattern."""
    rc = scan()
    out = capsys.readouterr().out
    assert rc == 0, f"building literals found in core code:\n{out}"


def _executable_source(path: Path) -> str:
    """Source with docstrings and comments stripped.

    Needed because the fix for BUG-214 QUOTES the removed string in a comment explaining what
    was wrong with it - which is exactly the kind of context worth keeping. A raw substring
    search would fail on that comment and push a future maintainer to delete the explanation
    to make the test pass. (This test made that mistake on its first run, minutes after the
    scanner made the same one.)
    """
    from scripts.check_building_literals import _prose_lines

    src = path.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    return "\n".join(line for n, line in enumerate(src.splitlines(), 1) if n not in prose)


def test_bug_214_no_hardcoded_sensor_inventory_in_prompts():
    """The energy note must describe the RETRIEVED DATA, not the building's instrumentation.

    A claim about what a building owns is a graph COUNT question; asserting it in a prompt
    string is how this one went stale and stayed wrong.
    """
    code = _executable_source(ORCH)
    assert "does NOT have energy meters" not in code
    assert "This building (Abacws)" not in code
    # The replacement must still stop the model inventing a figure.
    assert "contains no energy or power" in code
    assert "Do not state, estimate or imply an energy or carbon figure" in code


def test_bug_215_alert_store_uses_the_active_building():
    """No fallback to a specific building id - user data must not cross buildings."""
    code = _executable_source(ORCH)
    assert 'state.building_id or "bldg1"' not in code
    assert "state.building_id or settings.BUILDING_ID" in code


def test_scanner_reports_prose_and_accumulators_as_clean():
    """The scanner must not cry wolf, or it gets muted.

    Its first version reported 16 hits of which 14 were prose inside multi-line docstrings and
    two were `sensor_count = 0` accumulators. A scanner with a 12% true-positive rate is worse
    than no scanner, because the habit it teaches is to ignore it.
    """
    from scripts.check_building_literals import _prose_lines

    src = (
        "def f():\n"
        '    """Example: pipeline.load_manifest("abacws", 3) -- a usage illustration.\n'
        "\n"
        "    Mentioning abacws here is documentation, not a literal.\n"
        '    """\n'
        "    sensor_count = 0  # accumulator, not a hardcoded count\n"
        "    return sensor_count\n"
    )
    prose = _prose_lines(src)
    # Every line of the docstring (2-5) is prose, including its interior.
    assert {2, 3, 4, 5}.issubset(prose)
    # The trailing comment is prose too.
    assert 6 in prose
