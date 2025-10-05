# Analytics Microservices (Flask)

Analytics endpoints for time-series sensor payloads used by the Rasa Action Server and other clients.

## Run

- With Docker (recommended): service `microservices` in a building compose file (e.g. `docker-compose.bldg1.yml` or `docker-compose.bldg2.yml`).
  - Typical host: http://localhost:6001 (host → container 6000)
  - Alternate (some bldg3 variants or isolation strategy): http://localhost:6002
  - Health: GET `/health`
  - Runner: POST `/analytics/run`
  - See root `README.md` for port matrix and isolation guidance.

## API

- POST `/analytics/run`
  - Body:
    - `analysis_type` (string, required)
    - Sensor data: either flat or nested payload
      - Flat: `{ sensorName: [ {timestamp|datetime, reading_value}, ... ] }`
      - Nested: `{ groupId: { innerKey: { timeseries_data: [ {datetime, reading_value}, ... ] } } }`
    - Optional params per analysis (e.g., `acceptable_range`, `thresholds`, `method`)
  - Returns: `{ analysis_type, timestamp, results }`

Example request (nested):

```json
{
  "analysis_type": "analyze_temperatures",
  "1": {
    "Air_Temperature_Sensor": {
      "timeseries_data": [
        {"datetime": "2025-02-10 05:31:59", "reading_value": 22.5},
        {"datetime": "2025-02-10 05:33:00", "reading_value": 23.0}
      ]
    }
  }
}
```

## Available analyses (selection)

- Environmental: `analyze_temperatures`, `analyze_humidity`, `analyze_co2_levels`, `analyze_pm_levels`, `analyze_noise_levels`, `analyze_formaldehyde_levels`, `analyze_air_quality`, `compute_air_quality_index`
- HVAC/air: `analyze_supply_return_temp_difference`, `analyze_air_flow_variation`, `analyze_pressure_trend`, `analyze_air_quality_trends`, `analyze_hvac_anomalies`
- Generic: `correlate_sensors`, `aggregate_sensor_data`, `analyze_sensor_trend`, `detect_anomalies`, `detect_potential_failures`, `forecast_downtimes`
- Ops: `analyze_device_deviation`, `analyze_failure_trends`, `analyze_recalibration_frequency`

Notes:
- All functions accept flat or nested payloads and normalize timestamps.
- Results include human units and UK indoor defaults (where applicable): °C, %RH, ppm, µg/m³, etc.
- Anomaly detection supports `method: zscore` or `iqr` (robust).

## UK defaults and units

Embedded UK-oriented guidelines include:

- Temperature: 18–24 °C; Humidity: 40–60 %RH
- CO2: good 400–1000 ppm; max 1500 ppm
- PM2.5: 35 µg/m³; PM10: 50 µg/m³
- Formaldehyde (HCHO): 0.1 mg/m³; Noise: ~55 dB(A)

You can override thresholds/ranges in the request. Responses include `unit`, `acceptable_range`, or `acceptable_max` metadata where relevant.

## Integration

- Action Server calls this service via internal URL `http://microservices:6000/analytics/run` (see `rasa-ui/actions`).
- Decider Service optionally selects which `analysis_type` to run for a user question.

## Customize for your building

- Sensor naming: key detection is robust (e.g., matches "temperature" and "temp" while avoiding "attempt"). Prefer human-readable names in payloads.
- Thresholds: pass `acceptable_range` or `thresholds` per request to tailor to building standards.
- New analyses: add a new function in `blueprints/analytics_service.py` and register it in the analysis registry used by `/analytics/run`.

## Testing

- Health: open http://localhost:6001/health
- Smoke test: `python microservices/test_analytics_smoke.py` — exercises all registered analyses with dummy data and prints a summary.
