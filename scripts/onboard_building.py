#!/usr/bin/env python3
"""
onboard_building.py — Phase 5.1: Building Onboarding CLI
=========================================================
Interactive CLI to register a new building with OntoSage.

What it does:
  1. Prompts for building metadata (id, name, namespace, timezone, TTL paths)
  2. Validates the TTL files exist and can be parsed by rdflib
  3. Introspects the ABox to detect sensor classes and counts
  4. Tests GraphDB connectivity (optional)
  5. Generates a ready-to-use building_config.yaml
  6. Optionally uploads the TTL to GraphDB via REST API

Usage:
    python scripts/onboard_building.py
    python scripts/onboard_building.py --non-interactive --id bldg2 --name "Science Tower" \
        --namespace "http://example.com/bldg2#" --prefix bldg2 \
        --timezone "Europe/London" --abox ./bldg2.ttl --output ./config/bldg2_config.yaml
"""

import argparse
import os
import sys
import json
import re
import textwrap
from pathlib import Path
from typing import Optional

# Try rdflib for validation
try:
    from rdflib import Graph, Namespace, URIRef

    RDFLIB_OK = True
except ImportError:
    RDFLIB_OK = False
    print("⚠️  rdflib not installed — TTL validation will be skipped.")

# Try yaml
try:
    import yaml

    YAML_OK = True
except ImportError:
    YAML_OK = False
    yaml = None

# ─────────────────────────────────────────────────────────────────────────────
# ANSI colours
# ─────────────────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg):
    print(f"{GREEN}✅ {msg}{RESET}")


def warn(msg):
    print(f"{YELLOW}⚠️  {msg}{RESET}")


def err(msg):
    print(f"{RED}❌ {msg}{RESET}")


def info(msg):
    print(f"{CYAN}ℹ️  {msg}{RESET}")


def banner(msg):
    print(f"\n{BOLD}{CYAN}{'─'*60}\n  {msg}\n{'─'*60}{RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
VALID_SCHEMAS = ("brick", "rec", "s223", "custom")
VALID_BACKENDS = ("mysql", "postgresql", "influxdb", "timescaledb")

IANA_SAMPLE_ZONES = {
    "UK": "Europe/London",
    "US East": "America/New_York",
    "US West": "America/Los_Angeles",
    "Central EU": "Europe/Berlin",
    "Japan": "Asia/Tokyo",
    "Singapore": "Asia/Singapore",
    "Australia": "Australia/Sydney",
}


def prompt(label, default=None, required=True, choices=None, secret=False):
    """Interactive prompt with default + validation."""
    hint = f" [{default}]" if default else ""
    if choices:
        hint += f" ({'/'.join(choices)})"
    while True:
        try:
            val = input(f"  {label}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if not val and default is not None:
            return default
        if not val and required:
            err(f"'{label}' is required.")
            continue
        if choices and val not in choices:
            err(f"Must be one of: {', '.join(choices)}")
            continue
        return val


def validate_ttl(path: str) -> dict:
    """Parse TTL and return stats."""
    if not os.path.isfile(path):
        return {"ok": False, "error": f"File not found: {path}", "triples": 0}
    if not RDFLIB_OK:
        return {"ok": True, "error": None, "triples": -1, "warning": "rdflib unavailable"}
    try:
        g = Graph()
        g.parse(path, format="turtle")
        triple_count = len(g)
        # Count classes and entities
        classes = set(
            str(o)
            for s, p, o in g.triples((None, None, None))
            if "type" in str(p).lower() and str(o).startswith("http")
        )
        return {"ok": True, "error": None, "triples": triple_count, "class_count": len(classes)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "triples": 0}


def introspect_abox(ttl_path: str) -> dict:
    """Count sensor-like instances by class."""
    if not RDFLIB_OK or not os.path.isfile(ttl_path):
        return {}
    SENSOR_KEYWORDS = ["sensor", "meter", "point", "actuator", "zone", "room", "floor", "equipment"]
    g = Graph()
    try:
        g.parse(ttl_path, format="turtle")
    except Exception:
        return {}
    class_counts = {}
    for s, p, o in g.triples((None, None, None)):
        obj_str = str(o)
        local = obj_str.split("#")[-1] if "#" in obj_str else obj_str.split("/")[-1]
        if any(kw in local.lower() for kw in SENSOR_KEYWORDS):
            class_counts[local] = class_counts.get(local, 0) + 1
    return dict(sorted(class_counts.items(), key=lambda x: -x[1])[:20])


def test_graphdb(url: str, repo: str) -> dict:
    """Quick connectivity test to GraphDB."""
    try:
        import httpx

        resp = httpx.get(f"{url}/repositories/{repo}/size", timeout=5)
        if resp.status_code == 200:
            return {"ok": True, "size": resp.text.strip()}
        return {"ok": False, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


def generate_config(data: dict) -> str:
    """Generate building_config.yaml content."""
    if YAML_OK:
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    # Fallback: manual serialization
    lines = ["# OntoSage Building Configuration", "# Auto-generated by onboard_building.py", ""]

    def _dump(d, indent=0):
        result = []
        for k, v in d.items():
            pad = "  " * indent
            if isinstance(v, dict):
                result.append(f"{pad}{k}:")
                result.extend(_dump(v, indent + 1))
            elif isinstance(v, list):
                result.append(f"{pad}{k}:")
                for item in v:
                    result.append(f"{pad}  - {item}")
            else:
                result.append(f"{pad}{k}: {repr(v)}")
        return result

    lines.extend(_dump(data))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def run_interactive():
    banner("OntoSage Building Onboarding CLI")
    info("This tool registers a new building with OntoSage and generates its config file.")
    print()

    # ── Step 1: Building identity ──────────────────────────────────────────
    print(f"{BOLD}Step 1/6: Building Identity{RESET}")
    bldg_id = prompt("Building ID (e.g. bldg1, science_tower)", default="bldg1")
    bldg_name = prompt("Building name", default="My Smart Building")
    namespace = prompt(
        "Ontology namespace URI (must end with '#')", default=f"http://example.com/{bldg_id}#"
    )
    if not namespace.endswith("#"):
        namespace += "#"
    prefix = prompt("SPARQL prefix (short, e.g. bldg)", default="bldg")
    # Suggest timezone
    info("Common timezones: " + " | ".join(f"{k}: {v}" for k, v in IANA_SAMPLE_ZONES.items()))
    timezone = prompt("IANA timezone", default="Europe/London")

    # ── Step 2: Ontology files ─────────────────────────────────────────────
    print(f"\n{BOLD}Step 2/6: Ontology Files{RESET}")
    abox_file = prompt(
        "Path to ABox TTL file (building instances)", default=f"data/{bldg_id}_abox.ttl"
    )
    tbox_file = prompt("Path to TBox TTL file (schema/vocabulary)", default="data/Brick.ttl")
    schema = prompt("Ontology schema type", default="brick", choices=list(VALID_SCHEMAS))

    # ── Step 3: Validate TTLs ────────────────────────────────────────────
    print(f"\n{BOLD}Step 3/6: Validating Ontology Files{RESET}")
    for label, path in [("ABox", abox_file), ("TBox", tbox_file)]:
        result = validate_ttl(path)
        if result["ok"]:
            ok(f"{label} parsed: {result['triples']} triples ({path})")
            if result.get("warning"):
                warn(result["warning"])
        else:
            warn(f"{label} validation failed: {result['error']} — config will still be generated.")

    # Introspect
    print("\n  Introspecting ABox sensor classes...")
    classes = introspect_abox(abox_file)
    if classes:
        ok(f"Detected {len(classes)} sensor class types:")
        for cls, cnt in list(classes.items())[:10]:
            print(f"     • {cls}: {cnt} instances")
    else:
        warn("No sensor classes detected (check TTL path or rdflib installation).")

    # ── Step 4: Storage backend ──────────────────────────────────────────
    print(f"\n{BOLD}Step 4/6: Time-Series Storage{RESET}")
    backend = prompt("DB backend", default="mysql", choices=list(VALID_BACKENDS))
    database = prompt("Database name", default=bldg_id)
    db_table = prompt("Sensor data table", default="sensor_data")
    col_uuid = prompt("UUID column name", default="uuid")
    col_val = prompt("Value column name", default="value")
    col_time = prompt("Timestamp column name", default="time")

    # ── Step 5: GraphDB (optional) ────────────────────────────────────────
    print(f"\n{BOLD}Step 5/6: GraphDB Connection (optional){RESET}")
    test_gdb = prompt("Test GraphDB connection? (y/n)", default="n", choices=["y", "n"])
    if test_gdb == "y":
        gdb_url = prompt("GraphDB URL", default="http://localhost:7200")
        gdb_repo = prompt("Repository name", default=bldg_id)
        result = test_graphdb(gdb_url, gdb_repo)
        if result.get("ok"):
            ok(f"GraphDB connected! Repository size: {result.get('size', 'N/A')} triples.")
        else:
            warn(f"GraphDB test failed: {result.get('error') or result.get('status')}")

    # ── Step 6: Generate config ─────────────────────────────────────────
    print(f"\n{BOLD}Step 6/6: Generating Config{RESET}")
    config_data = {
        "building": {
            "id": bldg_id,
            "name": bldg_name,
            "namespace": namespace,
            "prefix": prefix,
            "timezone": timezone,
            "abox_file": abox_file,
            "tbox_file": tbox_file,
        },
        "ontology": {
            "schema": schema,
            "schema_uri": (
                "https://brickschema.org/schema/Brick#"
                if schema == "brick"
                else f"http://example.com/{schema}#"
            ),
            "extra_prefixes": [],
        },
        "storage": {
            "backend": backend,
            "database": database,
            "table": db_table,
            "columns": {
                "uuid": col_uuid,
                "value": col_val,
                "timestamp": col_time,
                "sensor_name": "sensor_name",
            },
        },
    }
    config_yaml = generate_config(config_data)
    out_path = prompt("Output config file path", default=f"config/{bldg_id}_building_config.yaml")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(config_yaml, encoding="utf-8")
    ok(f"Config written to: {out_path}")

    # ── Summary ────────────────────────────────────────────────────────────
    banner("Onboarding Complete!")
    print(textwrap.dedent(f"""
    {BOLD}Next steps:{RESET}
      1. Set the env var: {CYAN}BUILDING_CONFIG_FILE={out_path}{RESET}
      2. Upload your TTL to GraphDB:
         {CYAN}curl -X PUT http://localhost:7200/repositories/{bldg_id}/statements \\
               -H "Content-Type: text/turtle" --data-binary @{abox_file}{RESET}
      3. Rebuild the sensor cache:
         {CYAN}python scripts/cache_sensor_map.py{RESET}
      4. Start OntoSage:
         {CYAN}docker compose up orchestrator{RESET}
    """))


def run_non_interactive(args):
    """Non-interactive mode for CI/CD onboarding."""
    namespace = args.namespace
    if not namespace.endswith("#"):
        namespace += "#"

    config_data = {
        "building": {
            "id": args.id,
            "name": args.name,
            "namespace": namespace,
            "prefix": args.prefix,
            "timezone": args.timezone,
            "abox_file": args.abox,
            "tbox_file": args.tbox or "data/Brick.ttl",
        },
        "ontology": {
            "schema": args.schema,
            "schema_uri": "https://brickschema.org/schema/Brick#",
            "extra_prefixes": [],
        },
        "storage": {
            "backend": args.backend,
            "database": args.id,
            "table": "sensor_data",
            "columns": {
                "uuid": "uuid",
                "value": "value",
                "timestamp": "time",
                "sensor_name": "sensor_name",
            },
        },
    }

    # Validate ABox
    if args.abox:
        result = validate_ttl(args.abox)
        if result["ok"]:
            ok(f"ABox valid: {result['triples']} triples")
        else:
            warn(f"ABox validation: {result['error']}")

    config_yaml = generate_config(config_data)
    out = args.output or f"config/{args.id}_building_config.yaml"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(config_yaml, encoding="utf-8")
    ok(f"Config written: {out}")
    # Also print JSON summary for CI consumption
    print(json.dumps({"status": "ok", "config": out, "building_id": args.id}))


def run_scaffold(building_id: str, input_root: Path) -> None:
    """Copy input/_templates/ to input/<building_id>/ with BUILDING_ID substituted."""
    templates_dir = input_root / "_templates"
    target_dir = input_root / building_id

    if not templates_dir.is_dir():
        err(f"Templates directory not found: {templates_dir}")
        err("Create input/_templates/ first (see docs/ADDING_A_DATA_SOURCE.md).")
        sys.exit(1)

    if target_dir.exists():
        warn(f"Directory already exists: {target_dir}")
        warn("Scaffold will only copy files that don't already exist (no overwrite).")
    else:
        target_dir.mkdir(parents=True)
        ok(f"Created {target_dir}")

    copied, skipped = 0, 0
    for src in templates_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(templates_dir)
        dest = target_dir / rel
        if dest.exists():
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8", errors="replace")
        # Substitute all template placeholders
        content = content.replace("{BUILDING_ID}", building_id)
        content = content.replace("{{BUILDING_ID}}", building_id)
        dest.write_text(content, encoding="utf-8")
        ok(f"  scaffolded: {rel}")
        copied += 1

    print()
    info(f"Scaffold complete: {copied} files copied, {skipped} skipped (already exist).")
    info(f"Edit {target_dir}/building.yaml to set building_name and ontology_namespace.")
    info("Then run:  python scripts/swap_building.py --to " + building_id + " --dry-run")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OntoSage Building Onboarding CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run in non-interactive mode (requires --id, --name, etc.)",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help=(
            "Copy input/_templates/ to input/<--building-id>/ with BUILDING_ID substituted. "
            "Use this to bootstrap a new building's directory before onboarding."
        ),
    )
    parser.add_argument(
        "--building-id",
        dest="building_id",
        help="Building ID for --scaffold mode.",
    )
    parser.add_argument(
        "--input-root",
        default="input",
        help="Path to the input/ root (default: input).",
    )
    parser.add_argument("--id", help="Building ID (non-interactive mode)")
    parser.add_argument("--name", help="Building name")
    parser.add_argument("--namespace", help="Ontology namespace URI")
    parser.add_argument("--prefix", default="bldg", help="SPARQL prefix")
    parser.add_argument("--timezone", default="Europe/London", help="IANA timezone")
    parser.add_argument("--abox", help="Path to ABox TTL")
    parser.add_argument("--tbox", help="Path to TBox TTL")
    parser.add_argument("--schema", default="brick", choices=list(VALID_SCHEMAS))
    parser.add_argument("--backend", default="mysql", choices=list(VALID_BACKENDS))
    parser.add_argument("--output", help="Output config file path")

    args = parser.parse_args()

    if args.scaffold:
        bid = args.building_id or args.id
        if not bid:
            parser.error("--building-id (or --id) is required with --scaffold")
        run_scaffold(bid, Path(args.input_root).resolve())
    elif args.non_interactive:
        for req in ("id", "name", "namespace"):
            if not getattr(args, req):
                parser.error(f"--{req} is required in non-interactive mode")
        run_non_interactive(args)
    else:
        run_interactive()
