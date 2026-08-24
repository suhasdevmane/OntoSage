# Fixture building (V6-T64)

Used by V6 unit tests instead of bldg1/bldg2/bldg3. It exists to make building-shaped
assumptions fail fast, so it shares nothing with any real building:

| Property | Real buildings | This fixture |
|---|---|---|
| namespace | `…cardiff.ac.uk/abacws#` / `buildsys.org…#` | `http://example.invalid/fixture/` (no `#`) |
| room ids | dotted — `2.15`, `0.34` | hyphenated — `W-A1` |
| floors | numbered 0–5 | **named** — Ground, Upper |
| floor plans | DWG + DXF + PDF | **none** |
| sensors | hundreds | **two**, one of which has no timeseries at all |

The last row matters most: `fix:Co2B1` is *declared but not connected*, which is a different
state from *not instrumented*, and the two are easy to conflate in code.

**Rule:** a V6 test that needs a building uses this one. `pytest -m unit` must pass in the
parked state (no active building) — if a test needs bldg1 to be present, it is testing bldg1,
not the system.
