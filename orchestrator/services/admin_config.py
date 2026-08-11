"""
admin_config.py — read/write the root .env and database connections for the
admin console (the localhost:3001 control panel).

Design properties
-----------------
* **.env round-trip** preserves comments, blank lines, and key order — only the
  changed keys' values are rewritten in place; new keys are appended. A
  hand-maintained .env stays readable.
* **Secrets are masked.** Any key that looks like a credential (PASSWORD, SECRET,
  TOKEN, KEY, …) is returned as ``MASK``; on write, an incoming value equal to
  ``MASK`` is treated as "unchanged" and is NOT written back — so the GUI can
  round-trip a form without leaking or clobbering secrets.
* **Databases** are added to a ``database_registry.custom.yaml`` OVERLAY (the
  curated, heavily-documented ``database_registry.yaml`` is never rewritten). A
  connection is stored as ``${ENV}`` references and the values are written to
  .env — so credentials live in .env, exactly as the operator expects, and are
  used automatically when a UUID's ``ref:storedAt`` routes to that DB.

Nothing here takes effect on a running orchestrator until it restarts — env is
read at boot. Callers surface a "restart required" flag to the UI.
"""

from __future__ import annotations

import asyncio
import csv
import datetime as _dt
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from shared.utils import get_logger

# Optional DB drivers — imported at module level so tests can monkeypatch them.
try:  # MySQL / MariaDB family
    import pymysql as _pymysql
except ImportError:  # pragma: no cover
    _pymysql = None  # type: ignore[assignment]
try:  # PostgreSQL / TimescaleDB family
    import asyncpg as _asyncpg
except ImportError:  # pragma: no cover
    _asyncpg = None  # type: ignore[assignment]

_MYSQL_TYPES = {"mysql", "mysql_narrow"}
_PG_TYPES = {"postgresql", "timescaledb"}

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

logger = get_logger(__name__)

# Sentinel shown in place of a secret's value; a submitted value equal to this is
# treated as "unchanged" and skipped on write. Deliberately distinctive (bullets, not
# asterisks) so a real secret can't realistically collide with it — the GUI also only
# submits fields the operator actually edited, so this is a secondary guard.
MASK = "••••••••"

# A key is treated as secret (value masked) if it contains any of these tokens.
_SECRET_HINTS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "PRIVATE",
    "ACCESS_KEY",
    "CREDENTIAL",
    "PASSWD",
    "PWD",
)

_ENV_SEARCH_PATHS = [Path("/app/.env"), Path(".env")]
_DB_PRIMARY_PATHS = [
    Path("/app/input/database_registry.yaml"),
    Path("input/database_registry.yaml"),
    Path("/app/config/database_registry.yaml"),
    Path("config/database_registry.yaml"),
]

# SQL-family connection shapes the "add database" form supports out of the box.
_SQL_TYPES = {"mysql", "mysql_narrow", "postgresql", "timescaledb"}

_KV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def is_secret(key: str) -> bool:
    """True if the key name looks like a credential and should be masked."""
    up = key.upper()
    return any(h in up for h in _SECRET_HINTS)


# URL/DSN with inline user:pass@ credentials — e.g. redis://u:p@host, mongodb://…,
# postgres://…. These leak secrets even when the KEY name has no secret token
# (REDIS_URL, MONGODB_URI, DATABASE_URL), so mask by VALUE shape too.
_EMBEDDED_CRED_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def value_has_embedded_credentials(value: str) -> bool:
    """True if a value is a URL/DSN carrying inline ``user:pass@`` credentials."""
    return bool(_EMBEDDED_CRED_RE.search(value or ""))


# ── .env resolution ──────────────────────────────────────────────────────────


def env_path() -> Path:
    """First existing .env path, else the first candidate (for first write)."""
    for p in _ENV_SEARCH_PATHS:
        if p.is_file():
            return p
    return _ENV_SEARCH_PATHS[0] if Path("/app").exists() else _ENV_SEARCH_PATHS[-1]


def _read_env_text(path: Optional[Path] = None) -> str:
    p = path or env_path()
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


# ── .env read / write ────────────────────────────────────────────────────────


def read_env(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return the .env as an ordered list of {key, value, is_secret}.

    Secret values are masked. Comment/blank lines are omitted from the result
    (they are preserved on write, just not shown as editable rows).
    """
    out: List[Dict[str, Any]] = []
    for line in _read_env_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        # Mask by key name OR by value shape (a URL/DSN with inline credentials
        # leaks even when the key name has no secret token, e.g. REDIS_URL).
        secret = is_secret(key) or value_has_embedded_credentials(raw)
        out.append(
            {
                "key": key,
                "value": MASK if (secret and raw) else raw,
                "is_secret": secret,
            }
        )
    return out


def apply_env(changes: Dict[str, str], path: Optional[Path] = None) -> Dict[str, Any]:
    """Update/append keys in .env, preserving comments + order.

    Rules:
      * a change whose value == MASK is skipped (unchanged secret).
      * an existing ``KEY=`` line has its value replaced in place.
      * a new key is appended at the end.
    Returns a summary {updated: [...], added: [...], skipped: [...]}.
    """
    p = path or env_path()
    text = _read_env_text(p)
    lines = text.splitlines()

    # Index existing KEY= lines.
    key_line: Dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _KV_RE.match(line)
        if m and not line.strip().startswith("#"):
            key_line[m.group(1)] = i

    summary: Dict[str, List[str]] = {"updated": [], "added": [], "skipped": []}
    appended: List[str] = []
    for key, value in changes.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            summary["skipped"].append(f"{key} (invalid name)")
            continue
        # Reject CR/LF in a value: a newline would inject extra KEY=value lines
        # into .env (e.g. value="x\nADMIN_PASSWORD=pwned").
        if "\n" in value or "\r" in value:
            summary["skipped"].append(f"{key} (newline in value rejected)")
            continue
        if value == MASK:
            summary["skipped"].append(key)  # unchanged secret
            continue
        new_line = f"{key}={value}"
        if key in key_line:
            lines[key_line[key]] = new_line
            summary["updated"].append(key)
        else:
            appended.append(new_line)
            summary["added"].append(key)

    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# ── Added via admin console ──")
        lines.extend(appended)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(
        f"[admin_config] .env updated={summary['updated']} added={summary['added']} "
        f"skipped={len(summary['skipped'])} → {p}"
    )
    return summary


# ── database_registry.yaml (read curated + custom overlay) ─────────────────────


def _db_primary_path() -> Optional[Path]:
    for p in _DB_PRIMARY_PATHS:
        if p.is_file():
            return p
    return None


def db_custom_path() -> Path:
    """Overlay file for GUI-added DB connections (keeps the curated registry pristine)."""
    primary = _db_primary_path()
    base = (
        primary.parent
        if primary
        else (Path("/app/input") if Path("/app/input").exists() else Path("input"))
    )
    return base / "database_registry.custom.yaml"


def _mask_conn(conn: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in conn.items():
        out[k] = MASK if (is_secret(k) and v) else v
    return out


def read_databases() -> List[Dict[str, Any]]:
    """Return DB connections from the curated registry + custom overlay (masked).

    Each item: {key, type, fields{...masked}, source: 'curated'|'custom'}.
    """
    items: List[Dict[str, Any]] = []
    seen = set()

    def _ingest(path: Optional[Path], source: str) -> None:
        if not path or not Path(path).is_file():
            return
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[admin_config] could not parse {path}: {e}")
            return
        dbs = data.get("databases", {})
        if not isinstance(dbs, dict):
            return
        for key, conn in dbs.items():
            if key in seen or not isinstance(conn, dict):
                continue
            seen.add(key)
            items.append(
                {
                    "key": key,
                    "type": conn.get("type", "?"),
                    "fields": _mask_conn(
                        {k: v for k, v in conn.items() if k not in ("type", "nature", "note")}
                    ),
                    "source": source,
                    # Real vs synthetic DATA SOURCE. Each building declares this per
                    # connection via `nature:` in its own database_registry.yaml;
                    # absent => synthetic, so a source is never claimed to be real
                    # unless the building says so. `note` is the human hint on the card.
                    "nature": conn.get("nature", "synthetic"),
                    "note": conn.get("note", ""),
                }
            )

    _ingest(_db_primary_path(), "curated")
    _ingest(db_custom_path(), "custom")
    return items


def _input_dir() -> Path:
    for p in (Path("/app/input"), Path("input")):
        if p.exists():
            return p
    return Path("input")


# ── Building identity (namespace / prefix) — the per-building ontology prereq ────
# The `bldg:` prefix is only a label; the NAMESPACE it binds to is per-building and
# lives in input/building.yaml (`ontology_namespace`). config.py reads it at boot.
# The admin console edits it here as an alternative to hand-editing the file.

_NCNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")


def building_yaml_path() -> Path:
    """The active building's building.yaml (rw, under input/)."""
    return _input_dir() / "building.yaml"


def read_building_config() -> Dict[str, Any]:
    """Current building identity — from building.yaml, falling back to live settings.

    Returns ``{building_id, building_name, ontology_namespace, ontology_prefix, path, exists}``.
    """
    from shared.config import settings

    p = building_yaml_path()
    data: Dict[str, Any] = {}
    if p.is_file():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[admin_config] could not parse {p}: {e}")
            data = {}
    return {
        "building_id": data.get("building_id") or settings.BUILDING_ID,
        "building_name": data.get("building_name") or settings.BUILDING_NAME,
        "ontology_namespace": data.get("ontology_namespace") or settings.BUILDING_NAMESPACE,
        "ontology_prefix": data.get("ontology_prefix") or settings.BUILDING_PREFIX,
        # Building-level data provenance (real | synthetic | mixed) — a statement about
        # the whole building including its ontology and sensors, which per-connection
        # `nature:` in database_registry.yaml cannot express. Absent → unstated, and
        # callers must not guess on the building's behalf.
        "provenance": data.get("provenance") or {},
        "path": str(p),
        "exists": p.is_file(),
    }


def _set_yaml_scalar(text: str, key: str, value: str) -> str:
    """Set a TOP-LEVEL scalar ``key: value`` in YAML text, preserving comments/order.

    Replaces the existing top-level line if present (line-based, so inline docs survive),
    otherwise appends it. The replacement line is produced by ``yaml.safe_dump`` so the value is
    quoted only when YAML actually requires it (URIs like ``http://x#`` stay unquoted). Only safe
    for top-level scalar keys — which is exactly what the building identity fields are.
    """
    line = yaml.safe_dump({key: value}, default_flow_style=False, allow_unicode=True).strip()
    pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
    if pat.search(text):
        return pat.sub(lambda _m: line, text, count=1)  # lambda: no backref interpretation
    sep = "" if text.endswith("\n") or text == "" else "\n"
    return f"{text}{sep}{line}\n"


def write_building_config(
    ontology_namespace: str,
    ontology_prefix: str = "bldg",
    building_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate + persist the building identity into input/building.yaml (atomic, in place).

    Namespace must be an absolute URI ending in ``#`` or ``/`` (Brick/BACnet ABox convention);
    prefix must be a valid SPARQL prefix label. Takes effect after an orchestrator restart
    (building.yaml is read at boot). Returns ``{ok, error, ...read_building_config()}``.
    """
    ns = (ontology_namespace or "").strip()
    prefix = (ontology_prefix or "").strip()
    if not (ns.startswith("http://") or ns.startswith("https://")):
        return {"ok": False, "error": "namespace must be an absolute http(s) URI"}
    if not ns.endswith("#") and not ns.endswith("/"):
        return {"ok": False, "error": "namespace must end with '#' or '/'"}
    if len(ns) > 300 or any(c in ns for c in (" ", "\n", "\t", "<", ">", '"')):
        return {"ok": False, "error": "namespace contains invalid characters"}
    if not _NCNAME_RE.match(prefix):
        return {
            "ok": False,
            "error": "prefix must start with a letter (letters, digits, _ . - only)",
        }

    p = building_yaml_path()
    try:
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        text = _set_yaml_scalar(text, "ontology_namespace", ns)
        text = _set_yaml_scalar(text, "ontology_prefix", prefix)
        if building_name is not None and building_name.strip():
            text = _set_yaml_scalar(text, "building_name", building_name.strip())
        # Validate the result still parses before committing.
        yaml.safe_load(text)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(p))
    except Exception as e:
        logger.error(f"[admin_config] write_building_config failed: {e}", exc_info=True)
        return {"ok": False, "error": f"could not write building.yaml: {e}"}

    logger.info(f"[admin_config] building identity saved: ns={ns!r} prefix={prefix!r}")
    result = read_building_config()
    result["ok"] = True
    result["error"] = None
    return result


def role_access_path() -> Path:
    """role → allowed data-sources map (rw, in input/ so the console can edit it)."""
    return _input_dir() / "role_datasource_access.yaml"


def read_role_access() -> Dict[str, Any]:
    """{role: ['src', ...] | '*'} — a role absent from the map is unrestricted."""
    p = role_access_path()
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        roles = data.get("roles", {})
        return roles if isinstance(roles, dict) else {}
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[admin_config] could not parse {p}: {e}")
        return {}


def set_role_access(role: str, sources: Any) -> Dict[str, Any]:
    """Set a role's allowed sources ('*' or a list). Persists to input/."""
    p = role_access_path()
    doc: Dict[str, Any] = {"roles": {}}
    if p.is_file():
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or doc
        except Exception as e:
            raise ValueError(f"role-access file unreadable: {e}") from e
    if not isinstance(doc.get("roles"), dict):
        doc["roles"] = {}
    doc["roles"][role] = "*" if sources in ("*", ["*"]) else list(sources)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    except OSError as e:
        raise ValueError(f"could not write {p} ({e}). Is ./input read-write?") from e
    logger.info(f"[admin_config] role access set: {role} -> {doc['roles'][role]}")
    return {"ok": True, "role": role, "sources": doc["roles"][role]}


def is_source_allowed(
    role: Optional[str], source_id: str, access_map: Optional[Dict] = None
) -> bool:
    """True if `role` may use data source `source_id`.

    admin is always allowed; a role not listed in the map is unrestricted
    (permissive default → access control is opt-in per role).
    """
    if role == "admin":
        return True
    amap = read_role_access() if access_map is None else access_map
    if role not in amap:
        return True
    allowed = amap[role]
    if allowed == "*":
        return True
    return source_id in (allowed or [])


def active_db_keys(input_root: Optional[Path] = None) -> Optional[set]:
    """Connection keys the active building actually initializes, from
    ``building.yaml`` ``storage.databases``. Returns None when there is no filter
    (legacy: every connection is initialized)."""
    roots = [Path(input_root)] if input_root else [Path("/app/input"), Path("input")]
    for base in roots:
        p = base / "building.yaml"
        if p.is_file():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:  # pragma: no cover
                return None
            dbs = ((data.get("storage") or {}).get("databases")) or []
            return set(dbs) if dbs else None
    return None


def add_database(
    key: str,
    db_type: str,
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
    table: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a SQL-family DB connection: overlay entry (${ENV} refs) + values in .env.

    The connection is used automatically when a sensor UUID's ``ref:storedAt``
    points to ``key`` — after an orchestrator restart. Returns a summary.

    ``table`` is required for ``mysql_narrow`` (the adapter reads ``cfg["table"]``);
    ignored for the wide ``mysql`` type.
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ValueError("database key must be alphanumeric/underscore")
    if db_type not in _SQL_TYPES:
        raise ValueError(f"unsupported type '{db_type}' (supported: {sorted(_SQL_TYPES)})")
    if db_type == "mysql_narrow" and not (table or "").strip():
        raise ValueError("mysql_narrow requires a 'table' (the narrow uuid/datetime/value table)")

    # Existing keys anywhere in the registry are off-limits (avoid shadowing).
    if any(item["key"] == key for item in read_databases()):
        raise ValueError(f"database key '{key}' already exists")

    prefix = key.upper()
    env_changes = {
        f"{prefix}_HOST": host,
        f"{prefix}_PORT": str(port or "3306"),
        f"{prefix}_USER": user,
        f"{prefix}_PASSWORD": password,
        f"{prefix}_DATABASE": database,
    }
    entry: Dict[str, Any] = {
        "type": db_type,
        "host": f"${{{prefix}_HOST}}",
        "port": f"${{{prefix}_PORT}}",
        "user": f"${{{prefix}_USER}}",
        "password": f"${{{prefix}_PASSWORD}}",
        "database": f"${{{prefix}_DATABASE}}",
    }
    # Narrow tables carry a fixed table name (not a secret) directly in the entry.
    if (table or "").strip():
        entry["table"] = table.strip()

    # 1) persist the overlay registry entry
    path = db_custom_path()
    doc: Dict[str, Any] = {"databases": {}}
    if path.is_file():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or doc
        except Exception as e:
            raise ValueError(f"custom registry unreadable: {e}") from e
    if not isinstance(doc.get("databases"), dict):
        doc["databases"] = {}
    doc["databases"][key] = entry
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    except OSError as e:
        raise ValueError(f"could not write {path} ({e}). Is ./input mounted read-write?") from e

    # 2) persist the credential values to .env
    apply_env(env_changes)
    # 3) make the running process see them now (no restart): resolve_connection()
    #    expands ${VAR} against os.environ, so keep it consistent with the .env we
    #    just wrote. The caller still reloads the adapter pool for the query path.
    os.environ.update({k: str(v) for k, v in env_changes.items()})
    logger.info(f"[admin_config] added database '{key}' ({db_type}) → {path.name} + .env")
    return {"ok": True, "key": key, "env_keys": list(env_changes.keys()), "restart_required": True}


def delete_database(key: str) -> Dict[str, Any]:
    """Delete a GUI-added (custom-overlay) connection. Curated entries are protected."""
    path = db_custom_path()
    if not path.is_file():
        raise ValueError(f"no custom connections file — '{key}' is not GUI-added")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ValueError(f"custom registry unreadable: {e}") from e
    dbs = doc.get("databases", {})
    if not isinstance(dbs, dict) or key not in dbs:
        raise ValueError(
            f"'{key}' is not a GUI-added connection (curated entries can't be deleted)"
        )
    dbs.pop(key)
    doc["databases"] = dbs
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    logger.info(f"[admin_config] deleted custom database '{key}'")
    return {"ok": True, "key": key, "restart_required": True}


# ── Connection resolution + live probes (test / introspect / preview) ──────────


def resolve_env_value(v: Any) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` references against os.environ."""
    if not isinstance(v, str):
        return v

    def _sub(m: "re.Match") -> str:
        var, default = m.group(1), m.group(2)
        return os.environ.get(var, default if default is not None else "")

    return _ENV_REF.sub(_sub, v)


def _registry_entry(key: str) -> Optional[Dict[str, Any]]:
    """Raw (unmasked) connection entry for a key, from curated + custom registries."""
    for path in (_db_primary_path(), db_custom_path()):
        if not path or not Path(path).is_file():
            continue
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except Exception:  # pragma: no cover
            continue
        conn = (data.get("databases", {}) or {}).get(key)
        if isinstance(conn, dict):
            return conn
    return None


def resolve_connection(key: str) -> Optional[Dict[str, Any]]:
    """Resolved (env-expanded) creds for an existing connection key, or None."""
    conn = _registry_entry(key)
    if conn is None:
        return None
    return {
        "type": conn.get("type", "mysql"),
        "host": resolve_env_value(conn.get("host", "")),
        "port": resolve_env_value(conn.get("port", "")),
        "user": resolve_env_value(conn.get("user", "")),
        "password": resolve_env_value(conn.get("password", "")),
        "database": resolve_env_value(conn.get("database", "")),
        # Table hint (narrow adapters store the timeseries table here) — needed so
        # UUID/answerability resolution targets the RIGHT table, not a guessed one.
        "table": conn.get("table", ""),
        "ts_table": conn.get("ts_table", ""),
    }


def _mysql_connect(host, port, user, password, database, timeout=8):
    return _pymysql.connect(
        host=host or "localhost",
        port=int(port or 3306),
        user=user or "root",
        password=password or "",
        database=database or None,
        connect_timeout=timeout,
        read_timeout=timeout,
    )


async def _pg_connect(host, port, user, password, database, timeout=8):
    return await _asyncpg.connect(
        host=host or "localhost",
        port=int(port or 5432),
        user=user or "postgres",
        password=password or None,
        database=database or "postgres",
        timeout=timeout,
    )


async def test_connection(
    db_type: str, host: str, port: str, user: str, password: str, database: str
) -> Dict[str, Any]:
    """Try to connect + run ``SELECT 1``. Returns {ok, latency_ms, error?}."""
    start = time.time()
    try:
        if db_type in _MYSQL_TYPES:
            if _pymysql is None:
                return {"ok": False, "error": "pymysql not installed"}

            def _probe():
                conn = _mysql_connect(host, port, user, password, database)
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
                finally:
                    conn.close()

            await asyncio.get_event_loop().run_in_executor(None, _probe)
        elif db_type in _PG_TYPES:
            if _asyncpg is None:
                return {"ok": False, "error": "asyncpg not installed"}
            conn = await _pg_connect(host, port, user, password, database)
            try:
                await conn.fetchval("SELECT 1")
            finally:
                await conn.close()
        else:
            return {"ok": False, "error": f"unsupported type '{db_type}'"}
        return {"ok": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": round((time.time() - start) * 1000, 1)}


async def introspect(
    db_type: str, host: str, port: str, user: str, password: str, database: str
) -> Dict[str, Any]:
    """List tables + their columns so an admin can map them to sensors."""
    try:
        if db_type in _MYSQL_TYPES:
            if _pymysql is None:
                return {"ok": False, "error": "pymysql not installed"}

            def _probe():
                conn = _mysql_connect(host, port, user, password, database)
                out = []
                try:
                    with conn.cursor() as cur:
                        cur.execute("SHOW TABLES")
                        tables = [r[0] for r in cur.fetchall()]
                        for t in tables[:200]:
                            cur.execute(f"SHOW COLUMNS FROM `{t}`")
                            cols = [{"name": c[0], "type": c[1]} for c in cur.fetchall()]
                            out.append({"name": t, "columns": cols})
                finally:
                    conn.close()
                return out

            tables = await asyncio.get_event_loop().run_in_executor(None, _probe)
        elif db_type in _PG_TYPES:
            if _asyncpg is None:
                return {"ok": False, "error": "asyncpg not installed"}
            conn = await _pg_connect(host, port, user, password, database)
            try:
                rows = await conn.fetch(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
                )
            finally:
                await conn.close()
            grouped: Dict[str, List[Dict[str, str]]] = {}
            for r in rows:
                grouped.setdefault(r["table_name"], []).append(
                    {"name": r["column_name"], "type": r["data_type"]}
                )
            tables = [{"name": k, "columns": v} for k, v in grouped.items()]
        else:
            return {"ok": False, "error": f"unsupported type '{db_type}'"}
        return {"ok": True, "tables": tables}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def distinct_uuids(
    db_type: str,
    host: str,
    port: str,
    user: str,
    password: str,
    database: str,
    table: str,
    limit: int = 500,
) -> Dict[str, Any]:
    """Distinct timeseries UUIDs in a (narrow) table, so the guided sensor form can map real
    ids from the datasource instead of hand-typed UUIDs. Returns {ok, uuids: [...], error?}."""
    if not re.match(r"^[A-Za-z0-9_]+$", table or ""):
        return {"ok": False, "error": "invalid table name"}
    n = max(1, min(int(limit or 500), 5000))
    try:
        if db_type in _MYSQL_TYPES:
            if _pymysql is None:
                return {"ok": False, "error": "pymysql not installed"}

            def _probe():
                conn = _mysql_connect(host, port, user, password, database)
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT DISTINCT `uuid` FROM `{table}` LIMIT {n}")
                        return [r[0] for r in cur.fetchall()]
                finally:
                    conn.close()

            uuids = await asyncio.get_event_loop().run_in_executor(None, _probe)
        elif db_type in _PG_TYPES:
            if _asyncpg is None:
                return {"ok": False, "error": "asyncpg not installed"}
            conn = await _pg_connect(host, port, user, password, database)
            try:
                rows = await conn.fetch(f'SELECT DISTINCT "uuid" FROM "{table}" LIMIT {n}')
            finally:
                await conn.close()
            uuids = [r["uuid"] for r in rows]
        else:
            return {"ok": False, "error": f"unsupported type '{db_type}'"}
        return {"ok": True, "uuids": [str(u) for u in uuids if u]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def table_stats(
    db_type: str, host: str, port: str, user: str, password: str, database: str, table: str
) -> Dict[str, Any]:
    """Row count + distinct-uuid count + recent sample for a (narrow) table."""
    if not re.match(r"^[A-Za-z0-9_]+$", table or ""):
        return {"ok": False, "error": "invalid table name"}
    try:
        if db_type in _MYSQL_TYPES:
            if _pymysql is None:
                return {"ok": False, "error": "pymysql not installed"}

            def _probe():
                conn = _mysql_connect(host, port, user, password, database)
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                        n = cur.fetchone()[0]
                        uuids = None
                        sample = []
                        try:
                            cur.execute(f"SELECT COUNT(DISTINCT `uuid`) FROM `{table}`")
                            uuids = cur.fetchone()[0]
                            cur.execute(
                                f"SELECT `uuid`,`datetime`,`value` FROM `{table}` "
                                "ORDER BY `datetime` DESC LIMIT 8"
                            )
                            sample = [
                                {"uuid": str(r[0]), "datetime": str(r[1]), "value": r[2]}
                                for r in cur.fetchall()
                            ]
                        except Exception:
                            pass  # not a narrow table — count only
                        return n, uuids, sample
                finally:
                    conn.close()

            n, uuids, sample = await asyncio.get_event_loop().run_in_executor(None, _probe)
        elif db_type in _PG_TYPES:
            if _asyncpg is None:
                return {"ok": False, "error": "asyncpg not installed"}
            conn = await _pg_connect(host, port, user, password, database)
            try:
                n = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
                uuids, sample = None, []
                try:
                    uuids = await conn.fetchval(f'SELECT COUNT(DISTINCT "uuid") FROM "{table}"')
                    rows = await conn.fetch(
                        f'SELECT "uuid","datetime","value" FROM "{table}" '
                        'ORDER BY "datetime" DESC LIMIT 8'
                    )
                    sample = [
                        {
                            "uuid": str(r["uuid"]),
                            "datetime": str(r["datetime"]),
                            "value": r["value"],
                        }
                        for r in rows
                    ]
                except Exception:
                    pass
            finally:
                await conn.close()
        else:
            return {"ok": False, "error": f"unsupported type '{db_type}'"}
        return {"ok": True, "table": table, "rows": n, "sensors": uuids, "sample": sample}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def parse_sensor_csv(text: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Parse a CSV of sensors into point dicts. Header:
    ``local,brick_class,location,uuid[,unit,label]``. Returns (points, issues)."""
    issues: List[str] = []
    points: List[Dict[str, str]] = []
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        return [], ["empty CSV"]
    cols = {c.strip().lower() for c in reader.fieldnames}
    required = {"local", "brick_class", "location", "uuid"}
    missing = required - cols
    if missing:
        return [], [f"missing columns: {sorted(missing)} (need local,brick_class,location,uuid)"]
    for i, row in enumerate(reader, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(r.get(k) for k in required):
            continue  # blank line
        miss = [k for k in required if not r.get(k)]
        if miss:
            issues.append(f"row {i}: missing {miss}")
            continue
        pt = {k: r[k] for k in ("local", "brick_class", "location", "uuid")}
        if r.get("unit"):
            pt["unit"] = r["unit"]
        if r.get("label"):
            pt["label"] = r["label"]
        points.append(pt)
    return points, issues


# ── Config backup / restore ─────────────────────────────────────────────────────
# Snapshot + restore the files an admin authors through the console. Excludes .env
# on purpose: it holds secrets, and a downloadable backup of secrets is a footgun —
# credentials stay in the .env editor. GraphDB named graphs / narrow-table rows are
# runtime-derived (re-enable a source or re-register sensors to recreate them), so
# they're not in the bundle either.


def _managed_config_targets() -> Dict[str, Path]:
    """Logical name → resolved path for each console-managed config file."""
    idir = _input_dir()
    targets: Dict[str, Path] = {
        "datasources.custom.yaml": idir / "datasources.custom.yaml",
        "database_registry.custom.yaml": db_custom_path(),
        "role_datasource_access.yaml": role_access_path(),
    }
    # Datasource toggle-state (which sources are enabled + last_generated/row_count).
    for p in (
        Path("/app/volumes/artifacts/.datasource_state.json"),
        Path("volumes/artifacts/.datasource_state.json"),
    ):
        if p.parent.exists():
            targets["datasource_state.json"] = p
            break
    return targets


def backup_config() -> Dict[str, Any]:
    """Return a portable bundle of the console-managed config files (no secrets)."""
    files: Dict[str, Optional[str]] = {}
    for name, path in _managed_config_targets().items():
        try:
            files[name] = path.read_text(encoding="utf-8") if path.is_file() else None
        except Exception as e:  # pragma: no cover - defensive
            files[name] = None
            logger.warning(f"[config_backup] could not read {path}: {e}")
    return {
        "meta": {
            "version": 1,
            "kind": "ontosage-console-config",
            "created_at": _dt.datetime.utcnow().isoformat() + "Z",
            "excludes": [".env (secrets are never backed up)"],
        },
        "files": files,
    }


def restore_config(bundle: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    """Validate then write a backup bundle back to disk. Atomic: aborts if any file
    is malformed (nothing is written). Restart needed for registry reloads.
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get("files"), dict):
        raise ValueError("invalid backup: missing 'files' object")
    targets = _managed_config_targets()
    summary: Dict[str, Any] = {"restored": [], "skipped": [], "invalid": []}
    to_write: List[Tuple[Path, str, str]] = []
    for name, content in bundle["files"].items():
        if content is None:
            summary["skipped"].append(f"{name} (empty)")
            continue
        if name not in targets:
            summary["skipped"].append(f"{name} (unknown target)")
            continue
        try:
            if name.endswith(".json"):
                json.loads(content)
            else:
                yaml.safe_load(content)  # must parse as YAML
        except Exception as e:
            summary["invalid"].append(f"{name}: {e}")
            continue
        to_write.append((targets[name], content, name))
    if summary["invalid"]:
        raise ValueError("restore aborted — invalid files: " + "; ".join(summary["invalid"]))
    if dry_run:
        summary["restored"] = [n for _, _, n in to_write]
        summary["dry_run"] = True
        return summary
    for path, content, name in to_write:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            summary["restored"].append(name)
        except OSError as e:
            raise ValueError(
                f"could not write {name} to {path} ({e}). Is ./input read-write?"
            ) from e
    logger.info(f"[config_backup] restored {summary['restored']}")
    return summary
