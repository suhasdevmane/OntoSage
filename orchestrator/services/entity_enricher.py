"""EntityEnricher (Part D) — make any input-TTL point queryable.

Scans GraphDB for time-series points (those with ``ref:hasTimeseriesId``) that lack
a Brick class and/or an ``rdfs:label``, derives the missing class / label /
relationships from the URI tokens (``shared.entity_enrichment``), and writes the
derived triples into a dedicated, idempotent named graph
``urn:ontosage:enrichment``. The user's raw input TTL is never modified — the
enrichment is a derived overlay so the standard class/label/relationship resolver
finds points regardless of their URI naming scheme.

Idempotent: each run DROPs the enrichment graph first, recomputes from the original
data, then PUTs the fresh overlay. Non-fatal everywhere — a failure leaves the
graph as-is and the orchestrator still boots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

import httpx

from shared.config import settings
from shared.entity_enrichment import EnrichmentConfig, enrich_entity, local_name
from shared.utils import get_logger

logger = get_logger(__name__)

ENRICHMENT_GRAPH = "urn:ontosage:enrichment"
_BRICK = "https://brickschema.org/schema/Brick#"


@dataclass
class EnrichmentReport:
    scanned: int = 0
    classes_added: int = 0
    labels_added: int = 0
    relationships_added: int = 0
    stubs_added: int = 0
    unmapped: List[str] = field(default_factory=list)  # local-names with no class inferred

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} classes+={self.classes_added} labels+={self.labels_added} "
            f"rels+={self.relationships_added} stubs+={self.stubs_added} unmapped={len(self.unmapped)}"
        )


class EntityEnricher:
    def __init__(
        self,
        graphdb_url: Optional[str] = None,
        repository: Optional[str] = None,
        config: Optional[EnrichmentConfig] = None,
    ):
        host = settings.GRAPHDB_HOST
        port = settings.GRAPHDB_PORT
        self._base = (graphdb_url or f"http://{host}:{port}").rstrip("/")
        self._repo = repository or (settings.GRAPHDB_REPOSITORY or "bldg")
        self._cfg = config or EnrichmentConfig.load()
        self._auth = (
            (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
        )

    @property
    def _query_url(self) -> str:
        return f"{self._base}/repositories/{self._repo}"

    @property
    def _statements_url(self) -> str:
        return f"{self._base}/repositories/{self._repo}/statements"

    async def _select(self, client: httpx.AsyncClient, sparql: str) -> List[dict]:
        r = await client.post(
            self._query_url,
            auth=self._auth,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        return r.json().get("results", {}).get("bindings", [])

    async def _valid_classes(self, client: httpx.AsyncClient, candidates: Set[str]) -> Set[str]:
        """Return the subset of prefixed classes that actually exist as owl:Class."""
        if not candidates:
            return set()
        values = " ".join(f"{c}" if ":" in c else f"<{c}>" for c in candidates)
        q = (
            "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
            "PREFIX bldg: <" + settings.BUILDING_NAMESPACE + ">\n"
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            f"SELECT ?c WHERE {{ VALUES ?c {{ {values} }} ?c a owl:Class }}"
        )
        rows = await self._select(client, q)
        # Map full URIs back to the prefixed form the caller used.
        valid_full = {b["c"]["value"] for b in rows}
        out = set()
        for c in candidates:
            full = c.replace("brick:", _BRICK).replace("bldg:", settings.BUILDING_NAMESPACE)
            if full in valid_full:
                out.add(c)
        return out

    async def find_bare_points(self, client: httpx.AsyncClient) -> List[Tuple[str, bool, bool]]:
        """Return (uri, has_class, has_label) for time-series points missing either.

        Excludes the enrichment graph so the scan reflects the ORIGINAL data and the
        run stays idempotent (we DROP the overlay before scanning)."""
        q = f"""
PREFIX brick: <{_BRICK}>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s (COUNT(DISTINCT ?bc) AS ?nclass) (COUNT(DISTINCT ?lbl) AS ?nlabel) WHERE {{
  ?s ref:hasExternalReference/ref:hasTimeseriesId ?u .
  OPTIONAL {{ ?s a ?bc . FILTER(STRSTARTS(STR(?bc), "{_BRICK}")) }}
  OPTIONAL {{ ?s rdfs:label ?lbl }}
}}
GROUP BY ?s
HAVING (COUNT(DISTINCT ?bc) = 0 || COUNT(DISTINCT ?lbl) = 0)
"""
        rows = await self._select(client, q)
        out: List[Tuple[str, bool, bool]] = []
        for b in rows:
            uri = b["s"]["value"]
            has_class = int(b.get("nclass", {}).get("value", "0")) > 0
            has_label = int(b.get("nlabel", {}).get("value", "0")) > 0
            out.append((uri, has_class, has_label))
        return out

    def _build_overlay_ttl(
        self, bare: List[Tuple[str, bool, bool]], valid_classes: Set[str], report: EnrichmentReport
    ) -> str:
        ns = settings.BUILDING_NAMESPACE
        lines = [
            f"@prefix bldg: <{ns}> .",
            "@prefix brick: <https://brickschema.org/schema/Brick#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "",
        ]
        stub_emitted: Set[str] = set()
        for uri, has_class, has_label in bare:
            res = enrich_entity(uri, self._cfg)
            ln = local_name(uri)
            triples: List[str] = []
            cls_ok = res.brick_class in valid_classes if res.brick_class else False
            if not has_class:
                if cls_ok:
                    triples.append(f"a {res.brick_class}")
                    report.classes_added += 1
                else:
                    report.unmapped.append(ln)
            if not has_label:
                esc = res.label.replace("\\", "\\\\").replace('"', '\\"')
                triples.append(f'rdfs:label "{esc}"@en')
                report.labels_added += 1
            # Relationships only when we could class the point (avoids noise).
            if cls_ok and not has_class:
                for pred, target in res.relationships:
                    triples.append(f"{pred} bldg:{target}")
                    report.relationships_added += 1
                for stub_local, stub_class in res.stubs:
                    if stub_local not in stub_emitted and stub_class in valid_classes:
                        lines.append(f"bldg:{stub_local} a {stub_class} .")
                        stub_emitted.add(stub_local)
                        report.stubs_added += 1
            if triples:
                lines.append(f"<{uri}> " + " ;\n    ".join(triples) + " .")
        return "\n".join(lines) + "\n"

    async def enrich(self, dry_run: bool = False) -> EnrichmentReport:
        """Recompute and (unless dry_run) write the enrichment overlay. Idempotent."""
        report = EnrichmentReport()
        from urllib.parse import quote

        ctx = quote(f"<{ENRICHMENT_GRAPH}>", safe="")
        async with httpx.AsyncClient(timeout=60.0) as client:
            # DROP the overlay first so the scan reflects the original data.
            if not dry_run:
                await client.delete(f"{self._statements_url}?context={ctx}", auth=self._auth)
            bare = await self.find_bare_points(client)
            report.scanned = len(bare)
            if not bare:
                return report
            wanted = {enrich_entity(u, self._cfg).brick_class for u, _, _ in bare}
            wanted |= {c for u, _, _ in bare for _, c in enrich_entity(u, self._cfg).stubs}
            valid = await self._valid_classes(client, {c for c in wanted if c})
            ttl = self._build_overlay_ttl(bare, valid, report)
            if not dry_run and (report.classes_added or report.labels_added):
                resp = await client.put(
                    f"{self._statements_url}?context={ctx}",
                    auth=self._auth,
                    content=ttl.encode("utf-8"),
                    headers={"Content-Type": "text/turtle"},
                )
                resp.raise_for_status()
        return report


async def run_entity_enrichment() -> EnrichmentReport:
    """Entry point for startup / CLI. Non-fatal — logs and returns the report."""
    try:
        enricher = EntityEnricher()
        report = await enricher.enrich()
        logger.info(f"[entity_enricher] {report.summary()}")
        if report.unmapped:
            logger.info(
                f"[entity_enricher] {len(report.unmapped)} point(s) had no class mapping "
                f"(extend config/entity_enrichment.yaml): {report.unmapped[:10]}"
            )
        return report
    except Exception as e:  # pragma: no cover - network dependent
        logger.warning(f"[entity_enricher] enrichment failed (non-fatal): {e}")
        return EnrichmentReport()
