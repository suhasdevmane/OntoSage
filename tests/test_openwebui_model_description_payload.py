"""H3 (trial readiness, 2026-10-07): the Open WebUI model description and starter prompts.

Payload only. The script is loaded by path, because `scripts/` is not a package. Open WebUI is
mocked with httpx.MockTransport, so no network is used and the running image is NOT verified
here; the first `--apply` against the live stack is a coordinator step.

Pins:
* the description names the building it is given, names no internal lane, and does not claim
  a queue order (the hosted gateway runs several turns at once);
* the six starter prompts are the ones `self_description` ships, each with title and content;
* an existing model row is updated and an absent one is created;
* a dry run sends nothing, and nothing printed or returned carries the admin password.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from orchestrator.services import self_description

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "set_openwebui_model_description.py"
_spec = importlib.util.spec_from_file_location("set_openwebui_model_description", _PATH)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

SENTINEL_PASSWORD = "admin-password-sentinel-7f3a"
SENTINEL_TOKEN = "token-sentinel-9c1e"
BUILDING = "Test Hall"


def _settings(**overrides):
    values = {
        "OPENWEBUI_URL": "http://owui.test",
        "OPENWEBUI_ADMIN_EMAIL": "admin@example.com",
        "OPENWEBUI_ADMIN_PASSWORD": SENTINEL_PASSWORD,
        "BUILDING_ID": "not-used-when-patched",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _form():
    return script.model_form(
        script.MODEL_ID,
        BUILDING,
        script.model_description(BUILDING),
        script.suggested_prompts(),
    )


def test_the_description_names_the_building_it_is_given():
    assert BUILDING in script.model_description(BUILDING)


def test_the_description_falls_back_when_no_name_is_resolved():
    assert "this building" in script.model_description("")


def test_the_description_names_no_internal_lane():
    text = script.model_description(BUILDING).lower()
    for name in self_description._NOT_USER_FACING:
        assert name.lower() not in text, f"internal lane {name!r} leaked into the description"


def test_the_description_claims_no_queue_order():
    text = script.model_description(BUILDING).lower()
    assert "one at a time" not in text
    assert "in turn" not in text


def test_the_starter_prompts_are_the_shipped_six_with_title_and_content():
    prompts = script.prompt_suggestions(self_description.suggested_prompts())
    assert len(prompts) == 6
    assert [p["content"] for p in prompts] == self_description.suggested_prompts()
    for p in prompts:
        assert p["title"][0] == p["content"]


def test_the_form_targets_the_pipeline_model_as_its_own_base():
    form = _form()
    assert form["id"] == form["base_model_id"] == script.MODEL_ID
    assert form["meta"]["description"] == script.model_description(BUILDING)
    assert len(form["meta"]["suggestion_prompts"]) == 6


def test_the_form_carries_no_credential_field():
    dumped = json.dumps(_form())
    assert "password" not in dumped.lower()
    assert "token" not in dumped.lower()


def _recording_transport(model_exists: bool):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/api/v1/auths/signin":
            return httpx.Response(200, json={"token": SENTINEL_TOKEN})
        if request.url.path == "/api/v1/models/model":
            if model_exists:
                return httpx.Response(200, json={"id": script.MODEL_ID})
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), calls


def test_an_existing_model_row_is_updated_not_recreated():
    import asyncio

    transport, calls = _recording_transport(model_exists=True)

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await script.apply_model_form(
                client, "http://owui.test", {"Authorization": "Bearer x"}, _form()
            )

    assert asyncio.run(go()) == "updated"
    paths = [path for _, path, _ in calls]
    assert "/api/v1/models/model/update" in paths
    assert "/api/v1/models/create" not in paths


def test_an_absent_model_row_is_created():
    import asyncio

    transport, calls = _recording_transport(model_exists=False)

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await script.apply_model_form(
                client, "http://owui.test", {"Authorization": "Bearer x"}, _form()
            )

    assert asyncio.run(go()) == "created"
    assert "/api/v1/models/create" in [path for _, path, _ in calls]


def test_a_dry_run_prints_the_payload_and_sends_nothing(capsys):
    import asyncio

    transport, calls = _recording_transport(model_exists=False)
    with patch.object(script, "building_name", return_value=BUILDING), patch.object(
        script, "settings", _settings()
    ):
        code = asyncio.run(script.run(apply=False, transport=transport))
    out = capsys.readouterr().out
    assert code == 0
    assert calls == []
    assert BUILDING in out
    assert SENTINEL_PASSWORD not in out


def test_apply_without_admin_credentials_skips_and_says_which_is_missing(capsys):
    import asyncio

    with patch.object(script, "building_name", return_value=BUILDING), patch.object(
        script, "settings", _settings(OPENWEBUI_ADMIN_EMAIL="")
    ):
        code = asyncio.run(script.run(apply=True))
    out = capsys.readouterr().out
    assert code == 1
    assert "OPENWEBUI_ADMIN_EMAIL" in out
    assert SENTINEL_PASSWORD not in out


def test_apply_writes_the_row_and_never_prints_the_password_or_token(capsys):
    import asyncio

    transport, calls = _recording_transport(model_exists=False)
    with patch.object(script, "building_name", return_value=BUILDING), patch.object(
        script, "settings", _settings()
    ):
        code = asyncio.run(script.run(apply=True, transport=transport))
    captured = capsys.readouterr()
    assert code == 0
    assert "created" in captured.out
    assert SENTINEL_PASSWORD not in captured.out + captured.err
    assert SENTINEL_TOKEN not in captured.out + captured.err
    assert ("POST", "/api/v1/auths/signin", {}) in calls


def test_a_rejected_sign_in_fails_with_the_status_and_no_secret(capsys):
    import asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad"})

    transport = httpx.MockTransport(handler)
    with patch.object(script, "building_name", return_value=BUILDING), patch.object(
        script, "settings", _settings()
    ):
        code = asyncio.run(script.run(apply=True, transport=transport))
    out = capsys.readouterr().out
    assert code == 1
    assert "HTTP 401" in out
    assert SENTINEL_PASSWORD not in out
