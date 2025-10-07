# Analytics Microservices Design Guide

Action Plan Reference: #9 (Microservice Design Guide)  
Related Tasks: Sustainability mapping (#4), CI validation (#14)

## 1. Purpose
Defines the contract, operational expectations, versioning, and error semantics for the analytics service consumed by the Rasa Action Server and evaluation harnesses.

## 2. High-Level Flow
1. Action Server builds canonical payload (flat or nested) with `analysis_type`.
2. POST to `/analytics/run` with JSON body.
3. Service dispatches to registered function (decorated by `@analytics_function`).
4. Returns JSON containing metadata, results, optional artifacts, and warnings.
5. (Planned) Compliance/report bundling endpoint orchestrates multiple analytics.

## 3. Request Envelope Schema
```jsonc
{
  "analysis_type": "percentage_time_in_range",      // REQUIRED
  "sensor_key": "Zone_Air_Humidity_Sensor",         // OPTIONAL (single-sensor guidance)
  "1": {                                             // Nested group container(s) permissible
    "Zone_Air_Humidity_Sensor": {
      "timeseries_data": [
        { "datetime": "2025-02-10 05:31:59", "reading_value": 45.2 },
        { "datetime": "2025-02-10 05:36:59", "reading_value": 46.0 }
      ]
    }
  },
  "parameters": {                                    // OPTIONAL free-form parameter map
    "lower": 40,
    "upper": 60,
    "method": "zscore"
  }
}
```

### Supported Input Shapes
- Flat: `{ "SensorName": [ {"datetime":..., "reading_value":...}, ... ] }`
- Nested: `{ "group_id": { "SensorName": { "timeseries_data": [...] } } }`
- Mixed groups: Multiple top-level group IDs permitted.

### Normalization Rules
- Datetime: Accepts `datetime` or `timestamp`; converted with `pd.to_datetime`.
- Value Casting: Attempts float casting; preserves non-numeric where appropriate.
- Duplicate Keys: Merged (append) per sensor name during flattening.

## 4. Response Envelope Schema
```jsonc
{
  "analysis_type": "percentage_time_in_range",
  "status": "ok",                      // ok | error | partial
  "metrics": {                          // Function-specific metrics
    "Zone_Air_Humidity_Sensor": {
      "total_points": 192,
      "in_range": 180,
      "pct_in_range": 0.9375
    }
  },
  "summary": "Humidity within range for 93.8% of points",
  "warnings": ["Some series had < 5 points and were skipped"],
  "artifacts": [
    {
      "type": "plot",
      "format": "png",
      "path": "artifacts/user123/humidity_pct_range.png"
    }
  ],
  "parameters_applied": {"lower": 40, "upper": 60},
  "version": "1.2.0",
  "generated_at": "2025-10-06T10:25:22Z",
  "execution_ms": 42
}
```

## 5. Error Handling
| Condition | HTTP Code | Body.status | Body Fields |
|-----------|-----------|-------------|-------------|
| Missing `analysis_type` | 400 | error | `error_code=missing_analysis_type` |
| Unsupported type | 400 | error | `error_code=unsupported_analysis` |
| Bad payload shape | 422 | error | `error_code=payload_invalid` + `detail` |
| Internal exception | 500 | error | `error_code=internal_error` + trace (suppressed in prod) |
| Partial computation (some series invalid) | 207 | partial | `warnings` + partial metrics |

### Error Body Example
```json
{
  "status": "error",
  "error_code": "unsupported_analysis",
  "detail": "Analysis type 'thermal_pmv' not registered",
  "version": "1.2.0"
}
```

## 6. Versioning & Deprecation
- Semantic Versioning: `MAJOR.MINOR.PATCH`.
- New analytics functions increment MINOR.
- Backward-incompatible payload/response changes increment MAJOR.
- Deprecated functions flagged via registry metadata: `{ "deprecated": true, "replacement": "new_func" }`.
- `/analytics/list` includes deprecation flags and added_date for provenance.

## 7. Performance Targets
| Metric | Target (p95) | Baseline Measurement (Oct 2025) |
|--------|--------------|----------------------------------|
| Simple latest-value | < 30 ms | TBD |
| Aggregation (avg/min/max) | < 60 ms | TBD |
| Distribution (histogram) | < 75 ms | TBD |
| Correlation (n<=5 series) | < 120 ms | TBD |
| Rolling regression | < 110 ms | TBD |

> NOTE: Populate baseline using profiling harness (Action Plan #16).

## 8. Registry Metadata Contract
Each decorated function stores metadata retrievable via `/analytics/list`:
```jsonc
{
  "current_value": {
    "patterns": ["current (value|reading)", "latest (temperature|humidity|co2|value)"],
    "description": "Return latest reading per detected series",
    "deprecated": false,
    "added": "2025-09-30"
  }
}
```

## 9. Extension Guidelines
1. Implement pure function: `def new_analysis(sensor_data, **kwargs) -> dict`
2. Add decorator: `@analytics_function(patterns=[...], description="...")`
3. Return dict with at least `metrics` or `results` and optional `summary`.
4. Avoid heavy I/O; offload large model inference to separate service.
5. Guard against empty or single-point series; return warning & skip.
6. Include unit inference where relevant via `_unit_for_key`.

## 10. Parameter Handling Recommendations
| Pattern | Example | Behavior |
|---------|---------|----------|
| Numeric thresholds | `lower`, `upper` | Filter or compliance calculation |
| Window specification | `window_hours=6` | Recent slice for slope/rate |
| Method selection | `method=zscore|iqr` | Branch algorithm internally |
| Top-N rank | `n=5` | Limit ranking output |

Unrecognized parameters should be echoed under `ignored_parameters` for transparency.

## 11. Planned Endpoints (Roadmap)
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /analytics/list` | Registry metadata | Implemented |
| `POST /analytics/run` | Execute analysis | Implemented |
| `POST /analytics/bundle` | Run multi-analysis package (e.g., ASHRAE_62_1) | Planned |
| `GET /analytics/profiles` | Return standard parameter profiles | Planned |
| `GET /analytics/health` | Basic liveness / version | Implemented |

## 12. Observability
- Logging levels: INFO (summary), DEBUG (per-series detail), WARNING (data issues), ERROR (exceptions).
- Suggested log keys (JSON logger recommended): `analysis_type`, `series_count`, `execution_ms`, `correlation_id`.
- Future: Add OpenTelemetry spans around dispatch & execution.

## 13. Security & Hardening
- Reject payloads > configurable size (e.g. 5 MB) with 413.
- Enforce max series count per request (configurable, default 50) to prevent abuse.
- Sanitize any dynamically constructed file paths for artifacts.

## 14. Testing Strategy
| Test Type | Example |
|-----------|---------|
| Unit | Input shape normalization for flat vs nested |
| Unit | Percentage in range edge cases (empty, single point) |
| Property | Random synthetic series for rate_of_change monotonicity |
| Integration | Action Server end-to-end call via `/analytics/run` |
| Regression | Frozen expected metrics JSON for 10 canonical payloads |

## 15. Example Invocation (PowerShell)
```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:6001/analytics/run -ContentType 'application/json' -Body (@{
  analysis_type = 'percentage_time_in_range'
  '1' = @{ Air_Temperature_Sensor = @{ timeseries_data = @(
      @{ datetime = '2025-02-10 05:31:59'; reading_value = 22.1 },
      @{ datetime = '2025-02-10 05:33:59'; reading_value = 23.4 }
  )}}
  parameters = @{ lower = 18; upper = 24 }
} | ConvertTo-Json -Depth 6)
```

## 16. Change Log
| Date | Version | Change |
|------|---------|--------|
| 2025-10-06 | draft | Initial guide created |
