"""
Extracts all sensor instances that have external UUID references from bldg3_timeseries.ttl
and writes lines of "<sensor_uri>\t<uuid>" to sensor_uuids.txt in the same folder.
"""
from pathlib import Path
from rdflib import Graph, Namespace
from add_timeseries_refs_used import _parse_turtle_with_fallback

BRICK = Namespace("https://brickschema.org/schema/Brick#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

HERE = Path(__file__).parent
TTL = HERE / "bldg3_timeseries.ttl"
OUT = HERE / "sensor_uuids.txt"


def parse_ttl_robust(ttl_path: Path) -> Graph:
    return _parse_turtle_with_fallback(ttl_path)


def main():
    g = parse_ttl_robust(TTL)

    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?s ?uuid WHERE {
        ?s a ?type .
        ?type rdfs:subClassOf* brick:Sensor .
        {
            # Case 1: reference is a node (IRI or blank node) that has a timeseries id
            ?s ref:hasExternalReference ?refNode .
            ?refNode ref:hasTimeseriesId ?uuid .
        }
        UNION
        {
            # Case 2: legacy literal reference id; convert to IRI and follow
            ?s ref:hasExternalReference ?refId .
            FILTER(isLiteral(?refId))
            BIND(IRI(STR(?refId)) AS ?refNode)
            ?refNode ref:hasTimeseriesId ?uuid .
        }
    }
    ORDER BY ?s
    """

    rows = list(g.query(q))

    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            s = str(row[0])
            uuid = str(row[1])
            f.write(f"{s},{uuid}\n")

    print(f"Wrote {OUT} with {len(rows)} entries")


if __name__ == "__main__":
    main()
