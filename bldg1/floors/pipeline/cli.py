"""Command line entry point for the Abacws floor-plan -> knowledge graph pipeline."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from .boundary import BoundaryTracer, write_boundaries
from .extract import FloorPlanExtractor
from .merge import building_summary, check_alignment, find_vertical_links
from .readers import dwg_to_json, read_dwg_json, read_dxf
from .to_rdf import DEFAULT_BASE, GraphBuilder, attach_sensors, load_model


def _load_config(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _read_any(path: str | Path, scale: float, cache_dir: Path | None = None):
    """Read a .dwg (via LibreDWG-WASM), a .dxf (via ezdxf), or a cached .json."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dwg":
        cache = (cache_dir or path.parent) / f"{path.stem}.dwg.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            dwg_to_json(path, cache)
        else:
            print(f"  (using cached {cache.name})")
        return read_dwg_json(cache, scale)
    if suffix == ".json":
        return read_dwg_json(path, scale)
    return read_dxf(path, scale)


# --------------------------------------------------------------------------

def cmd_layers(args: argparse.Namespace) -> int:
    """Print the layer table with entity counts - run this FIRST on a new file."""
    entities, meta = _read_any(args.file, 1.0)
    counts: Counter[str] = Counter()
    types: dict[str, Counter] = {}
    for entity in entities:
        counts[entity.layer] += 1
        types.setdefault(entity.layer, Counter())[entity.type] += 1

    print(f"{'LAYER':<45} {'N':>7}  ENTITY TYPES")
    print("-" * 100)
    for layer, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        breakdown = ", ".join(f"{t}:{n}" for t, n in types[layer].most_common(5))
        print(f"{layer:<45} {count:>7}  {breakdown}")

    header = meta.get("header", {})
    print(f"\n{len(counts)} layers with entities, {len(entities)} entities kept.")
    print(f"All entity types: {dict(meta.get('entity_type_counts', {}))}")
    print(f"ACADVER: {header.get('ACADVER')}   INSUNITS: {header.get('INSUNITS')}")
    print("  (INSUNITS 4 = millimetres, 6 = metres, 1 = inches, 2 = feet)")
    if meta.get("unknown_entity_count"):
        print(f"  ! {meta['unknown_entity_count']} entities of unrecognised type were skipped")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    scale = float(config.get("units_to_metres", 0.001))
    entities, meta = _read_any(args.file, scale)
    model = FloorPlanExtractor(config).extract(entities, meta)
    Path(args.out).write_text(model.to_json(), encoding="utf-8")

    print(f"Wrote {args.out}")
    for key, value in model.stats.items():
        print(f"  {key:<28} {value}")

    unnamed = [s.id for s in model.spaces if not s.code and not s.name]
    if unnamed:
        print(f"\n  ! {len(unnamed)} space(s) got no label - widen labels.layers "
              f"in the config or raise geometry.tolerance_m")
    return 0


def cmd_building(args: argparse.Namespace) -> int:
    """Run every floor and merge into one building graph."""
    config = _load_config(args.config)
    floors = config.get("floors")
    if not floors:
        print("ERROR: config has no `floors:` list. See config.building.yaml.")
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cache_dir = outdir / "cache"

    models: list[dict] = []
    for floor in floors:
        source = Path(floor["file"])
        if not source.exists():
            print(f"  ! SKIPPING {source} - file not found")
            continue

        floor_config = copy.deepcopy(config)
        floor_config["storey"] = floor["storey"]
        floor_config.update(floor.get("overrides", {}) or {})
        scale = float(floor_config.get("units_to_metres", 0.001))

        print(f"\n=== {floor['storey'].get('name', source.name)} ({source.name}) ===")
        try:
            entities, meta = _read_any(source, scale, cache_dir)
        except Exception as error:
            print(f"  ! FAILED to read {source.name}: {error}")
            continue

        model = FloorPlanExtractor(floor_config).extract(entities, meta)
        model_dict = model.to_dict()

        # Namespace space/element ids per storey so floors cannot collide.
        prefix = floor["storey"]["id"]
        model_dict = _prefix_ids(model_dict, prefix)

        target = outdir / f"{prefix}.json"
        target.write_text(json.dumps(model_dict, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        models.append(model_dict)
        for key in ("spaces", "spaces_with_code", "elements", "dimensions",
                    "dimensions_with_measurement", "adjacency_edges",
                    "connectivity_edges", "total_area_m2"):
            print(f"  {key:<28} {model.stats.get(key)}")

    if not models:
        print("\nNo floors were processed.")
        return 1

    for warning in check_alignment(models, float(
            config.get("merge", {}).get("alignment_tolerance_m", 25.0))):
        print(f"\n  ! {warning}")

    merge_cfg = config.get("merge", {})
    links = find_vertical_links(
        models,
        core_patterns=merge_cfg.get("core_patterns"),
        min_overlap_ratio=float(merge_cfg.get("min_overlap_ratio", 0.5)),
        adjacent_only=bool(merge_cfg.get("adjacent_only", True)),
    )

    builder = GraphBuilder(args.base)
    builder.build_many(models)
    builder.add_vertical_links(links)

    if args.sensors:
        print(f"\n  bound {attach_sensors(builder.graph, args.sensors, args.base)} sensor(s)")

    out_ttl = outdir / args.out
    builder.graph.serialize(destination=str(out_ttl), format="turtle")

    summary = building_summary(models)
    summary["vertical_links"] = len(links)
    summary["triples"] = len(builder.graph)
    print(f"\n=== BUILDING GRAPH: {out_ttl} ===")
    for key, value in summary.items():
        print(f"  {key:<28} {value}")
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


def _prefix_ids(model: dict, prefix: str) -> dict:
    """Make every local id storey-unique, so merged floors never collide."""
    def rename(value: str) -> str:
        return f"{prefix}_{value}" if value else value

    for space in model.get("spaces", []):
        space["id"] = rename(space["id"])
    for element in model.get("elements", []):
        element["id"] = rename(element["id"])
        if element.get("in_space"):
            element["in_space"] = rename(element["in_space"])
    for dimension in model.get("dimensions", []):
        dimension["id"] = rename(dimension["id"])
        if dimension.get("in_space"):
            dimension["in_space"] = rename(dimension["in_space"])
    for edge in model.get("adjacency", []):
        edge["a"], edge["b"] = rename(edge["a"]), rename(edge["b"])
    for edge in model.get("connectivity", []):
        edge["door"] = rename(edge.get("door", ""))
        edge["spaces"] = [rename(s) for s in edge.get("spaces", [])]
    return model



def cmd_rooms(args: argparse.Namespace) -> int:
    """
    Trace a closed room boundary per room number - the BOUNDARY/BPOLY job.

    Input must be DXF. DWG is deliberately not accepted here: this command
    rewrites the drawing, and only ezdxf's own DXF round-trip preserves the
    entities it does not understand (AEC proxies especially). Converting DWG
    through a third-party reader first would quietly drop them.
    """
    import ezdxf

    source = Path(args.file)
    if source.suffix.lower() != ".dxf":
        print(f"ERROR: {source.name} is not a DXF.")
        print("  This command rewrites the drawing, so it needs a DXF that ezdxf")
        print("  can round-trip faithfully. Export DXF R2018 ASCII from AutoCAD")
        print("  first (SAVEAS -> DXF), then run this against that file.")
        return 2

    config = _load_config(args.config) if Path(args.config).exists() else {}
    rooms_cfg = config.get("rooms", {})

    doc = ezdxf.readfile(str(source))
    before = _entity_census(doc)

    tracer = BoundaryTracer(
        wall_layers=args.wall_layers or rooms_cfg.get("wall_layers", ["A-WALL", "I-WALL"]),
        door_layers=args.door_layers or rooms_cfg.get("door_layers", ["A-DOOR"]),
        room_text_layers=rooms_cfg.get("room_text_layers", ["A-AREA-IDEN"]),
        room_pattern=args.pattern or rooms_cfg.get("room_pattern", r"^\d\.\d{2}$"),
        units_to_metres=float(config.get("units_to_metres", 0.001)),
        min_area_m2=float(rooms_cfg.get("min_area_m2", 1.0)),
        max_area_m2=float(rooms_cfg.get("max_area_m2", 2000.0)),
        min_inradius_m=float(rooms_cfg.get("min_inradius_m", 0.3)),
        include_door_curves=bool(rooms_cfg.get("include_door_curves", False)),
    )

    result = tracer.trace(doc.modelspace())
    print(f"\n=== {source.name} ===")
    print(f"  wall segments   {result.stats.get('wall_segments')}")
    print(f"  room numbers    {result.stats.get('room_numbers_found')}")
    print(f"  faces found     {result.stats.get('faces_found')}")
    print(result.report())

    if args.dry_run:
        print("\n  (dry run - nothing written)")
        return 0

    written = write_boundaries(doc, result, layer_name=args.layer)
    doc.dxfversion = "AC1032"          # R2018
    target = Path(args.out) if args.out else source.with_name(source.name)
    doc.saveas(str(target))

    after = _entity_census(doc)
    print(f"\n  wrote {written} polyline(s) to layer {args.layer}")
    print(f"  saved {target}  (DXF R2018 ASCII)")

    # Prove nothing else moved: every pre-existing layer must have exactly the
    # same entity count afterwards.
    drift = {
        layer: (before.get(layer, 0), after.get(layer, 0))
        for layer in before
        if before.get(layer, 0) != after.get(layer, 0)
    }
    if drift:
        print("  ! WARNING - pre-existing layers changed entity count:")
        for layer, (was, now) in drift.items():
            print(f"      {layer}: {was} -> {now}")
    else:
        print(f"  verified: all {len(before)} pre-existing layers unchanged")
    return 0


def _entity_census(doc) -> dict[str, int]:
    census: dict[str, int] = {}
    for entity in doc.modelspace():
        layer = entity.dxf.get("layer", "")
        census[layer] = census.get(layer, 0) + 1
    return census


def cmd_rdf(args: argparse.Namespace) -> int:
    model = load_model(args.model)
    builder = GraphBuilder(args.base)
    graph = builder.build(model)
    if args.sensors:
        print(f"  bound {attach_sensors(graph, args.sensors, args.base)} sensor(s)")
    graph.serialize(destination=args.out, format=args.format)
    print(f"Wrote {args.out}  ({len(graph)} triples, {args.format})")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from rdflib import Graph

    graph = Graph()
    graph.parse(args.ttl, format="turtle")
    results = graph.query(Path(args.sparql).read_text(encoding="utf-8"))

    if results.type == "ASK":
        print(bool(results.askAnswer))
        return 0

    print(" | ".join(str(v) for v in results.vars or []))
    print("-" * 80)
    count = 0
    for row in results:
        print(" | ".join(
            (str(row[v]).rsplit("#", 1)[-1] if row[v] is not None else "")
            for v in results.vars))
        count += 1
    print(f"\n{count} row(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="abacws-kg",
        description="Turn architectural DWG/DXF floor plans into a queryable "
                    "Brick/BOT knowledge graph.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("layers", help="inspect the layer table of a DWG/DXF")
    p.add_argument("file")
    p.set_defaults(func=cmd_layers)

    p = sub.add_parser("extract", help="one DWG/DXF -> intermediate JSON model")
    p.add_argument("file")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-o", "--out", default="floor_model.json")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("building", help="all floors -> one merged building graph")
    p.add_argument("-c", "--config", default="config.building.yaml")
    p.add_argument("--outdir", default="out")
    p.add_argument("-o", "--out", default="abacws_building.ttl")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--sensors")
    p.set_defaults(func=cmd_building)

    p = sub.add_parser("rooms", help="trace a closed boundary per room number (BOUNDARY/BPOLY)")
    p.add_argument("file", help="input DXF (not DWG - see command help)")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-o", "--out", help="output DXF (default: overwrite input)")
    p.add_argument("--layer", default="A-AREA-ROOM")
    p.add_argument("--pattern", help=r"room number regex, default ^\d\.\d{2}$")
    p.add_argument("--wall-layers", nargs="*", dest="wall_layers")
    p.add_argument("--door-layers", nargs="*", dest="door_layers")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be traced without writing")
    p.set_defaults(func=cmd_rooms)

    p = sub.add_parser("rdf", help="intermediate JSON -> Turtle")
    p.add_argument("model")
    p.add_argument("-o", "--out", default="floor.ttl")
    p.add_argument("-f", "--format", default="turtle",
                   choices=["turtle", "nt", "xml", "json-ld"])
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--sensors")
    p.set_defaults(func=cmd_rdf)

    p = sub.add_parser("query", help="run a .rq file against a .ttl file")
    p.add_argument("ttl")
    p.add_argument("sparql")
    p.set_defaults(func=cmd_query)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
