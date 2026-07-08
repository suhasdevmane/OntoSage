"""
Phase 5 guard tests — config-panel static assets + compose wiring exist and
reference the endpoints the panel depends on. Cheap; no browser/stack needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "config-panel"


def test_panel_files_exist():
    for rel in ("nginx.conf", "html/index.html", "html/app.js", "html/style.css"):
        assert (PANEL / rel).is_file(), f"missing {rel}"


def test_nginx_proxies_to_orchestrator():
    conf = (PANEL / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://orchestrator:8000" in conf
    assert "location /api/" in conf and "location /auth/" in conf
    assert "location = /health" in conf  # Health tab


def test_app_calls_admin_api():
    js = (PANEL / "html" / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/datasources" in js
    # enable/disable are built via a ${verb} template, so match the tokens
    assert '"enable"' in js and '"disable"' in js
    assert "/regenerate" in js and "/preview" in js
    assert "/auth/login" in js
    # add-source (create) flow
    assert "createSource" in js and 'method: "POST"' in js
    # admin console: .env + databases + health + users/access
    assert "/api/v1/admin/env" in js and "/api/v1/admin/databases" in js
    assert "saveEnv" in js and "createDatabase" in js and "loadHealth" in js
    assert "/api/v1/admin/users" in js and "/api/v1/admin/role-access" in js
    assert "createUser" in js and "saveRoleAccess" in js
    # database ops: test / delete / data-preview / CSV sensor import
    assert "/api/v1/admin/databases/test" in js and "testDatabase" in js
    assert "deleteDatabaseConn" in js and "showDataPreview" in js
    assert "/sensors/csv" in js and "testNewConnection" in js
    # active/dormant badge + filter
    assert "dbActiveOnly" in js and "renderDbCards" in js
    html = (PANEL / "html" / "index.html").read_text(encoding="utf-8")
    assert 'id="db-active-only"' in html
    # external-DB sensor registration (TTL + points)
    assert "/sensors" in js and "submitSensors" in js and "openSensors" in js
    # restart button + live status
    assert "/api/v1/admin/restart" in js and "restartOrchestrator" in js and "pollHealthUntilUp" in js


def test_contextual_apply_notice():
    html = (PANEL / "html" / "index.html").read_text(encoding="utf-8")
    js = (PANEL / "html" / "app.js").read_text(encoding="utf-8")
    # a single contextual notice (only shown after a change), with copy/restart + close
    assert 'id="apply-notice"' in html and 'id="apply-close"' in html
    assert "data-restart" in html and "data-copy" in html
    # shown only on recreate-needing changes; auto-vanishes; closable
    assert "showRecreateNotice" in js and "hideNotice" in js
    assert "_noticeTimer" in js  # auto-vanish timer


def test_capabilities_catalog_valid_and_complete():
    """The per-modality capabilities catalogue parses and covers every seed
    modality with summary + stakeholder groups (capabilities + questions)."""
    import json

    cat = json.loads((PANEL / "html" / "capabilities.json").read_text(encoding="utf-8"))
    for mod in ("occupancy", "energy", "noise", "iaq", "light", "equipment", "water", "complaints"):
        assert mod in cat, f"missing modality {mod}"
        entry = cat[mod]
        assert entry.get("summary") and entry.get("groups"), f"{mod} incomplete"
        for g in entry["groups"]:
            assert g.get("stakeholder") and g.get("capabilities") and g.get("questions")


def test_details_modal_wired():
    js = (PANEL / "html" / "app.js").read_text(encoding="utf-8")
    html = (PANEL / "html" / "index.html").read_text(encoding="utf-8")
    assert "showDetails" in js and "loadCatalog" in js and "capabilities.json" in js
    assert "data-details" in js
    assert 'id="details-modal"' in html and 'id="details-groups"' in html


def test_hidden_display_flex_elements_have_hidden_override():
    """Any element toggled via the HTML `hidden` attribute whose CSS sets
    display:flex MUST also declare `[hidden]{display:none}` — otherwise the class
    rule overrides `hidden` and the element is always visible (the modal-stacking /
    always-on-notice bug). Guards apply-notice + modal-backdrop."""
    css = (PANEL / "html" / "style.css").read_text(encoding="utf-8")
    for sel in (".apply-notice", ".modal-backdrop"):
        assert f"{sel}[hidden]" in css, f"{sel} lacks a [hidden] display:none override"
    html = (PANEL / "html" / "index.html").read_text(encoding="utf-8")
    assert 'id="add-src"' in html and 'id="add-modal"' in html


def test_panel_has_all_tabs():
    html = (PANEL / "html" / "index.html").read_text(encoding="utf-8")
    for tab in ("sources", "settings", "databases", "users", "health"):
        assert f'data-tab="{tab}"' in html, f"missing nav for {tab}"
        assert f'id="tab-{tab}"' in html, f"missing panel for {tab}"


def test_compose_registers_config_panel():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "config-panel:" in compose
    assert "3001:80" in compose
    assert "./config-panel/html:/usr/share/nginx/html" in compose
