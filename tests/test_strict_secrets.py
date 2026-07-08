"""Test STRICT_SECRETS validator in shared/config.py"""

import pytest
from pydantic_core import ValidationError


@pytest.mark.unit
def test_strict_secrets_off_by_default(monkeypatch):
    """STRICT_SECRETS defaults to False — default passwords must not raise."""
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    # Force reload with clean env
    import importlib

    import shared.config as cfg

    importlib.reload(cfg)
    s = cfg.Settings()
    assert s.STRICT_SECRETS is False
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_graphdb_password(monkeypatch):
    """When STRICT_SECRETS=true and GraphDB password is the default, startup must raise."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "Admin@GraphDB2024")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "custom-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "custom-mysql-pass!")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890abcdef")
    import importlib

    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    # Reload back to clean state
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    monkeypatch.delenv("GRAPHDB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_postgres_password(monkeypatch):
    """When STRICT_SECRETS=true and Postgres password is the default, startup must raise."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "ontobot_secret")
    monkeypatch.setenv("MYSQL_PASSWORD", "custom-mysql-pass!")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890abcdef")
    import importlib

    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    # Reload back to clean state
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    monkeypatch.delenv("GRAPHDB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_mysql_password(monkeypatch):
    """When STRICT_SECRETS=true and MySQL password is the default, startup must raise."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "custom-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "mysql")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890abcdef")
    import importlib

    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|password|default"):
        importlib.reload(cfg)
    # Reload back to clean state
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    monkeypatch.delenv("GRAPHDB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_pipeline_api_key(monkeypatch):
    """When STRICT_SECRETS=true and PIPELINE_API_KEY is the default, startup must raise."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "custom-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "custom-mysql-pass!")
    monkeypatch.setenv("PIPELINE_API_KEY", "sk-ontobot-pipeline")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890abcdef")
    import importlib

    import shared.config as cfg

    with pytest.raises((ValueError, ValidationError), match="(?i)strict_secrets|default"):
        importlib.reload(cfg)
    # Reload back to clean state
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    monkeypatch.delenv("GRAPHDB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.delenv("PIPELINE_API_KEY", raising=False)
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_passes_with_all_custom_passwords(monkeypatch):
    """When STRICT_SECRETS=true and all passwords are custom, no error raised."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "my-secure-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "my-secure-mysql-pass!")
    monkeypatch.setenv("PIPELINE_API_KEY", "sk-custom-pipeline-key-xyz!")
    monkeypatch.setenv("SECRET_KEY", "changed-key-for-testing-purposes-1234567890abcdef")
    import importlib

    import shared.config as cfg

    importlib.reload(cfg)
    s = cfg.Settings()
    assert s.STRICT_SECRETS is True
    # Reload back to clean state
    monkeypatch.delenv("STRICT_SECRETS", raising=False)
    monkeypatch.delenv("GRAPHDB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_USER_PASSWORD", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.delenv("PIPELINE_API_KEY", raising=False)
    importlib.reload(cfg)


@pytest.mark.unit
def test_strict_secrets_raises_on_default_secret_key(monkeypatch):
    """STRICT_SECRETS must also refuse the default JWT SECRET_KEY (even with RBAC off)."""
    monkeypatch.setenv("STRICT_SECRETS", "true")
    monkeypatch.setenv("RBAC_ENABLED", "false")  # the RBAC gate is NOT what catches it
    monkeypatch.setenv("GRAPHDB_PASSWORD", "my-secure-graphdb-pass-xyz!")
    monkeypatch.setenv("POSTGRES_USER_PASSWORD", "my-secure-postgres-pass!")
    monkeypatch.setenv("MYSQL_PASSWORD", "my-secure-mysql-pass!")
    monkeypatch.setenv("PIPELINE_API_KEY", "sk-custom-pipeline-key-xyz!")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production-use-32-random-bytes")
    import importlib

    import shared.config as cfg

    with pytest.raises(
        (ValueError, ValidationError), match="(?i)strict_secrets|secret_key|default"
    ):
        importlib.reload(cfg)
    # Reload back to clean state
    for k in (
        "STRICT_SECRETS",
        "RBAC_ENABLED",
        "GRAPHDB_PASSWORD",
        "POSTGRES_USER_PASSWORD",
        "MYSQL_PASSWORD",
        "PIPELINE_API_KEY",
        "SECRET_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(cfg)
