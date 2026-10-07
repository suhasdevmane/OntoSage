"""BUG-1428 / trial G6: the newest-reading compliance verdict and its claim reconciliation.

Both modules are stdlib-only, so they are loaded by path under private names. Importing the
``orchestrator`` package instead boots Settings, which refuses to start on this machine's
STRICT_SECRETS setting -- the same reason tests/services/test_standards_engine.py loads by path.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def _load(private_name: str, rel_path: str):
    if private_name in sys.modules:
        return sys.modules[private_name]
    spec = importlib.util.spec_from_file_location(private_name, str(_ROOT / rel_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[private_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


_se = _load("_t_standards_engine_verdict", "orchestrator/services/standards_engine.py")
_nc = _load(
    "_t_narration_contradiction_verdict", "orchestrator/services/narration_contradiction.py"
)

G6_TIME = "2026-10-02 11:45:13"


def _rows(*pairs):
    """Rows of (timestamp, co2) -- wide enough for the verdict's column keywords."""
    return [
        {"timestamp": ts, "Room co2 ppm": co2, "temperature": 22.0, "humidity": 45.0}
        for ts, co2 in pairs
    ]


def test_newest_reading_above_co2_limit_is_not_fully_compliant():
    verdict = _se.newest_reading_verdict(_rows(("2026-10-02 10:00:00", 400), (G6_TIME, 1052)))
    assert verdict is not None
    assert verdict["at"] == G6_TIME
    assert verdict["all_compliant"] is False
    names = [f["standard"] for f in verdict["failing"]]
    assert any("WELL" in n for n in names)
    assert any("BREEAM" in n for n in names)
    # borderline is not compliance: 1052 ppm is within 10% of a 1000 ppm limit.
    assert all(f["status"] in ("borderline", "non_compliant") for f in verdict["failing"])


def test_verdict_judges_only_the_newest_row():
    # The first row is over the limit, the newest is not: the newest decides.
    verdict = _se.newest_reading_verdict(
        _rows(("2026-10-02 10:00:00", 1052), ("2026-10-02 11:00:00", 400))
    )
    assert verdict is not None
    assert verdict["at"] == "2026-10-02 11:00:00"
    for failure in verdict["failing"]:
        assert not any("CO2" in p for p in failure["parameters"])


def test_no_rows_or_no_mapped_columns_yields_no_verdict():
    assert _se.newest_reading_verdict([]) is None
    assert _se.newest_reading_verdict(None) is None
    assert _se.newest_reading_verdict([{"timestamp": "t", "unrelated": "x"}]) is None


def test_reconcile_replaces_the_claim_about_the_newest_reading():
    verdict = _se.newest_reading_verdict(_rows((G6_TIME, 1052)))
    text = (
        "Room 5.08 is at 22.5 °C. ❌ CO₂ is non-compliant with WELL v2 at this time.\n"
        f"Thus, the last time Room 5.08 met all listed comfort standards was at {G6_TIME}."
    )
    out = _nc.reconcile_compliance_claim(text, verdict)
    assert "met all listed" not in out
    assert f"At the newest reading ({G6_TIME})" in out
    assert "Not compliant:" in out
    assert "No earlier reading was searched" in out
    # Surrounding sentences are untouched.
    assert out.startswith("Room 5.08 is at 22.5 °C. ❌ CO₂ is non-compliant with WELL v2")


def test_reconcile_leaves_a_claim_about_an_earlier_time_alone():
    verdict = _se.newest_reading_verdict(_rows((G6_TIME, 1052)))
    text = "The last time it met all listed standards was at 2026-10-01 09:00:00."
    assert _nc.reconcile_compliance_claim(text, verdict) == text


def test_reconcile_is_identity_without_a_failing_verdict_or_a_claim():
    failing = _se.newest_reading_verdict(_rows((G6_TIME, 1052)))
    clean = {"at": G6_TIME, "checked": ["x"], "failing": [], "all_compliant": True}
    claim = f"The last time it met all listed standards was at {G6_TIME}."
    assert _nc.reconcile_compliance_claim(claim, clean) == claim
    assert _nc.reconcile_compliance_claim(claim, None) == claim
    assert _nc.reconcile_compliance_claim("CO2 is 1052 ppm.", failing) == "CO2 is 1052 ppm."
    assert _nc.reconcile_compliance_claim("", failing) == ""


def test_reconcile_also_catches_a_plain_comfortable_claim():
    """2026-10-07, G6 widened: the original regex required "standard"/"compliant" in the
    sentence. A plain "was comfortable" claim about the newest reading is now caught too."""
    verdict = _se.newest_reading_verdict(_rows((G6_TIME, 1052)))
    text = (
        "Room 5.08 is at 22.5 °C. ❌ CO₂ is non-compliant with WELL v2 at this time.\n"
        f"The room was comfortable as of {G6_TIME}."
    )
    out = _nc.reconcile_compliance_claim(text, verdict)
    assert "was comfortable" not in out
    assert f"At the newest reading ({G6_TIME})" in out
    assert out.startswith("Room 5.08 is at 22.5 °C. ❌ CO₂ is non-compliant with WELL v2")


def test_a_negated_comfort_claim_with_no_matching_timestamp_is_untouched():
    """The widened regex also matches "you can't say whether it is comfortable" -- a real
    shape measured in stored answers. It must NOT be edited: there is no timestamp in the
    sentence for reconcile_compliance_claim's own gate to match against, so the safety rail
    (same computed time must appear in the matched sentence) holds regardless of how broad
    the detection regex becomes."""
    verdict = _se.newest_reading_verdict(_rows((G6_TIME, 1052)))
    text = "Because we don't have the current sensor values, you can't say for sure whether the room is comfortable or not."
    assert _nc.reconcile_compliance_claim(text, verdict) == text


def test_dead_auto_check_pair_is_gone_from_the_live_path():
    # BUG-1428: these were never on development; no call site may reference them again.
    orch = (_ROOT / "orchestrator" / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")
    engine = (_ROOT / "orchestrator" / "services" / "standards_engine.py").read_text(
        encoding="utf-8"
    )
    assert ".auto_check(" not in orch
    assert ".format_for_llm(" not in orch
    assert "def auto_check" not in engine
    assert "def format_for_llm" not in engine
