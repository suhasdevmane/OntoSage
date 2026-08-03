"""Test STRICT_SECRETS validator in shared/config.py.

Hermetic by construction: every test sets the FULL secret env it needs and
restores a known-constructible env before the final reload. These tests used to
lean on a developer's local `.env` (which supplied STRICT_SECRETS=false plus real
passwords) and therefore could not run from a fresh clone, from CI, or from the
repo's canonical "no building active" state — the cleanup reload raised, so the
whole file failed. Nothing here may depend on an untracked file.
"""

import importlib

import pytest
from pydantic_core import ValidationError

# A full set of non-default secrets — enough for Settings() to construct under
# STRICT_SECRETS=true. Individual tests override ONE entry to a known default to
# prove the guard catches it.
_CUSTOM = {
    "GRAPHDB_PASSWORD": "my-secure-graphdb-pass-xyz!",
    "POSTGRES_USER_PASSWORD": "my-secure-postgres-pass!",
    "MYSQL_PASSWORD": "my-secure-mysql-pass!",
    "PIPELINE_API_KEY": "sk-custom-pipeline-key-xyz!",
    "SECRET_KEY": "changed-key-for-testing-purposes-1234567890abcdef",
}


def _apply(monkeypatch, strict: str, **overrides) -> None:
    """Set STRICT_SECRETS plus a full custom secret set, with optional overrides."""
    monkeypatch.setenv("STRICT_SECRETS", strict)
    for key, value in {**_CUSTOM, **overrides}.items():
        monkeypatch.setenv(key, value)


def _restore(monkeypatch, cfg) -> None:
    """Leave shared.config importable for every later test in the session.

    The module instantiates `settings = Settings()` at import, so the final reload
    must be guaranteed to succeed — pin STRICT_SECRETS=false explicitly rather
    than deleting it and hoping the ambient default is permissive.
    """
    _apply(monkeypatch, "false")
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_is_secure_by_default(monkeypatch):
    """Unset STRICT_SECRETS must default to True — secure by default."""
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    for key, value in _CUSTOM.items():
        monkeypatch.setenv(key, value)
    import shared.config as cfg

    importlib.reload(cfg)
    s = cfg.Settings()
    assert s.STRICT_SECRETS is True
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_graphdb_password(monkeypatch):
    """When STRICT_SECRETS=true and GraphDB password is the default, startup must raise."""
    _apply(monkeypatch, "true", GRAPHDB_PASSWORD="Admin@GraphDB2024")
    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_postgres_password(monkeypatch):
    """When STRICT_SECRETS=true and Postgres password is the default, startup must raise."""
    _apply(monkeypatch, "true", POSTGRES_USER_PASSWORD="ontobot_secret")
    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_mysql_password(monkeypatch):
    """When STRICT_SECRETS=true and MySQL password is the default, startup must raise."""
    _apply(monkeypatch, "true", MYSQL_PASSWORD="mysql")
    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_pipeline_api_key(monkeypatch):
    """When STRICT_SECRETS=true and PIPELINE_API_KEY is the default, startup must raise."""
    _apply(monkeypatch, "true", PIPELINE_API_KEY="sk-ontobot-pipeline")
    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|default"):
        importlib.reload(cfg)
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_secret_key(monkeypatch):
    """STRICT_SECRETS must also refuse the default JWT SECRET_KEY (even with RBAC off)."""
    _apply(monkeypatch, "true", SECRET_KEY="change-me-in-production-use-32-random-bytes")
    monkeypatch.setenv("RBAC_ENABLED", "false")  # the RBAC gate is NOT what catches it
    import shared.config as cfg

    with pytest.raises(
        (ValueError, ValidationError), match="(?i)strict_secrets|secret_key|default"
    ):
        importlib.reload(cfg)
    monkeypatch.delenv("RBAC_ENABLED", raising=False)
    _restore(monkeypatch, cfg)


@pytest.mark.unit
def test_strict_secrets_passes_with_all_custom_passwords(monkeypatch):
    """When STRICT_SECRETS=true and all passwords are custom, no error raised."""
    _apply(monkeypatch, "true")
    import shared.config as cfg

    importlib.reload(cfg)
    s = cfg.Settings()
    assert s.STRICT_SECRETS is True
    _restore(monkeypatch, cfg)
