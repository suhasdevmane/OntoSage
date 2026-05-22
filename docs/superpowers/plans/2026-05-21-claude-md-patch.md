# CLAUDE.md patch — to apply after Phase 3 cleanup

> **DO NOT apply this patch yet.** It updates `CLAUDE.md` to reflect the
> post-Phase-3 architecture (semantic-routing only, no keyword frozensets).
> Apply manually after `scripts/phase3_cleanup.py` runs and all gates pass.

## Patch 1: Quick Navigation Index — add three new entries

Edit `CLAUDE.md` Quick Navigation Index table. **Insert these rows** in the
alphabetical-ish ordering used today (the table is roughly grouped by subsystem):

```diff
 | Task | File | Line | Symbol |
 |------|------|------|--------|
 ...
 | Capability KB load/search | `orchestrator/agents/capability_agent.py` | 67 | `CapabilityAgent.answer()` |
+| Capability semantic indexer | `orchestrator/services/capability_indexer.py` | 60 | `class CapabilityIndexer` |
+| Capability semantic router | `orchestrator/services/semantic_router.py` | 71 | `class SemanticRouter` |
+| Embedding service wrapper | `orchestrator/services/embedding_service.py` | 50 | `class EmbeddingService` |
+| Capability routing config | `shared/capability_schema.py` | 19 | `class CapabilityRoutingConfig` |
```

## Patch 2: Architecture section — add semantic routing pipeline

After the existing "How the system chooses TTL/SPARQL vs PDF/DWG data" section,
**insert a new section**:

```markdown
### Capability semantic routing (added 2026-05-21)

The dialogue agent has a fast-path for capability queries (off-ontology
building features, policies, amenities) that bypasses the LLM intent call
when a high-confidence semantic match exists.

**Pipeline:**

1. At startup, `CapabilityIndexer` reads each `input/<bldg>/capability.yaml`,
   embeds every keyword + content snippet via `EmbeddingService` (OpenAI or
   local), and upserts into a Qdrant collection `capability_<bldg>`. The
   indexer is idempotent — unchanged YAML (SHA-256 match) skips re-embedding.

2. On every query, `dialogue_agent.detect_intent()` calls `SemanticRouter.classify(query, building_id)` BEFORE the LLM intent call.

3. Decision rule (per-building tunable in `input/<bldg>/building.yaml`):
   - `score >= override_min` (default 0.85) → intent=capability, skip LLM
   - `threshold <= score < override_min` (default 0.65) → soft override after
     LLM (only if LLM picked a non-data intent)
   - `score < threshold` → no signal, LLM intent classification proceeds

4. `CapabilityAgent.answer()` reads the pre-fetched matches from
   `state.intermediate_results["capability_matches"]` and formats the
   response — no second KB search.

**Per-building config** (`input/<bldg>/building.yaml`):

\`\`\`yaml
capability_routing:
  enabled: true
  threshold: 0.65       # soft override band lower bound
  override_min: 0.85    # skip-LLM threshold
  top_k: 5
  embedding_model: auto # 'auto' follows EMBEDDING_PROVIDER
\`\`\`

**Adding a new building's capability KB:** drop `capability.yaml` into
`input/<bldg>/`, restart the orchestrator. Zero Python edits required.
Failure (Qdrant down, embedding API down) is graceful — orchestrator boots,
router returns `source="fallback"`, dialogue agent reverts to LLM-only intent.
```

## Patch 3: Common Debugging Patterns — add capability semantic section

After the existing "SPARQL returns empty" section, **insert**:

```markdown
### Capability semantic routing not firing
\`\`\`bash
# 1. Verify the per-building collection exists in Qdrant
curl -s http://localhost:6333/collections | python -m json.tool | grep capability_

# 2. If missing, check indexer logs at startup
docker logs ontosage-orchestrator | grep capability_indexer
# Look for: "status=indexed entries=N points=M" (success) vs "status=degraded"

# 3. Most common degraded reason: embedding library missing
# Either install sentence-transformers in the orchestrator image, OR switch:
#   EMBEDDING_PROVIDER=openai in .env (uses existing OPENAI_API_KEY)

# 4. Inspect a stored point to verify yaml_sha
curl -s 'http://localhost:6333/collections/capability_bldg1/points/scroll?limit=1' \
  | python -m json.tool | grep yaml_sha
\`\`\`

### Capability returns wrong KB entry
\`\`\`bash
# Lower threshold temporarily to see all candidates
# Edit input/<bldg>/building.yaml:
#   capability_routing:
#     threshold: 0.30      # see everything
#     override_min: 0.50
# Restart, send the query, check logs for "[semantic-route]" lines showing scores.
\`\`\`
```

## Patch 4: Remove obsolete keyword-routing references

Search and remove any references to `_CAPABILITY_KW` or `_STRONG_FACILITY_KW`
in CLAUDE.md if they exist:

```bash
grep -n "_CAPABILITY_KW\|_STRONG_FACILITY_KW" CLAUDE.md
```

If matches exist (they may from prior debugging context), delete those lines —
they will be wrong after Phase 3 cleanup.

---

## Apply this patch

After Phase 3 cleanup completes and all gates pass:

1. Read this file.
2. Apply each patch above to `CLAUDE.md` manually using the Edit tool.
3. Verify: `grep -n "semantic_router\|CapabilityIndexer\|capability_<bldg>" CLAUDE.md` returns matches.
4. Verify: `grep -n "_CAPABILITY_KW\|_STRONG_FACILITY_KW" CLAUDE.md` returns zero matches.
