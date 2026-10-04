# -*- coding: utf-8 -*-
"""A4 (QA-trial plan, 2026-10-04).

`readonly: '*'` in `input/role_datasource_access.yaml` is ALREADY COMMITTED at
ab6c081 -- NOTE-1416's deliberate owner decision to open every data source to every
role for the trial. A fresh clone and every future deployment inherit it as-is, and
nothing reads the REAL file: every existing `tests/test_admin_config.py` reference
uses a `tmp_path` fixture, so a `readonly: '*'` that ships would pass every test in
this repo while granting the lowest-privilege role unrestricted access in production.

This test reads the ACTIVE building's real file via `admin_config.role_access_path()`
and fails specifically on `readonly == '*'` -- the one value NOTE-1416's own header
comment says must be restored before any non-trial deployment (`readonly: []`). It is
a tripwire for I2 (restore the per-role lists when the trial closes), not an assertion
that the open-access setting is wrong NOW.
"""
import pytest

from orchestrator.services import admin_config as ac

pytestmark = pytest.mark.unit


@pytest.mark.xfail(
    reason=(
        "NOTE-1416 (owner decision, 2026-10-02): readonly: '*' is deliberately "
        "shipped for the duration of the open trial. This test XPASSes the moment "
        "I2 restores the per-role lists when the trial closes, which is the signal "
        "I2 is done -- it must stay red (xfail, not skip) for as long as the trial "
        "setting is live, so a future session does not mistake the open state for "
        "the test being broken."
    ),
    strict=False,
)
def test_readonly_does_not_ship_unrestricted():
    path = ac.role_access_path()
    if not path.is_file():
        pytest.skip(f"no active building's role_datasource_access.yaml at {path}")
    roles = ac.read_role_access()
    readonly = roles.get("readonly")
    assert readonly != "*", (
        f"{path} grants readonly unrestricted data-source access ('*'). This is "
        "NOTE-1416's deliberate trial-only setting -- restore readonly: [] (see I2) "
        "before any non-trial deployment."
    )
