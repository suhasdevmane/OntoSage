# Analytics Function GUI: Risk & Mitigation Overview

This document catalogs key risks introduced by enabling dynamic, user-authored analytics functions through the web UI, and prescribes mitigations and future hardening steps.

## 1. Code Execution & Sandbox
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Arbitrary Python execution | User can inject harmful code (infinite loops, resource abuse) | AST gate blocks forbidden imports (os, subprocess, socket, sys, shutil, pathlib, builtins, importlib) + blocks exec/eval/open | Add timeout-executed worker (e.g. separate process with `multiprocessing`), CPU & memory limits (cgroups / container), deny attribute access via AST walk (e.g. `__class__`, dunder names). |
| Resource exhaustion (loop, large allocations) | Function consumes CPU/RAM | None beyond normal server limits | Execute in isolated short‑lived worker container or process with RLIMIT, enforce max runtime (e.g. 3s) and kill on timeout. |
| Data exfiltration | Plugin reads filesystem or env secrets | Limited only by import ban (still can use builtins indirectly) | Strict allowlist: only expose curated helper API object; run in chrooted / readonly container; remove direct global namespace exposure. |

## 2. Integrity & Versioning
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Overwrite / shadow existing function | New function name collides | Backend rejects if name exists | Add semantic version: `name@vN`; keep history list; allow rollback. |
| Silent regression | User edits function logic by overwriting file manually | None | Maintain hash + created_at + optional checksum; warn if file hash diverges from stored metadata. |
| Lost provenance | No audit of who created which function | Timestamp only | Add creator identity (user id), optional change log table / JSON lines append file. |

## 3. Security & Access Control
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Unauthorized function creation | Any consumer of endpoint may create | None (no auth shown) | Require auth token / session & RBAC: roles: viewer / creator / admin. |
| Enumeration / reconnaissance | Listing reveals internal patterns | Public endpoint | Gate `/analytics/functions` behind auth; provide redacted view for low-priv roles. |
| Pattern injection | Malicious regex DoS (catastrophic backtracking) | None | Pre-compile with timeout; reject patterns exceeding length / containing nested catastrophic constructs (e.g. `(a+)+`). |

## 4. Stability & Operational
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Plugin load crash | Syntax error stops some loads | Try/except logs error | Isolate each plugin load & store status; surface to UI (healthy vs failed). |
| Decider staleness | Patterns not recognized until reload | Auto reload after add | Add explicit version / ETag in `/decider/reload`; client can poll version drift. |
| Unbounded growth | Too many functions degrade performance | None | Cap active functions, LRU retire, or require review status before activation. |

## 5. Data Quality & Semantics
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Inconsistent parameter semantics | Free-form types/descriptions | Stored schema fields | Enforce primitive type enum (int, float, str, bool, list, dict); validate defaults convert. |
| Misleading descriptions / hallucinated claims | User-supplied text | None | Add moderation / length limit; optionally run lint / policy checks. |

## 6. Observability & Monitoring
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Hard to debug runtime errors | Trace printed only in server logs | Basic error JSON | Capture structured execution log (start/end/error, runtime ms) per invocation; expose `/analytics/health` summarizing counts. |
| Silent performance degradation | Slow functions accumulate | None | Measure median / p95 runtime; display in UI; optionally disable functions exceeding threshold. |

## 7. Testing & Validation
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| Inadequate functional correctness | Only ad hoc test run | Test endpoint | Add optional unit test snippets stored per function; run pre-activation tests; compute coverage of helper paths. |
| Schema drift | Parameters changed but old calls cached | Fresh call every time | Maintain parameter signature version; reject calls referencing obsolete param names. |

## 8. Dependency & Supply Chain
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| User attempts import of third-party libs | Forbidden for some stdlib only | AST ban for specified modules | Strict allowlist of permitted modules (`math`, `statistics`, `numpy`, `pandas` if preinstalled). Reject any other import. |
| Hidden dynamic import via `__import__` | Banned explicitly | Present | Also ban attribute access invoking importlib via AST pattern; sandbox builtins dict. |

## 9. UX / Human Factors
| Risk | Description | Current Mitigation | Recommended Hardening |
|------|-------------|--------------------|-----------------------|
| User confusion on payload format | Minimal hint text | Example JSON placeholder | Add inline schema + link to docs + sample generator button. |
| Regex complexity errors | Hard to craft correct patterns | None | Provide pattern tester UI calling `/decider/decide` with hypothetical question and highlighting matches. |

## 10. Future Extensions (Backlog)
- Pattern tester: simulate NL queries, show matched function, highlight regex hits.
- Parameter type enforcement & runtime coercion.
- Function disable / soft-delete flag.
- Versioned functions and rollback UI.
- Execution sandbox (per-function micro-process with timeout & memory cap).
- Telemetry: invocation counts, error rates, runtime percentiles.
- Bulk export/import of analytics function definitions (JSON or YAML).
- Lint pass: check for large loops / high cyclomatic complexity.

## Immediate Action Priorities
1. Add auth / basic token gating (High)
2. Regex safety validator (High)
3. Timeout + runtime measurement (Medium)
4. Function disable flag & health status (Medium)
5. Pattern tester UI (Medium)
6. Role-based separation for create vs view (Medium)

## JSON Metadata Example
```json
{
  "function_name": {
    "description": "Mean delta between X and Y",
    "patterns": ["difference", "delta"],
    "parameters": [
      {"name": "window_hours", "type": "int", "default": 6, "description": "Rolling window length"}
    ],
    "created_at": "2025-10-07T13:05:11Z"
  }
}
```

---
Maintained by: Analytics Platform Owners
