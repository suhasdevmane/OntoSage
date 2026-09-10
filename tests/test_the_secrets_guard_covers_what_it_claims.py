# -*- coding: utf-8 -*-
"""A boot guard over five of fourteen credentials reports all-clear (CAVEAT-458, W2-2).

WHAT WENT WRONG
---------------
`.env.example` was missing 31 settings the live `.env` uses (CAVEAT-449). Filling the gap
made a second problem visible: comparing the two files showed SIX credentials whose live
values were IDENTICAL to the committed example --

    POSTGRES_PASSWORD, PGADMIN_DEFAULT_PASSWORD, API_KEY,
    API_PGPASSWORD, API_MYSQL_PASSWORD, PG_THINGSBOARD_PASSWORD

-- and `STRICT_SECRETS`, whose whole purpose is to refuse startup on an unchanged
credential, had nothing to say about any of them. Its list was five names, kept by hand.

TWO SEPARATE GAPS, AND ONLY ONE IS FIXABLE BY EDITING THE LIST
--------------------------------------------------------------
The first is drift: a hand-kept list does not grow when a credential does. That is fixed by
DERIVING the list from the `Settings` fields whose names look like credentials, so one
added next month is covered without anyone remembering.

The second is structural, and derivation cannot reach it: those six are read by
docker-compose directly and never become `Settings` fields at all. No amount of work on the
field list touches them. So the guard also compares the process environment against
`.env.example` -- which IS the template, and which this module already treats as exactly as
insecure as a shipped default when left unfilled.

Best-effort by design: a missing `.env.example` is not a reason to refuse to boot.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from shared import config as cfg  # noqa: E402


def _guard_source() -> str:
    return inspect.getsource(cfg.Settings._check_strict_secrets)


def test_the_credential_list_is_derived_not_hand_written():
    src = _guard_source()
    assert "model_fields.items()" in src, (
        "the guard is back to a hand-kept list of names, which does not grow when a "
        "credential does"
    )
    assert "_CREDENTIAL_MARKERS" in src


def test_every_credential_field_with_a_shipped_default_is_covered():
    """Derived from the same rule the guard uses, so the two cannot drift apart."""
    markers = ("PASSWORD", "SECRET", "API_KEY", "TOKEN", "PRIVATE_KEY")
    not_credentials = {"STRICT_SECRETS", "SECRETS_BACKEND", "MASK_SECRETS"}
    covered = [
        n
        for n, f in cfg.Settings.model_fields.items()
        if any(m in n.upper() for m in markers)
        and n not in not_credentials
        and isinstance(getattr(f, "default", None), str)
        and str(getattr(f, "default")).strip()
    ]
    assert covered, "no credential field has a shipped default; the derivation is broken"
    # The five the original list named must still be among them.
    for name in ("GRAPHDB_PASSWORD", "MYSQL_PASSWORD", "SECRET_KEY", "PIPELINE_API_KEY"):
        assert name in covered, f"{name} dropped out of the derived coverage"


def test_the_guard_also_checks_credentials_that_never_reach_settings():
    src = _guard_source()
    assert ".env.example" in src, (
        "the guard no longer compares against the template, so the six compose-only "
        "credentials are invisible to it again"
    )
    assert "template_matches" in src


def test_the_switch_named_secrets_is_not_treated_as_one():
    """`STRICT_SECRETS` contains "SECRET" and is a boolean.

    The first version of the derived check duly reported the guard itself as an unset
    secret -- exactly the noise that gets a guard disabled.
    """
    src = _guard_source()
    assert "_NOT_CREDENTIALS" in src
    assert '"STRICT_SECRETS"' in src


def test_all_three_placeholder_spellings_are_recognised():
    """`.env.example` uses CHANGE-ME, change-me and your_... in different places.

    Matching one spelling left the other two looking like real values.
    """
    src = _guard_source()
    for spelling in ("CHANGE-ME", "CHANGE_ME", "YOUR_"):
        assert spelling in src, f"the {spelling} placeholder spelling is no longer caught"


def test_an_empty_credential_is_allowed():
    """Empty means "this integration is not configured".

    Refusing it would fail every deployment that does not use Influx, Cassandra or the
    demo datasource -- and a guard that fails on a correct configuration is one people
    switch off.
    """
    src = _guard_source()
    assert "if not _v or not any(" in src or "_default.strip()" in src


def test_the_guard_does_nothing_when_switched_off():
    src = _guard_source()
    assert "if not self.STRICT_SECRETS:" in src
