"""Load the frozen study graph into a THROWAWAY GraphDB and re-count Building A for section 4 (29 Oct 2026).

The table of building counts and the layered-model figure carried the live counts of 24 September 2026. Participants
used the graph frozen on 14 October 2026 (Freeze_2026-10-14/snapshot1_graph.trig: GraphDB export of repository `bldg`,
explicit statements only). This script:
  1. checks the snapshot against its recorded SHA-256;
  2. creates repository `recount` in a GraphDB started for this purpose (default http://127.0.0.1:7299, a container
     with no volume), with the live repository's configuration (config/graphdb_repo_bldg.ttl: ruleset
     rdfsplus-optimized), so inference is the same as when the 24 September counts were made;
  3. loads the snapshot and checks that the explicit statement count equals the freeze record's 315,662;
  4. runs paper/scripts/live_building_facts.py against it, writing to paper/generated/frozen_2026-10-14/.
The live building's GraphDB is never contacted.

Usage: python recount_frozen_graph.py [--base http://127.0.0.1:7299]
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(PAPER)
FREEZE = os.path.join(PAPER, "phd plan", "[anonymised]", "12_OntoSage_Readiness", "Freeze_2026-10-14")
TRIG = os.path.join(FREEZE, "snapshot1_graph.trig")
CONFIG = os.path.join(REPO_ROOT, "config", "graphdb_repo_bldg.ttl")
OUT = os.path.join(PAPER, "generated", "frozen_2026-10-14")
REPO = "recount"
EXPECTED_STATEMENTS = 315662


def http(method: str, url: str, data: bytes = None, headers: dict = None, timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7299")
    base = ap.parse_args().base.rstrip("/")
    if base.endswith(":7200"):
        print("refusing to use port 7200: that is the live building's GraphDB")
        return 1

    want = open(TRIG + ".sha256", encoding="utf-8").read().split()[0].strip().lower()
    got = hashlib.sha256(open(TRIG, "rb").read()).hexdigest()
    print(f"snapshot sha256 {got} ({'matches' if got == want else 'DOES NOT MATCH'} the freeze record)")
    if got != want:
        return 1

    for _ in range(60):
        try:
            http("GET", base + "/rest/repositories", timeout=5)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(3)
    else:
        print("GraphDB did not answer")
        return 1

    cfg = open(CONFIG, encoding="utf-8").read().replace('repositoryID> "bldg"', f'repositoryID> "{REPO}"')
    cfg = cfg.replace("<#bldg>", f"<#{REPO}>")
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"config\"; filename=\"repo.ttl\"\r\n"
            f"Content-Type: text/turtle\r\n\r\n{cfg}\r\n--{boundary}--\r\n").encode("utf-8")
    try:
        http("POST", base + "/rest/repositories", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        print(f"repository '{REPO}' created (ruleset rdfsplus-optimized)")
    except urllib.error.HTTPError as e:
        print(f"create repository: HTTP {e.code} {e.read()[:300]!r}")
        return 1

    t = time.time()
    http("POST", f"{base}/repositories/{REPO}/statements", open(TRIG, "rb").read(),
         {"Content-Type": "application/trig"}, timeout=1800)
    print(f"snapshot loaded in {time.time() - t:.0f} s")

    q = "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"
    import json
    import urllib.parse
    res = json.loads(http("POST", f"{base}/repositories/{REPO}",
                          urllib.parse.urlencode({"query": q, "infer": "false"}).encode(),
                          {"Accept": "application/sparql-results+json",
                           "Content-Type": "application/x-www-form-urlencoded"}))
    n = int(res["results"]["bindings"][0]["n"]["value"])
    print(f"explicit statements in named graphs: {n:,} (freeze record: {EXPECTED_STATEMENTS:,})")
    if n != EXPECTED_STATEMENTS:
        print("count differs from the freeze record; stopping")
        return 1

    env = dict(os.environ, GRAPHDB_SPARQL=f"{base}/repositories/{REPO}", LIVE_FACTS_OUT=OUT,
               PYTHONIOENCODING="utf-8")
    return subprocess.call([sys.executable, os.path.join(PAPER, "scripts", "live_building_facts.py")], env=env)


if __name__ == "__main__":
    sys.exit(main())
