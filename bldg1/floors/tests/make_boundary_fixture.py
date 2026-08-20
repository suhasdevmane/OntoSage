"""
A floor plan with deliberate defects, to prove the boundary tracer both
succeeds where it should and FAILS LOUDLY where it should.

Layers match the real Abacws convention: A-WALL / I-WALL, A-DOOR, A-AREA-IDEN.
Units are millimetres. Walls are drawn as two parallel lines, as in a real
architectural drawing, so the tracer has to return the INNER face.

Ground truth
------------
  0.01  large west room                89.90 m2   traced OK
  0.02  south-centre room  ) gap in the partition between them at y 2-3,
  0.03  south-east room    ) so BOTH must FAIL as one merged region
  0.04  north room, reached through a real doorway opening sealed only by
        the A-DOOR jamb lines            67.31 m2   traced OK, 1 island (column)
  0.06  detached annex, west wall missing         FAILS, leaks to exterior
  0.07  number sitting inside a wall cavity       FAILS, only 0.10 m across
"""

from pathlib import Path
import ezdxf

MM = 1000
OUTER_T = 0.2      # outer wall thickness (m)
INNER_T = 0.1      # partition thickness (m)


def rect_lines(msp, x0, y0, x1, y1, layer):
    """Four lines forming a rectangle."""
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        msp.add_line((ax * MM, ay * MM), (bx * MM, by * MM),
                     dxfattribs={"layer": layer})


def vline(msp, x, y0, y1, layer, gap=None):
    """Vertical line, optionally with a gap - the classic BOUNDARY killer."""
    if gap is None:
        msp.add_line((x * MM, y0 * MM), (x * MM, y1 * MM), dxfattribs={"layer": layer})
        return
    g0, g1 = gap
    msp.add_line((x * MM, y0 * MM), (x * MM, g0 * MM), dxfattribs={"layer": layer})
    msp.add_line((x * MM, g1 * MM), (x * MM, y1 * MM), dxfattribs={"layer": layer})


def hline(msp, y, x0, x1, layer):
    msp.add_line((x0 * MM, y * MM), (x1 * MM, y * MM), dxfattribs={"layer": layer})


def build(path: str = "boundary_fixture.dxf") -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    for name, color in [
        ("A-WALL", 7), ("I-WALL", 8), ("A-DOOR", 4),
        ("A-AREA-IDEN", 2), ("A-ANNO-DIMS", 6), ("TITLE_BLK", 8),
    ]:
        doc.layers.add(name=name, color=color)

    # ---- outer shell: two rectangles = a wall with thickness ----
    rect_lines(msp, 0, 0, 20, 12, "A-WALL")
    rect_lines(msp, OUTER_T, OUTER_T, 20 - OUTER_T, 12 - OUTER_T, "A-WALL")

    h = INNER_T / 2
    # ---- partition at x=8, full height (separates 0.01 from the rest) ----
    vline(msp, 8 - h, OUTER_T, 12 - OUTER_T, "I-WALL")
    vline(msp, 8 + h, OUTER_T, 12 - OUTER_T, "I-WALL")

    # ---- partition at y=6, east side, WITH A REAL DOORWAY OPENING at x 9-10.
    # The opening is a genuine gap in the wall lines. Only the door jamb lines
    # on A-DOOR seal it, which is exactly why door layers must be included in
    # the linework: without them 0.04 leaks into 0.02/0.03.
    hline(msp, 6 - h, 8 + h, 9.0, "I-WALL")
    hline(msp, 6 - h, 10.0, 20 - OUTER_T, "I-WALL")
    hline(msp, 6 + h, 8 + h, 9.0, "I-WALL")
    hline(msp, 6 + h, 10.0, 20 - OUTER_T, "I-WALL")

    # ---- partition at x=14 WITH A 1 m GAP -> 0.02 and 0.03 merge ----
    vline(msp, 14 - h, OUTER_T, 6 - h, "I-WALL", gap=(2.0, 3.0))
    vline(msp, 14 + h, OUTER_T, 6 - h, "I-WALL", gap=(2.0, 3.0))

    # ---- a structural column inside 0.04 -> island, area overstated ----
    rect_lines(msp, 10.0, 8.0, 10.5, 8.5, "A-WALL")

    # ---- detached annex with NO west wall -> 0.06 leaks to the exterior ----
    hline(msp, 0.0, 21, 24, "A-WALL")
    hline(msp, 3.0, 21, 24, "A-WALL")
    vline(msp, 24.0, 0, 3, "A-WALL")
    # (the x=21 wall is deliberately absent)

    # ---- the door itself: jamb lines seal the opening; the swing arc is
    # decorative and would carve a curved bite out of 0.04 if included ----
    msp.add_line((9.0 * MM, (6 - h) * MM), (9.0 * MM, (6 + h) * MM),
                 dxfattribs={"layer": "A-DOOR"})
    msp.add_line((10.0 * MM, (6 - h) * MM), (10.0 * MM, (6 + h) * MM),
                 dxfattribs={"layer": "A-DOOR"})
    # Threshold lines closing the wall gap - this is what a door block
    # normally contributes, and it is the ONLY thing standing between 0.04
    # and a leak into 0.02/0.03. Jamb lines alone do not seal an opening:
    # they partition the wall cavity without blocking passage through it.
    hline(msp, 6 - h, 9.0, 10.0, "A-DOOR")
    hline(msp, 6 + h, 9.0, 10.0, "A-DOOR")
    msp.add_arc((9.0 * MM, (6 + h) * MM), 1.0 * MM, 0, 90,
                dxfattribs={"layer": "A-DOOR"})

    # ---- room numbers on A-AREA-IDEN ----
    rooms = [
        ("0.01", 4.0, 6.0),
        ("0.02", 11.0, 3.0),
        ("0.03", 17.0, 3.0),
        ("0.04", 14.0, 9.0),
        ("0.06", 22.5, 1.5),     # inside the open annex
        ("0.07", 8.0, 1.0),      # sitting inside the x=8 partition itself
    ]
    for number, x, y in rooms:
        msp.add_text(number, height=250, dxfattribs={"layer": "A-AREA-IDEN"}
                     ).set_placement((x * MM, y * MM))
        # A name label that must NOT be mistaken for a room number.
        msp.add_text(f"ROOM {number}", height=200,
                     dxfattribs={"layer": "A-AREA-IDEN"}
                     ).set_placement((x * MM, (y - 0.5) * MM))

    msp.add_text("ABACWS - BOUNDARY FIXTURE", height=400,
                 dxfattribs={"layer": "TITLE_BLK"}).set_placement((0, -2000))

    doc.saveas(path)
    return path


if __name__ == "__main__":
    print(build())
