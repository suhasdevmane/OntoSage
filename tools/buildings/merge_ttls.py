import sys
from pathlib import Path
from rdflib import Graph

"""
merge_ttls.py

Usage:
  python tools/buildings/merge_ttls.py <out_ttl> <ttl1> [<ttl2> ...]

Merges multiple TTL files into a single Turtle graph and writes it to <out_ttl>.
This preserves data as-is; it does not attempt to normalize namespaces or shapes.
"""

def merge_ttls(out_path: Path, inputs: list[Path]):
    g = Graph()
    for p in inputs:
        g.parse(p.as_posix(), format="turtle")
    g.serialize(destination=out_path.as_posix(), format="turtle")
    print(f"Wrote {out_path} from {len(inputs)} files")


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/buildings/merge_ttls.py <out_ttl> <ttl1> [<ttl2> ...]")
        sys.exit(1)
    out_path = Path(sys.argv[1])
    inputs = [Path(x) for x in sys.argv[2:]]
    merge_ttls(out_path, inputs)


if __name__ == "__main__":
    main()
