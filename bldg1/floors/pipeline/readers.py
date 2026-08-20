"""
Front-ends: DXF (ezdxf) and DWG (LibreDWG-WASM JSON) -> list[NormEntity].

Both readers apply the unit scale, so everything downstream is in metres.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

from .entities import NormEntity


# ==========================================================================
# DWG - via tools/dwg_read.mjs (LibreDWG compiled to WebAssembly)
# ==========================================================================

def dwg_to_json(dwg_path: str | Path, json_path: str | Path,
                tools_dir: str | Path | None = None) -> Path:
    """
    Run the Node reader to dump a DWG into JSON.

    Requires `npm install @mlightcad/libredwg-web` in the tools directory.
    No ODA File Converter, no DXF intermediate - LibreDWG's WASM build reads
    the DWG directly.
    """
    tools = Path(tools_dir) if tools_dir else Path(__file__).resolve().parent.parent / "tools"
    script = tools / "dwg_read.mjs"
    if not script.exists():
        raise FileNotFoundError(f"DWG reader not found at {script}")

    result = subprocess.run(
        ["node", str(script), str(dwg_path), str(json_path)],
        cwd=str(tools), capture_output=True, text=True,
    )
    sys.stderr.write(result.stderr)
    if result.returncode != 0 or not Path(json_path).exists():
        raise RuntimeError(
            f"DWG read failed for {dwg_path}.\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )
    return Path(json_path)


def _pt(raw: Any, scale: float) -> tuple[float, float] | None:
    if not raw:
        return None
    try:
        return (float(raw[0]) * scale, float(raw[1]) * scale)
    except (TypeError, ValueError, IndexError):
        return None


def read_dwg_json(json_path: str | Path, scale: float) -> tuple[list[NormEntity], dict]:
    """Load the Node dump and normalise it."""
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    out: list[NormEntity] = []

    for raw in payload.get("entities", []):
        etype = raw.get("type", "")
        entity = NormEntity(
            type=etype,
            layer=raw.get("layer", "") or "",
            handle=str(raw.get("handle", "")),
            paper_space=bool(raw.get("paperSpace")),
            xdata=raw.get("xdata"),
        )

        if etype == "LWPOLYLINE":
            entity.closed = bool(raw.get("closed"))
            entity.points = [
                (float(v[0]) * scale, float(v[1]) * scale)
                for v in raw.get("vertices", [])
                if v is not None and len(v) >= 2
            ]
        elif etype == "POLYLINE":
            entity.closed = bool(raw.get("closed"))
            entity.points = [
                p for p in (_pt(v, scale) for v in raw.get("vertices", [])) if p
            ]
        elif etype == "INSERT":
            entity.block_name = raw.get("name")
            entity.point = _pt(raw.get("insertionPoint"), scale)
            entity.attribs = {
                str(a.get("tag", "")).strip(): str(a.get("text", "")).strip()
                for a in raw.get("attribs", [])
                if a.get("tag")
            }
        elif etype in ("TEXT", "MTEXT"):
            entity.text = _clean_mtext(str(raw.get("text", "") or ""))
            entity.point = _pt(raw.get("insertionPoint"), scale) or \
                _pt(raw.get("secondPoint"), scale)
        elif etype == "DIMENSION":
            measurement = raw.get("measurement")
            entity.measurement = (
                float(measurement) * scale if isinstance(measurement, (int, float)) else None
            )
            entity.text_override = raw.get("text") or None
            entity.dimension_type = raw.get("dimensionType")
            entity.point = _pt(raw.get("textPoint"), scale) or \
                _pt(raw.get("definitionPoint"), scale)
            entity.dimension_points = [
                p for p in (
                    _pt(raw.get(k), scale)
                    for k in ("definitionPoint", "subDefinitionPoint1", "subDefinitionPoint2")
                ) if p
            ]
        elif etype in ("CIRCLE", "ARC"):
            entity.point = _pt(raw.get("center"), scale)
        elif etype == "LINE":
            start, end = _pt(raw.get("start"), scale), _pt(raw.get("end"), scale)
            entity.points = [p for p in (start, end) if p]

        out.append(entity)

    meta = {
        "source": payload.get("source"),
        "header": payload.get("header", {}),
        "layers": payload.get("layers", []),
        "entity_type_counts": payload.get("entityTypeCounts", {}),
        "unknown_entity_count": payload.get("unknownEntityCount", 0),
        "block_records": payload.get("blockRecords", []),
    }
    return out, meta


def _clean_mtext(text: str) -> str:
    """Strip the common MTEXT formatting codes so labels compare as plain text."""
    import re
    if not text:
        return ""
    text = re.sub(r"\\P", " ", text)                 # paragraph break
    text = re.sub(r"\\[A-Za-z]+[^;\\]*;", "", text)  # \f...; \H...; \C...;
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\\~", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ==========================================================================
# DXF - via ezdxf
# ==========================================================================

def read_dxf(dxf_path: str | Path, scale: float,
             explode_blocks: bool = True) -> tuple[list[NormEntity], dict]:
    import ezdxf

    doc = ezdxf.readfile(str(dxf_path))
    out: list[NormEntity] = []
    counts: dict[str, int] = {}

    for raw in _iter_dxf(doc, explode_blocks):
        etype = raw.dxftype()
        counts[etype] = counts.get(etype, 0) + 1
        entity = NormEntity(
            type=etype,
            layer=raw.dxf.get("layer", "") or "",
            handle=str(raw.dxf.get("handle", "")),
            paper_space=bool(raw.dxf.get("paperspace", 0)),
        )

        try:
            if etype == "LWPOLYLINE":
                entity.closed = bool(raw.closed)
                entity.points = [(x * scale, y * scale) for x, y, *_ in raw.get_points("xyb")]
            elif etype == "POLYLINE":
                entity.closed = bool(raw.is_closed)
                entity.points = [
                    (v.dxf.location.x * scale, v.dxf.location.y * scale) for v in raw.vertices
                ]
            elif etype == "INSERT":
                entity.block_name = raw.dxf.get("name")
                entity.point = _dxf_point(raw, scale)
                entity.attribs = {
                    str(a.dxf.tag).strip(): str(a.dxf.text).strip()
                    for a in raw.attribs if str(a.dxf.tag).strip()
                }
            elif etype in ("TEXT", "MTEXT"):
                entity.text = (
                    raw.plain_text(split=False).strip() if etype == "MTEXT"
                    else str(raw.dxf.text).strip()
                )
                entity.point = _dxf_point(raw, scale)
            elif etype == "DIMENSION":
                measurement = raw.get_measurement()
                if isinstance(measurement, (int, float)) and math.isfinite(measurement):
                    entity.measurement = float(measurement) * scale
                text = str(raw.dxf.get("text", "") or "")
                entity.text_override = text if text not in ("", "<>") else None
                entity.dimension_type = int(raw.dxf.get("dimtype", 0)) & 0x0F
                entity.point = _dxf_point(raw, scale)
            elif etype in ("CIRCLE", "ARC"):
                centre = raw.dxf.center
                entity.point = (centre.x * scale, centre.y * scale)
            elif etype == "LINE":
                entity.points = [
                    (raw.dxf.start.x * scale, raw.dxf.start.y * scale),
                    (raw.dxf.end.x * scale, raw.dxf.end.y * scale),
                ]
        except Exception:
            # A malformed entity should never abort a 30 MB drawing.
            pass

        out.append(entity)

    meta = {
        "source": str(dxf_path),
        "header": {
            "INSUNITS": doc.header.get("$INSUNITS"),
            "ACADVER": doc.dxfversion,
        },
        "layers": [{"name": layer.dxf.name} for layer in doc.layers],
        "entity_type_counts": counts,
        "unknown_entity_count": 0,
        "block_records": [block.name for block in doc.blocks],
    }
    return out, meta


def _iter_dxf(doc, explode: bool) -> Iterator:
    msp = doc.modelspace()
    for entity in msp:
        yield entity
        if explode and entity.dxftype() == "INSERT":
            try:
                yield from entity.virtual_entities()
            except Exception:
                continue


def _dxf_point(entity, scale: float) -> tuple[float, float] | None:
    for attr in ("insert", "align_point", "location", "text_midpoint", "defpoint"):
        if entity.dxf.hasattr(attr):
            p = entity.dxf.get(attr)
            return (p.x * scale, p.y * scale)
    return None
