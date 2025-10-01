import csv
import glob
import os
from pathlib import Path
from rdflib import Graph

HERE = Path(__file__).parent
BUILDINGS_DIR = HERE / "buildings"
QUERIES_DIR = HERE / "queries"
RESULTS_DIR = HERE / "results"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_graph(ttl_path: Path) -> Graph:
    g = Graph()
    g.parse(ttl_path.as_posix(), format="turtle")
    return g


def run_query(g: Graph, rq_path: Path):
    query = rq_path.read_text(encoding="utf-8")
    return g.query(query)


def main():
    buildings = sorted(BUILDINGS_DIR.glob("*.ttl"))
    queries = sorted(QUERIES_DIR.glob("*.rq"))

    if not buildings:
        print("No building TTLs found.")
        return
    if not queries:
        print("No queries found.")
        return

    # Run each query across every building graph
    for rq in queries:
        out_csv = RESULTS_DIR / f"{rq.stem}.csv"
        rows = []
        header = None
        for b in buildings:
            g = load_graph(b)
            res = run_query(g, rq)
            # Determine header from result vars the first time
            if header is None:
                header = ["building"] + [str(v) for v in res.vars]
            for row in res:
                rows.append([b.stem] + [str(x) for x in row])
        # Write output
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header or ["building"])  # header fallback
            writer.writerows(rows)
        print(f"Wrote {out_csv} with {len(rows)} rows")


if __name__ == "__main__":
    main()
