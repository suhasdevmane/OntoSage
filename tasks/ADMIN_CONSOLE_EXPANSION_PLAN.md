# Admin Console — Expansion Plan

**Status:** proposed · **Date:** 2026-07-05 · **Lens:** demo-first, production-aware
**Scope target:** `config-panel/html/` (SPA) + `orchestrator/main.py` admin endpoints +
`orchestrator/services/admin_config.py` + a few config files.

---

## 0. Read this first — the frame, and the trap

The console is **already a 5-tab admin SPA**, not a toggle widget: Data Sources,
`.env` editor, external DB connect + sensor registration (points/CSV/TTL → Brick
triples), user/role CRUD + role→datasource access matrix, and Health. So the job is
**not** "add 30 features to an empty shell." It's "close the specific gaps that make
the demo story clean and the console feel professional, without turning a focused tool
into abandonware."

**The governing constraint (decides several designs below):** `shared/config.py`
resolves and *validates* the provider at **boot** — `_validate()` raises if the chosen
provider's key is missing, and `get_llm_config()` / `get_embedding_config()` are read
when each agent's LLM/embedding client is constructed. Consequence: **provider/model
changes are an `.env`-write + restart, not a live hot-swap.** The console already has a
`.env` writer and a restart button — we extend that pattern. Live hot-swap (re-init
every agent client, re-warm, reindex Qdrant on embedding-dim change, drain in-flight
requests) is a rabbit hole and explicitly out of scope for v1.

**What "done" looks like — the target demo narrative.** Every Tier-1 item below exists
to make *this* 6-step walkthrough work end-to-end, in the console, with zero terminal:

1. Open console → **Overview** shows: provider = Local Ollama (deepseek-r1), 1/8 sources
   enabled, all services green.
2. **AI & Models** tab → switch to a different installed Ollama model (picked from a live
   list of what's actually installed) → restart notice → restart.
3. **Query tester** (in-console) → ask *"what's the noise level on floor 5?"* → get the
   **named locked decline** ("enable Acoustic Sensing").
4. **Data Sources** → regenerate + enable Noise → (cache auto-flush).
5. **Query tester** → same question → **substantive answer + provenance chips**
   (Building Ontology · Acoustic Sensing System · Analytics Engine).
6. **Databases** → "Load demo database" → connect the seeded dummy MySQL → register its
   sensors → ask a question it answers. Then **"Reset to demo state."**

If a proposed feature doesn't sharpen that narrative or a clear professional-polish need,
it's Tier 3 or cut.

---

## 1. Tiered roadmap (the whole catalog, critically filtered)

Legend — Effort: **S** ≤ half-day · **M** ~1–2 days · **L** ~3–5 days. Every item lists a
**Trap** = the over-build to avoid.

### TIER 1 — demo-critical (build first)

| # | Item | Why it matters | Effort |
|---|---|---|---|
| A1 | **AI & Models tab** — provider radio (OpenAI / Local Ollama / Ollama Cloud), model dropdown, embedding provider, Test-connection, Save→restart | Your #1 ask; today it's raw `.env` editing. Direct demo payoff (local vs cloud). | **M** |
| E2 | **In-console Query Tester** — ask a question, render answer + provenance chips + route decision | Makes the console *self-demonstrating*; closes the toggle→ask→unlock loop without leaving the page | **M** |
| E1 | **Bulk ops + "Reset to demo state"** — enable/disable many; one-click disable-all + cache flush | Idempotent demo reset between runs (my QA script does this manually today) | **S** |
| C1 | **Guide / How-to tab** — static: what each tab does, "two halves of a datasource" model, connect-a-DB flow, model switcher, roles | Your #4 ask; onboarding for a non-author admin | **S–M** |
| G1 | **Overview / dashboard landing tab** — provider, #enabled sources, #users, health at a glance | Clean demo opener; orients a first-time viewer | **S** |
| F1 | **Auth the two unauthenticated admin endpoints** (`GET /api/v1/datasources`, `preview`) | Security: you're actively expanding a console with open admin reads. 1-line `Depends()` each. | **S** |

### TIER 2 — depth & professionalism (build second)

| # | Item | Why | Effort |
|---|---|---|---|
| B1–B3 | **Dockerized dummy external DB** (profile-gated) + "Load demo database" prefill + seeded sensor TTL | Your #3 ask; rehearse the real external-DB path in 2 clicks | **M–L** |
| A2 | **Live feeds panel** (`feeds.yaml` typed editor: weather/tariff REST-poll, csv-drop) | "AI integrations" ask; config already exists, needs a form | **M** |
| A3 | **Notification channels panel** (`channels.yaml`: log/webhook/smtp + test-send) | "AI integrations" ask; makes ECA-rule alerts demoable | **M** |
| D2 | **Data Sources card upgrade** — row count, last-regenerated ts, clearer on/off, per-card "unlocks" summary | Professional feel; reduces "did it work?" ambiguity | **S** |
| D3 | **Health tab upgrade** — per-service latency, circuit-breaker state (already in `/health`), auto-refresh, color | Looks like a real ops console | **S** |
| C2 | **Contextual "?" popovers** per tab (progressive disclosure) | Onboarding without a wall of text | **S** |

### TIER 3 — production-hardening (DESIGN FOR NOW, build when it goes to prod)

| # | Item | Why deferred | Effort |
|---|---|---|---|
| F2 | **Admin action audit log** (who changed what env/user/source, when) | Real ops need; not needed for the demo story | **M** |
| F3 | Fix remaining review findings: `.env` newline injection, `is_secret()` gaps (REDIS_URL/MONGODB_URI), mask-sentinel equality, `readonly:'*'` wildcard, `STRICT_SECRETS` missing `SECRET_KEY` | Correctness/security; low individual effort, batch them | **S–M** |
| F4 | Backup / restore of console-managed config (`datasources.custom.yaml`, `database_registry.custom.yaml`, `role_datasource_access.yaml`) | Ops safety net | **M** |
| E3 | Persisted provenance/analytics view (recent Q→sources) | Leans ops; `turn_memory` already stores enough to build later | **M** |
| — | SSO / multi-tenant / plugin marketplace | **Trap. Not now.** | — |

---

## 2. Workstream detail

### A. AI & Models + Integrations (your "model switcher" + "more skills")

**A1 — AI & Models tab.**
- **Backend:** new `GET /api/v1/admin/ai-config` (returns current `MODEL_PROVIDER`,
  resolved model, `EMBEDDING_PROVIDER`, and *masked* key presence — never the key value);
  `POST /api/v1/admin/ai-config/test` (provider reachability probe); Save reuses the
  existing `PUT /api/v1/admin/env` to write `MODEL_PROVIDER` / `OLLAMA_MODEL` /
  `OPENAI_MODEL` / `OPENAI_API_KEY` / `EMBEDDING_PROVIDER` etc.
- **Live model list (the demo winner):** for Local Ollama, call
  `GET {OLLAMA_BASE_URL}/api/tags` → populate the dropdown with models actually installed.
  For OpenAI, a curated known list (`gpt-4o`, `gpt-4o-mini`, …) + free-text. For Cloud,
  `OLLAMA_CLOUD_MODEL`.
- **Embedding switch guardrail:** switching `EMBEDDING_PROVIDER` changes vector dimension
  (local MiniLM 384 ↔ OpenAI 1536) → **existing Qdrant collections become unusable and
  must be re-indexed.** The panel must warn loudly and link the reindex step. This is a
  real footgun the raw `.env` editor hides today.
- **Where:** `config-panel/html/{index.html,app.js,style.css}`; `orchestrator/main.py`;
  `orchestrator/services/admin_config.py`.
- **Design decision (stated, not asked):** `.env`-write + guided restart. Reuses the
  existing restart notice. **No hot-swap in v1** (see §0).
- **Trap:** don't build a per-agent model override matrix or a "model router" UI. One
  provider + one model + one fast-model + embedding provider. That's what the code reads.

**A2 — Live feeds panel** (`input/feeds.yaml`). Typed form for `rest_poll` (weather/tariff)
and `csv_drop` sources. Reuses the `FeedRegistry` that already loads this file.
**Trap:** don't invent new adapter types in the UI — expose only the adapters that exist.

**A3 — Notification channels panel** (`input/channels.yaml`). Form for `log` / `webhook` /
`smtp` + a "send test" button routing through `services/notification_service.py`.
**Trap:** don't build a full alert-rule editor here — `rules.yaml` (ECA) is a separate,
bigger surface; link to it, don't inline it in v1.

### B. Dockerized dummy external DB (your "dummy datasources to connect")

- **B1:** add a `dummy-mysql` service to `docker-compose.yml` **behind a compose profile**
  (`--profile demo`) so it never runs in a normal/prod stack. Seed it on first boot from
  the existing `mysql-dummy-publish-dev/` harness (`sensor_uuids.json` +
  `mysql_dummy_publisher.py`).
- **B2:** "Load demo database" button in the Databases tab → pre-fills the Add-connection
  form (host `dummy-mysql`, port, seeded creds) → Test → Add. Then a matching seed TTL/CSV
  so "Register sensors" is one paste. Turns a manual multi-field flow into a 2-click demo.
- **B3:** document the rehearsal in the Guide tab (C1).
- **Trap:** never auto-connect it or seed it into the main stack. Opt-in profile + explicit
  button only — otherwise it pollutes real deployments and muddies provenance.

### C. Guide / How-to (your "how-to section")

- **C1:** a **Guide** tab. Static content (no backend), sections: *What each tab does* ·
  *The two halves of a data source* (SPARQL finds sensor+UUID+`storedAt` → SQL routes to
  DB) · *Connect an external DB* · *Switch the AI model* · *Roles & access* · *Reset for a
  clean demo*. Keep it in one `guide.html` fragment or a JS-rendered markdown blob.
- **C2:** small "?" popovers per tab header (progressive disclosure).
- **C3 (nice-to-have):** a scripted "demo tour" that highlights each step of the §0
  narrative. Mark optional — don't block Tier 1 on it.
- **Trap:** no tutorial-engine / LMS. Static content + popovers is the whole scope.

### D. UX / polish / professionalism

- **D1:** consistent toasts, loading/empty/error states, focus management, light+dark
  theme parity. Audit `style.css` for the gaps.
- **D2:** Data Sources cards show **row count + last-regenerated timestamp + clearer
  enabled state + a per-card "unlocks" line**. Backend already returns most of this.
- **D3:** Health tab: per-service latency, circuit-breaker state (already in `/health`
  payload — see the Task-3 smoke output), colored status dots, auto-refresh toggle.
- **D4 (= G1):** Overview landing tab (Tier 1).

### E. Logic / capabilities / advanced controls

- **E1 (Tier 1):** multi-select bulk enable/disable + **"Reset to demo state"** (disable
  all synthetic sources, flush `resp_cache:*`). This is the idempotent reset my
  `scripts/test_datasource_capability_qa.py` performs by hand — promote it to a button.
- **E2 (Tier 1):** **Query tester.** Thin: a text box → `POST /chat` → render
  `data.response` + `data.sources[]` as provenance chips + `route_decision.final_node`.
  Reuses everything. The single highest demo-value build because it shows toggle→unlock
  live. **Trap:** keep it thin — it is *not* a second OpenWebUI. No history, no streaming,
  no persona picker in v1; just ask → answer → provenance.
- **E3 (Tier 3):** persisted provenance view.

### F. Production-aware (design now, mostly build later)

- **F1 (Tier 1, do now):** add `Depends(require_permission(...))` to the two currently
  unauthenticated datasource endpoints. You're expanding a console; open admin reads are
  reckless. ~1 line each.
- **F3 (Tier 3, batch):** the remaining review findings (env newline injection, `is_secret`
  scope, mask-sentinel exact-equality, `readonly:'*'`, `STRICT_SECRETS` ∌ `SECRET_KEY`).
- **F2/F4:** audit log + config backup/restore when this leaves the demo context.

---

## 2b. Phase 1 — deferred adjustments (revisit before commit)

These are known open items from the Phase-1 build. Parked deliberately; not blockers for Phase 2.

- **F1 decision to confirm.** I did NOT gate `GET /api/v1/datasources` / `preview` behind auth —
  the SPA reads both anonymously for its read-only landing view and neither leaks a secret. I clamped
  `preview`'s `limit` (≤500) to kill the only real issue (unauthenticated unbounded generation). If we
  decide the anonymous landing view isn't worth keeping, revisit and gate them.
- **`main.py` formatting churn.** I ran `black` on the whole file; because this branch has large
  uncommitted P0-hardening work that wasn't black-clean, the run normalized pre-existing lines and
  inflated the diff. My feature code is only at the datasource/ai-config endpoint regions. **At commit
  time:** land the P0 work + features first, then run `black` as a separate formatting-only commit so
  review stays clean.
- **Admin-role bootstrap.** Default `admin`/`admin123` is role `facility_manager` and cannot reach the
  `system:admin` tabs (.env / Databases / AI & Models). For the demo, seed a real `admin`-role account
  (e.g. `create_admin.py`) or promote one. Consider documenting this in the Guide tab.
- **Browser click-through.** Phase-1 was verified at the API contract level + static-asset serving; a
  manual browser pass of each new tab is still worth doing before the demo.

## 3. Recommended build sequence

- **Phase 1 (demo-ready):** F1 (auth fix) → G1 (Overview) → E1 (bulk + reset) → E2 (query
  tester) → A1 (AI & Models) → C1 (Guide). This alone makes the §0 narrative work.
- **Phase 2 (depth):** B1–B3 (dummy DB) → A2/A3 (feeds/channels) → D2/D3 (card + health
  polish) → C2 (popovers).
- **Phase 3 (pre-prod):** F3 (batch security) → F2 (audit log) → F4 (backup/restore) → E3.
- **Phase 4 (post-console, architectural):** TTL-native capabilities + guided triple GUI
  — move capabilities from the Qdrant KB into the ontology as SPARQL-answerable triples,
  add a guided capability-triple editor, and collapse the two competing routers into one
  SPARQL-first path. Fixes the "wrongly routes to `capability`" problem at the root.
  Full plan: **[tasks/TTL_NATIVE_CAPABILITIES_PLAN.md](./TTL_NATIVE_CAPABILITIES_PLAN.md)**.

Each phase is independently shippable and leaves the console in a working state.

## 4. Explicit non-goals (the traps, collected)

- **No live model hot-swap** — `.env` + restart (boot-time validation makes hot-swap a
  rabbit hole).
- **No per-agent model matrix / model router UI** — the code reads one provider+model.
- **No auto-connected dummy DB** — profile-gated, opt-in only.
- **No second chat app** — the query tester stays thin.
- **No tutorial engine, SSO, multi-tenant, or plugin marketplace** in this effort.
- **Don't inline the ECA `rules.yaml` editor** into the channels panel — separate surface.

## 5. Open risks / things to verify before Phase 1

- Confirm `capabilities.json` is meant to stay static (Task-1 known-limitation says yes);
  the Overview/Guide tabs should read from live endpoints, not re-hardcode it.
- The AI-config test probe must **never echo the key back**; return booleans/labels only.
- "Reset to demo state" must define *demo state* explicitly (which sources on/off) or it
  becomes non-deterministic — store the intended demo baseline in one place.
