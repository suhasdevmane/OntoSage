# -*- coding: utf-8 -*-
"""B1: scripts/generate_secrets.py rewrites only placeholder credentials, never prints them."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_secrets.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_secrets_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gs = _load()

# Real-looking values that must survive untouched.
_KEPT_MYSQL = "kept-mysql-value-7f3a"
_KEPT_OPENAI = "CHANGE-ME-openai"  # provider key: never rotated even though it is a placeholder
_TEMPLATE = (
    "# header comment, must survive\r\n"
    "SECRET_KEY=change-me-in-production-use-32-random-bytes\r\n"
    "MYSQL_PASSWORD=" + _KEPT_MYSQL + "\r\n"
    "OPENAI_API_KEY=" + _KEPT_OPENAI + "\r\n"
    "POSTGRES_PASSWORD=CHANGE-ME-postgres  # inline comment survives\r\n"
    "ADMIN_PASSWORD=\r\n"
    "STRICT_SECRETS=true\r\n"
    "PIPELINE_API_KEY=CHANGE_ME_pipeline\r\n"
)


def _value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    raise KeyError(key)


def test_placeholders_are_rotated_and_everything_else_is_kept():
    new, rotated = gs.rotate_text(_TEMPLATE)
    assert set(rotated) == {
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "PIPELINE_API_KEY",
        "WEBUI_SECRET_KEY",
    }
    assert _value(new, "SECRET_KEY") != "change-me-in-production-use-32-random-bytes"
    assert len(_value(new, "SECRET_KEY")) >= 40
    assert _value(new, "MYSQL_PASSWORD") == _KEPT_MYSQL
    assert _value(new, "OPENAI_API_KEY") == _KEPT_OPENAI
    assert _value(new, "STRICT_SECRETS") == "true"
    assert _value(new, "ADMIN_PASSWORD") == ""  # empty = not configured, left alone
    assert "# header comment, must survive" in new
    assert "# inline comment survives" in new  # the comment outlives the value it followed


def test_generated_values_survive_env_file_parsing():
    new, _ = gs.rotate_text(_TEMPLATE)
    for key in ("SECRET_KEY", "POSTGRES_PASSWORD", "PIPELINE_API_KEY", "WEBUI_SECRET_KEY"):
        value = _value(new, key).split(" #")[0].rstrip()
        assert value and " " not in value and "#" not in value and '"' not in value


def test_line_endings_are_preserved():
    new, _ = gs.rotate_text(_TEMPLATE)
    assert new.count("\r\n") == _TEMPLATE.count("\r\n") + 1  # +1 for the appended WEBUI key
    assert new.count("\n") == new.count("\r\n")


def test_a_real_value_is_kept_without_force_and_rotated_with_it():
    real = "SECRET_KEY=already-a-real-value-0123456789abcdef\n"
    kept, rotated_kept = gs.rotate_text(real + "WEBUI_SECRET_KEY=x-real-webui-value-9876543210\n")
    assert kept.startswith(real) and "SECRET_KEY" not in rotated_kept
    forced, rotated_forced = gs.rotate_text(real, force=True)
    assert "SECRET_KEY" in rotated_forced
    assert not forced.startswith(real)


def test_idempotent_second_run_rotates_nothing():
    once, _ = gs.rotate_text(_TEMPLATE)
    twice, rotated = gs.rotate_text(once)
    assert rotated == []
    assert twice == once


def test_main_writes_the_file_and_never_prints_a_value(tmp_path, capsys):
    env = tmp_path / ".env1"
    env.write_bytes(_TEMPLATE.encode("utf-8"))
    assert gs.main(["--env", str(env)]) == 0
    written = env.read_text(encoding="utf-8")
    out = capsys.readouterr()
    assert written != _TEMPLATE
    new_secret = _value(written, "SECRET_KEY")
    for stream in (out.out, out.err):
        assert new_secret not in stream
        assert _KEPT_MYSQL not in stream
        assert "change-me-in-production" not in stream
    assert "SECRET_KEY" in out.out


def test_dry_run_writes_nothing(tmp_path):
    env = tmp_path / ".env1"
    env.write_bytes(_TEMPLATE.encode("utf-8"))
    assert gs.main(["--env", str(env), "--dry-run"]) == 0
    assert env.read_bytes() == _TEMPLATE.encode("utf-8")


def test_missing_file_is_an_error_not_a_created_file(tmp_path):
    assert gs.main(["--env", str(tmp_path / "nope")]) == 2
    assert not (tmp_path / "nope").exists()
