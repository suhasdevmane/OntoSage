"""
Build synthetic multi-storey DXF plans that mimic the layer structure observed
in the Abacws drawings, so the pipeline can be verified without the real files.

Ground truth encoded here, per floor:
  <n>Z19 "Vending"       24.0 m2   adjacent to <n>Z21 (4.0m) and <n>.29 (6.0m)
  <n>Z21 "41P Collab S"  24.0 m2   adjacent to <n>Z19 (4.0m) and <n>.29 (6.0m)
  <n>.29 "Refuse Store"  36.0 m2   adjacent to both
  <n>Z05 "Stair Core"     9.0 m2   SAME footprint on every floor
  doors: Z19<->Z21, Z19<->.29, Z21<->Z05   (Z21 has NO door to .29,
    so reaching .29 from Z21 must route through Z19)
  3 DIMENSION entities per floor: 6.0 m, 6.0 m (outside rooms) and
    4.0 m (inside Vending, so in_space binding is tested too)
  one electrical equipment item with ATTRIBs inside <n>Z19

Units are millimetres, matching UK architectural practice.
"""

from pathlib import Path
import ezdxf

MM = 1000  # one metre in drawing units

ROOMS = [
    (0, 0, 6, 4, "Z19", "Vending"),
    (6, 0, 12, 4, "Z21", "41P Collab S"),
    (0, 4, 12, 7, ".29", "Refuse Store"),
    (12, 0, 15, 3, "Z05", "Stair Core"),   # stacks on every storey
]

DOORS = [
    (6.0, 2.0),    # Vending <-> Collab
    (3.0, 4.0),    # Vending <-> Refuse Store
    (12.0, 1.5),   # Collab <-> Stair Core (the route onto other floors)
]
EQUIPMENT = [(1.0, 1.0)]

# (x1, y1, x2, y2, dimline_y) -> expected measurement = x2 - x1
# The first two sit outside any room (below the plan, as drafters normally
# place them); the third sits inside Vending, so the in_space binding is
# exercised as well as the measurement itself.
DIMENSIONS = [
    (0.0, 0.0, 6.0, 0.0, -1.0),    # 6.0 m, in_space None
    (6.0, 0.0, 12.0, 0.0, -1.0),   # 6.0 m, in_space None
    (1.0, 1.0, 5.0, 1.0, 2.0),     # 4.0 m, inside Vending
]


def build_floor(level: int, path: str) -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    for name, color in [
        ("USABLE", 3), ("POLYLINES", 1), ("ROOM_NAMES", 7), ("A-DOOR", 4),
        ("CSM-STL-XX-ZZ-E-ELEC-EQPI", 5), ("A-ANNO-DIMS", 6), ("TITLE_BLK", 8),
    ]:
        doc.layers.add(name=name, color=color)

    door_block = doc.blocks.new(name="DR_SINGLE")
    door_block.add_line((0, 0), (0, 900))
    door_block.add_arc((0, 0), 900, 0, 90)

    equip_block = doc.blocks.new(name="ELEC_DB")
    equip_block.add_lwpolyline([(0, 0), (400, 0), (400, 400), (0, 400)], close=True)

    for x0, y0, x1, y1, suffix, name in ROOMS:
        points = [(x0 * MM, y0 * MM), (x1 * MM, y0 * MM),
                  (x1 * MM, y1 * MM), (x0 * MM, y1 * MM)]
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": "USABLE"})

        code = f"{level}{suffix}"
        cx, cy = (x0 + x1) / 2 * MM, (y0 + y1) / 2 * MM
        msp.add_text(code, height=200, dxfattribs={"layer": "ROOM_NAMES"}
                     ).set_placement((cx, cy + 300))
        msp.add_text(name, height=200, dxfattribs={"layer": "ROOM_NAMES"}
                     ).set_placement((cx, cy - 300))

    for x, y in DOORS:
        msp.add_blockref("DR_SINGLE", (x * MM, y * MM), dxfattribs={"layer": "A-DOOR"})

    for x, y in EQUIPMENT:
        ref = msp.add_blockref("ELEC_DB", (x * MM, y * MM),
                               dxfattribs={"layer": "CSM-STL-XX-ZZ-E-ELEC-EQPI"})
        ref.add_attrib("ASSET_ID", f"DB-{level}-014", (x * MM, y * MM))
        ref.add_attrib("CIRCUIT", f"L{level}-04", (x * MM, y * MM - 200))

    # Real DIMENSION entities - these carry a computed `measurement`.
    for x1, y1, x2, y2, dim_y in DIMENSIONS:
        dim = msp.add_linear_dim(
            base=(0, dim_y * MM),
            p1=(x1 * MM, y1 * MM),
            p2=(x2 * MM, y2 * MM),
            dxfattribs={"layer": "A-ANNO-DIMS"},
        )
        dim.render()

    msp.add_line((0, -2000), (15000, -2000), dxfattribs={"layer": "A-ANNO-DIMS"})
    msp.add_text(f"ABACWS - LEVEL {level}", height=500,
                 dxfattribs={"layer": "TITLE_BLK"}).set_placement((0, -3000))

    doc.saveas(path)
    return path


def build_all(outdir: str = "synthetic", levels: int = 3) -> list[str]:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    return [
        build_floor(level, str(Path(outdir) / f"Abacws floor {level}.dxf"))
        for level in range(levels)
    ]


if __name__ == "__main__":
    import sys
    levels = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for path in build_all(levels=levels):
        print(path)
