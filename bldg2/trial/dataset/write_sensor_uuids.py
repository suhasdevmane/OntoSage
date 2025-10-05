"""
Extracts all sensor instances that have external UUID references from bldg2_timeseries.ttl
and writes lines of "<sensor_uri>\t<uuid>" to sensor_uuids.txt in the same folder.
"""
from pathlib import Path
from rdflib import Graph, Namespace

BRICK = Namespace("https://brickschema.org/schema/Brick#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

HERE = Path(__file__).parent
TTL = HERE / "bldg2.ttl"
OUT = HERE / "sensor_uuids.txt"


def parse_ttl_robust(ttl_path: Path) -> Graph:
    g = Graph()
    g.parse(ttl_path.as_posix(), format="turtle")
    return g


def main():
    g = parse_ttl_robust(TTL)

    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    PREFIX owl:   <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?s ?uuid WHERE {
        {
            # Instance sensors
            ?s a ?type .
            ?type rdfs:subClassOf* brick:Sensor .
            {
                # Ref is a node (IRI or blank) with a timeseries id
                ?s ref:hasExternalReference ?refNode .
                ?refNode ref:hasTimeseriesId ?uuid .
            }
            UNION
            {
                # Legacy literal reference id; convert to IRI and follow
                ?s ref:hasExternalReference ?refId .
                FILTER(isLiteral(?refId))
                BIND(IRI(STR(?refId)) AS ?refNode)
                ?refNode ref:hasTimeseriesId ?uuid .
            }
        }
        UNION
        {
            # Class sensors
            ?s a owl:Class .
            ?s rdfs:subClassOf* brick:Sensor .
            {
                ?s ref:hasExternalReference ?refNode .
                ?refNode ref:hasTimeseriesId ?uuid .
            }
            UNION
            {
                ?s ref:hasExternalReference ?refId .
                FILTER(isLiteral(?refId))
                BIND(IRI(STR(?refId)) AS ?refNode)
                ?refNode ref:hasTimeseriesId ?uuid .
            }
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
