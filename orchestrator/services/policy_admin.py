# -*- coding: utf-8 -*-
"""V5-T43 — author access policies from the admin GUI into versioned TTL.

Policies are triples (V5-T37), so the governance surface is the same TTL-first
path capabilities use: a guided form is rendered to Turtle, validated, written to
``input/<id>_policies.ttl``, and its named graph re-synced. The file stays the
source of truth, so a GUI edit and a hand edit converge and the change is visible
in version control rather than living in a database nobody diffs.

TWO THINGS THIS EDITOR REFUSES, DELIBERATELY
--------------------------------------------
The 0-leak certification rests on these policies, and a GUI is exactly where a
guarantee gets weakened by accident.

1. *Silent* weakening. Lowering a k-anonymity floor, widening a resolution tier
   or removing a rate limit is a legitimate operation — but never an incidental
   one. Such an edit is rejected unless the caller sets ``acknowledge_weakening``,
   and the response names precisely what got weaker.

2. Turning off the individual-privacy rules at all. "The system explains the
   building; it never tracks individuals" is a product property, not a setting:
   an inference class may only be authored as ``deny``, and an existing
   inference-class policy cannot be deleted here. Anyone who genuinely means to
   change that edits the TTL directly, where it is a reviewable diff.

Building-agnostic: the building id and namespace are parameters throughout.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_ONTO_NS = "http://ontosage.org/capabilities#"
_LOCALNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")
_TIERS_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*(?:,\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*)*$"
)
_INFERENCE_RE = re.compile(r"^[a-z][a-z0-9_]*:(allow|restrict|deny)$")

ANY_ROLE = "*"

#: Guided-form schema the admin tab renders. Kept here so the GUI gains a field
#: by editing this list, not by editing React.
POLICY_FORM_SCHEMA: List[Dict[str, str]] = [
    {
        "name": "id",
        "label": "Policy id",
        "type": "text",
        "required": "true",
        "help": "Local name, e.g. policy_occupant_full",
    },
    {
        "name": "role",
        "label": "Applies to role",
        "type": "select",
        "required": "true",
        "help": "An RBAC role, or * for every role",
    },
    {
        "name": "scope_spaces",
        "label": "Scope",
        "type": "text",
        "help": "'any', or a scope expression the building understands",
    },
    {
        "name": "min_sensors",
        "label": "Min sensors to aggregate (k)",
        "type": "number",
        "help": "k-anonymity floor: refuse an answer drawn from fewer sensors than this",
    },
    {
        "name": "min_spaces",
        "label": "Min spaces to aggregate (k)",
        "type": "number",
        "help": "k-anonymity floor across spaces",
    },
    {
        "name": "tiers",
        "label": "Resolution tiers",
        "type": "text",
        "help": "recency_minutes:max_resolution_seconds pairs, e.g. '0:900,60:60'",
    },
    {"name": "rate_max", "label": "Max queries", "type": "number", "help": "0 = unlimited"},
    {"name": "rate_window_min", "label": "Per minutes", "type": "number", "help": "0 = unlimited"},
    {
        "name": "comment",
        "label": "Why this policy exists",
        "type": "textarea",
        "help": "Shown to operators and carried into the graph",
    },
]


def known_roles() -> List[str]:
    """RBAC roles plus the wildcard — resolved live, never hardcoded here."""
    from orchestrator.middleware.rbac import ROLE_PERMISSIONS

    return [ANY_ROLE] + sorted(ROLE_PERMISSIONS)


def building_namespace(building_id: str) -> str:
    try:
        from orchestrator.services.building_context import resolve_building_context

        return resolve_building_context(building_id).namespace
    except Exception:
        return settings.BUILDING_NAMESPACE


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def _as_int(value: Any, default: int = 0) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ── validation + rendering ───────────────────────────────────────────────────


def validate_policy_fields(fields: Dict[str, Any]) -> Optional[str]:
    """Return an error string, or None when the guided form is coherent."""
    local = str(fields.get("id") or "").strip()
    if not _LOCALNAME_RE.match(local):
        return "invalid policy id (letters, digits, _ . - ; must start with a letter)"

    role = str(fields.get("role") or "").strip()
    if role not in known_roles():
        return f"unknown role '{role}' — expected one of {', '.join(known_roles())}"

    inference = str(fields.get("inference_class") or "").strip()
    if inference:
        if not _INFERENCE_RE.match(inference):
            return "inference class must look like 'individual_presence:deny'"
        if not inference.endswith(":deny"):
            return (
                "an inference class may only be authored as ':deny' here — the system "
                "explains the building and never tracks individuals. Edit the TTL directly "
                "if you genuinely intend to change that."
            )
        return None  # inference policies carry no floors/tiers

    for key in ("min_sensors", "min_spaces"):
        n = _as_int(fields.get(key), 1)
        if n is None:
            return f"{key} must be a whole number"
        if n < 1:
            return f"{key} must be at least 1 — a floor of 0 disables the k-anonymity check"

    tiers = str(fields.get("tiers") or "").strip()
    if tiers and not _TIERS_RE.match(tiers):
        return "resolution tiers must be 'minutes:seconds' pairs, e.g. '0:900,60:60'"

    for key in ("rate_max", "rate_window_min"):
        n = _as_int(fields.get(key), 0)
        if n is None or n < 0:
            return f"{key} must be a whole number of 0 or more (0 = unlimited)"
    return None


def build_policy_ttl(building_id: str, fields: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Guided fields -> one AccessPolicy instance in Turtle."""
    err = validate_policy_fields(fields)
    if err:
        return {"ok": False, "error": err, "ttl": "", "subject": ""}

    ns = building_namespace(building_id)
    local = str(fields["id"]).strip()
    subject = f"{ns}{local}"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    provenance = f"authored in the admin policy editor by {actor or 'unknown'} on {stamp}"
    comment = str(fields.get("comment") or "").strip()
    full_comment = f"{comment} [{provenance}]" if comment else f"[{provenance}]"

    lines = [
        f"@prefix ontosage: <{_ONTO_NS}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
        f"<{subject}> a ontosage:AccessPolicy ;",
        f'    ontosage:appliesToRole "{_esc(str(fields["role"]))}" ;',
    ]
    inference = str(fields.get("inference_class") or "").strip()
    if inference:
        lines.append(f'    ontosage:inferenceClass "{_esc(inference)}" ;')
    else:
        lines += [
            f'    ontosage:scopeSpaces "{_esc(str(fields.get("scope_spaces") or "any"))}" ;',
            f"    ontosage:minAggregationSensors {_as_int(fields.get('min_sensors'), 1)} ;",
            f"    ontosage:minAggregationSpaces {_as_int(fields.get('min_spaces'), 1)} ;",
            f'    ontosage:resolutionTier "{_esc(str(fields.get("tiers") or "0:1"))}" ;',
            f'    ontosage:rateLimit "{_as_int(fields.get("rate_max"), 0)}:'
            f'{_as_int(fields.get("rate_window_min"), 0)}" ;',
        ]
    lines.append(f'    rdfs:comment "{_esc(full_comment)}"@en .')
    return {"ok": True, "error": None, "ttl": "\n".join(lines) + "\n", "subject": subject}


# ── weakening detection ──────────────────────────────────────────────────────


def diff_weakening(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> List[str]:
    """Name every way ``new`` is more permissive than ``old``. Empty = no weakening."""
    if not old:
        return []
    weaker: List[str] = []
    for key, label in (
        ("min_sensors", "sensor k-anonymity floor"),
        ("min_spaces", "space k-anonymity floor"),
    ):
        o, n = _as_int(old.get(key), 1), _as_int(new.get(key), 1)
        if o is not None and n is not None and n < o:
            weaker.append(f"{label} lowered {o} -> {n}")

    o_rate, n_rate = _as_int(old.get("rate_max"), 0), _as_int(new.get("rate_max"), 0)
    if o_rate and (not n_rate or n_rate > o_rate):
        weaker.append(f"query rate limit relaxed {o_rate} -> {n_rate or 'unlimited'}")

    # A tier maps recency -> coarsest resolution allowed. A SMALLER max_resolution
    # means finer data is released, i.e. weaker.
    o_tiers, n_tiers = _tier_map(old.get("tiers")), _tier_map(new.get("tiers"))
    for recency, o_res in o_tiers.items():
        n_res = n_tiers.get(recency)
        if n_res is not None and n_res < o_res:
            weaker.append(
                f"resolution at {recency:g} min sharpened {o_res:g}s -> {n_res:g}s "
                "(finer data released)"
            )
    return weaker


def _tier_map(raw: Any) -> Dict[float, float]:
    out: Dict[float, float] = {}
    for part in str(raw or "").split(","):
        if ":" not in part:
            continue
        a, b = part.split(":", 1)
        try:
            out[float(a)] = float(b)
        except ValueError:
            continue
    return out


# ── graph-facing operations ──────────────────────────────────────────────────


async def list_policies(building_id: str, client: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Every AccessPolicy in the building's namespace, GUI- or file-authored."""
    from orchestrator.services.privacy.policy_engine import PolicyEngine

    engine = PolicyEngine(building_id, building_namespace(building_id))
    try:
        await engine.load()
    except Exception as exc:
        logger.warning(f"[policy_admin] cannot load policies: {exc}")
        return []
    rows = []
    for p in engine._policies or []:
        rows.append(
            {
                "id": p.iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1],
                "iri": p.iri,
                "role": p.role,
                "inference_class": p.inference_class or "",
                "scope_spaces": p.scope_spaces,
                "min_sensors": p.min_sensors,
                "min_spaces": p.min_spaces,
                "tiers": ",".join(f"{a:g}:{b:g}" for a, b in p.tiers),
                "rate_max": p.rate_max,
                "rate_window_min": p.rate_window_min,
                "comment": p.comment,
                "editable": not p.inference_class,
            }
        )
    return sorted(rows, key=lambda r: (r["role"], r["id"]))


async def create_policy(
    building_id: str,
    fields: Dict[str, Any],
    actor: str = "",
    acknowledge_weakening: bool = False,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Validate, weakening-check, write to <id>_policies.ttl, re-sync, invalidate caches."""
    built = build_policy_ttl(building_id, fields, actor=actor)
    if not built["ok"]:
        return built

    existing = {p["id"]: p for p in await list_policies(building_id, client=client)}
    old = existing.get(str(fields.get("id") or "").strip())
    if old and old.get("inference_class"):
        return {
            "ok": False,
            "error": (
                "this is an individual-privacy rule and cannot be edited here — "
                "edit the TTL directly if you genuinely intend to change it"
            ),
            "ttl": "",
            "subject": built["subject"],
        }

    weakened = diff_weakening(old, fields)
    if weakened and not acknowledge_weakening:
        return {
            "ok": False,
            "error": (
                "this change weakens a privacy guarantee: "
                + "; ".join(weakened)
                + ". Re-submit with acknowledge_weakening set if that is intended."
            ),
            "weakened": weakened,
            "ttl": built["ttl"],
            "subject": built["subject"],
        }

    from orchestrator.services.input_ttl_store import upsert_policy

    res = await upsert_policy(building_id, built["subject"], built["ttl"], client=client)
    if res.get("ok"):
        await invalidate_policy_caches(building_id)
        if weakened:
            # A weakening that WAS acknowledged still belongs in the record.
            logger.warning(
                f"[policy_admin] {actor or 'unknown'} weakened {built['subject']}: "
                + "; ".join(weakened)
            )
        else:
            logger.info(f"[policy_admin] {actor or 'unknown'} saved {built['subject']}")
    return {
        "ok": bool(res.get("ok")),
        "subject": built["subject"],
        "ttl": built["ttl"],
        "file": res.get("file"),
        "weakened": weakened,
        "error": res.get("error"),
    }


async def delete_policy(
    building_id: str, local: str, actor: str = "", client: Optional[Any] = None
) -> Dict[str, Any]:
    """Remove a policy. Individual-privacy rules are not deletable through the GUI."""
    if not _LOCALNAME_RE.match(local or ""):
        return {"ok": False, "error": "invalid policy id"}

    existing = {p["id"]: p for p in await list_policies(building_id, client=client)}
    target = existing.get(local)
    if target and target.get("inference_class"):
        return {
            "ok": False,
            "error": (
                "this is an individual-privacy rule ("
                + target["inference_class"]
                + ") and cannot be deleted here — deleting it would let the system answer "
                "questions about individuals. Edit the TTL directly if that is truly intended."
            ),
        }

    from orchestrator.services.input_ttl_store import remove_policy

    res = await remove_policy(
        building_id, f"{building_namespace(building_id)}{local}", client=client
    )
    if res.get("ok"):
        await invalidate_policy_caches(building_id)
        logger.warning(f"[policy_admin] {actor or 'unknown'} deleted policy {local}")
    return res


async def invalidate_policy_caches(building_id: str) -> int:
    """A policy edit must bind on the NEXT question, not the next restart.

    Two caches would otherwise keep serving pre-edit behaviour: the PDP holds its
    policy list in process, and the response cache holds answers computed under
    the old rules — which is how a tightened floor appears to have "not worked".
    Returns the number of policies reloaded (0 when the PDP is unavailable).
    """
    reloaded = 0
    try:
        from orchestrator.services.privacy.enforcement import reload_policies

        reloaded = await reload_policies()
    except Exception as exc:  # pragma: no cover - live wiring
        logger.warning(f"[policy_admin] PDP not reloaded: {exc}")
    try:
        from orchestrator import main as _main

        cache = getattr(_main, "response_cache", None)
        if cache is not None:
            await cache.invalidate(building_id=building_id, flush_all=True)
    except Exception as exc:  # pragma: no cover - live wiring
        logger.warning(f"[policy_admin] response cache not flushed: {exc}")
    return reloaded
