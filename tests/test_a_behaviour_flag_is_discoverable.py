"""A flag that changes behaviour is discoverable without grepping the source (TODO-494).

54 Settings fields and 25 raw `os.environ` names appeared in neither `.env` nor
`.env.example`. Every one had a working default, so none of them broke a fresh clone — they
were undiscoverable rather than broken, which is its own kind of defect: a setting nobody can
find is a setting nobody can use.

The row's own judgement was that listing all 79 would triple the file and bury the ones that
matter, so the split is deliberate: anything that changes BEHAVIOUR belongs here, and internal
tuning belongs in ONTOSAGE.md. This test holds that line.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Names that are set by the build or are internal plumbing, not behaviour a deployer picks.
_NOT_BEHAVIOUR = {
    "BUILD_SHA",  # stamped at image build
    "BUILD_TIME",  # stamped at image build
    "DEFAULT_BUILDING_ID",  # internal fallback; the real switch is BUILDING_ID
    "DOCS_OUTPUT_DIR",  # a script's output path
}


def _declared() -> set:
    text = Path(".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]{2,})=", text, re.M))


def _settings_fields() -> set:
    cfg = Path("shared/config.py").read_text(encoding="utf-8")
    return set(re.findall(r"^\s{4}([A-Z][A-Z0-9_]{2,})\s*:", cfg, re.M))


def _raw_env_names() -> set:
    names = set()
    for path in list(Path("orchestrator").rglob("*.py")) + list(Path("shared").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        names |= set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']", text))
        names |= set(re.findall(r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']", text))
    return names


def test_every_settings_field_is_documented():
    """These are the ones STRICT_SECRETS can refuse to boot on, so a missing one is not
    merely undiscoverable — it is a boot failure nobody can diagnose from the example."""
    missing = sorted(_settings_fields() - _declared())
    assert not missing, missing


def test_every_behaviour_flag_read_from_the_environment_is_documented():
    missing = sorted(_raw_env_names() - _declared() - _settings_fields() - _NOT_BEHAVIOUR)
    assert not missing, (
        f"{len(missing)} flag(s) change behaviour and appear in no example: {missing}. "
        f"Add them to .env.example with their real default, or add them to _NOT_BEHAVIOUR "
        f"with a reason if they are build-time or internal."
    )


def test_the_exclusion_list_stays_small_and_justified():
    """An exclusion list is how this guard would be silently emptied of meaning."""
    assert len(_NOT_BEHAVIOUR) <= 8
    for name in _NOT_BEHAVIOUR:
        assert name in _raw_env_names(), f"{name} is excluded but nothing reads it"


def test_the_documented_defaults_are_the_real_defaults():
    """A worked example that lies is worse than no example. Spot-checked on the flags whose
    default is load-bearing."""
    text = Path(".env.example").read_text(encoding="utf-8")
    for name, default in (
        ("LLM_MAX_RETRIES", "3"),
        ("LLM_RUNNER_RESTART_WAIT_S", "10.0"),
        ("RESPONSE_CACHE_FUZZY", "false"),
        ("CQIR_COMPILE_CACHE", "true"),
    ):
        assert re.search(rf"^{name}={re.escape(default)}\s*$", text, re.M), name
