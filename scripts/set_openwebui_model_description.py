#!/usr/bin/env python
"""Set the Open WebUI model description and starter prompts for the OntoSage model (H3).

A tester opening a new chat sees a blank box, and the model table in Open WebUI has no row
for the OntoSage model, so it has no description. This writes one model row (the base is the
pipeline model the stack already exposes) with a description naming the active building and
six starter questions taken from `self_description.suggested_prompts()`.

Dry run by default: prints the payload and touches nothing. `--apply` signs in with the admin
account from `.env` (OPENWEBUI_ADMIN_EMAIL / OPENWEBUI_ADMIN_PASSWORD), then creates the row
or updates it if it exists. The password is read from settings and never printed or logged.

Endpoints relied on (Open WebUI 0.8.x; NOT verified against the running image, so the first
`--apply` must be checked in the Open WebUI admin screen):
  POST /api/v1/auths/signin                  {email, password} -> {token}
  GET  /api/v1/models/model?id=<id>          200 with a row, or 200 null / 404 when absent
  POST /api/v1/models/create                 ModelForm
  POST /api/v1/models/model/update?id=<id>   ModelForm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.services import openwebui_sync  # noqa: E402
from orchestrator.services.self_description import suggested_prompts  # noqa: E402
from shared.config import settings  # noqa: E402

#: The model id the stack exposes to Open WebUI (docker-compose DEFAULT_MODELS).
MODEL_ID = "ontobot-pipeline"
_TIMEOUT_SECONDS = 15.0


def building_name() -> str:
    """The active building's name, resolved from the building config, never a literal here."""
    from orchestrator.services.building_context import resolve_building_context

    return resolve_building_context(getattr(settings, "BUILDING_ID", None)).name


def model_description(name: str) -> str:
    """The description a tester reads on the model card. Names no internal lane."""
    label = (name or "").strip() or "this building"
    return (
        f"Ask about {label}: its rooms, floors, sensors, comfort, energy, maintenance and the "
        "documents it holds. Figures are read from the building's own sensor records and floor "
        "plans, and an answer lists the sources it used. A reply can take longer when several "
        "people are asking at once."
    )


def prompt_suggestions(questions: List[str]) -> List[Dict[str, Any]]:
    """Open WebUI's starter-prompt shape: each question is both the title and the content."""
    return [{"content": q, "title": [q, ""]} for q in questions]


def model_form(model_id: str, name: str, description: str, questions: List[str]) -> Dict[str, Any]:
    """The ModelForm body. Carries no credential: only what a tester reads."""
    return {
        "id": model_id,
        "base_model_id": model_id,
        "name": name or model_id,
        "meta": {
            "description": description,
            "suggestion_prompts": prompt_suggestions(questions),
        },
        "params": {},
        "is_active": True,
    }


async def _model_exists(
    client: httpx.AsyncClient, base: str, headers: Dict[str, str], model_id: str
) -> bool:
    resp = await client.get(f"{base}/api/v1/models/model", params={"id": model_id}, headers=headers)
    if resp.status_code == 404:
        return False
    if resp.status_code != 200:
        raise RuntimeError(f"model lookup returned HTTP {resp.status_code}")
    return bool(resp.json())


async def apply_model_form(
    client: httpx.AsyncClient, base: str, headers: Dict[str, str], form: Dict[str, Any]
) -> str:
    """Create the model row, or update it when it exists. Returns 'created' or 'updated'."""
    model_id = form["id"]
    if await _model_exists(client, base, headers, model_id):
        resp = await client.post(
            f"{base}/api/v1/models/model/update",
            params={"id": model_id},
            json=form,
            headers=headers,
        )
        verb = "updated"
    else:
        resp = await client.post(f"{base}/api/v1/models/create", json=form, headers=headers)
        verb = "created"
    if resp.status_code != 200:
        raise RuntimeError(f"model write ({verb}) returned HTTP {resp.status_code}")
    return verb


async def run(apply: bool, transport: Optional[httpx.AsyncBaseTransport] = None) -> int:
    """Print the payload (dry run) or apply it. Returns a process exit code."""
    name = building_name()
    form = model_form(MODEL_ID, name, model_description(name), suggested_prompts())
    if not apply:
        print(json.dumps(form, indent=2, ensure_ascii=False))
        print("\nDry run: nothing sent. Re-run with --apply to write to Open WebUI.")
        return 0

    admin_email = (settings.OPENWEBUI_ADMIN_EMAIL or "").strip()
    admin_password = settings.OPENWEBUI_ADMIN_PASSWORD or ""
    if not admin_email or not admin_password:
        print("skipped: OPENWEBUI_ADMIN_EMAIL or OPENWEBUI_ADMIN_PASSWORD is not set in .env")
        return 1

    base = (settings.OPENWEBUI_URL or "").rstrip("/")
    kwargs: Dict[str, Any] = {"timeout": _TIMEOUT_SECONDS}
    if transport is not None:
        kwargs["transport"] = transport
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            token = await openwebui_sync._signin(client, base, admin_email, admin_password)
            verb = await apply_model_form(client, base, {"Authorization": f"Bearer {token}"}, form)
    except (PermissionError, RuntimeError, httpx.HTTPError) as exc:
        print(f"failed: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"{verb}: model '{MODEL_ID}' with {len(form['meta']['suggestion_prompts'])} starter prompts"
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--apply", action="store_true", help="write to Open WebUI (default: dry run)"
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
