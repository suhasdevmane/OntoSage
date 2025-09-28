import json
from datetime import datetime, timedelta
from urllib import request

BASE_URL = "http://localhost:6001/analytics/run"


def ts(n):
    # produce ISO-like timestamps spaced by minutes
    return (datetime(2025, 2, 10, 5, 30) + timedelta(minutes=n)).strftime("%Y-%m-%d %H:%M:%S")


def payload_standard():
    # Nested payload with a variety of sensors
    return {
        "1": {
            "Air_Temperature_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 22.5},
                    {"datetime": ts(1), "reading_value": 22.7},
                    {"datetime": ts(2), "reading_value": 23.1},
                ]
            },
            "Zone_Air_Humidity_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 45},
                    {"datetime": ts(1), "reading_value": 46},
                    {"datetime": ts(2), "reading_value": 47},
                ]
            },
            "CO2_Level_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 900},
                    {"datetime": ts(1), "reading_value": 980},
                    {"datetime": ts(2), "reading_value": 1020},
                ]
            },
            "PM2.5_Level_Sensor_Standard": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 22},
                    {"datetime": ts(1), "reading_value": 28},
                    {"datetime": ts(2), "reading_value": 31},
                ]
            },
            "PM10_Level_Sensor_Standard": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 40},
                    {"datetime": ts(1), "reading_value": 45},
                    {"datetime": ts(2), "reading_value": 48},
                ]
            },
            "Air_Quality_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 55},
                    {"datetime": ts(1), "reading_value": 60},
                    {"datetime": ts(2), "reading_value": 58},
                ]
            },
            "Static_Pressure_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 1.1},
                    {"datetime": ts(1), "reading_value": 1.2},
                    {"datetime": ts(2), "reading_value": 1.3},
                ]
            },
            "Sound_Noise_Sensor_MEMS": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 50},
                    {"datetime": ts(1), "reading_value": 56},
                    {"datetime": ts(2), "reading_value": 53},
                ]
            },
            "Formaldehyde_Level_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 0.08},
                    {"datetime": ts(1), "reading_value": 0.09},
                    {"datetime": ts(2), "reading_value": 0.11},
                ]
            },
            "Supply_Air_Temperature_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 19.0},
                    {"datetime": ts(1), "reading_value": 19.5},
                    {"datetime": ts(2), "reading_value": 20.0},
                ]
            },
            "Return_Air_Temperature_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 22.0},
                    {"datetime": ts(1), "reading_value": 22.2},
                    {"datetime": ts(2), "reading_value": 22.1},
                ]
            },
            "Air_Flow_Rate_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 100},
                    {"datetime": ts(1), "reading_value": 105},
                    {"datetime": ts(2), "reading_value": 98},
                ]
            },
            "HVAC_Main_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 10},
                    {"datetime": ts(1), "reading_value": 11},
                    {"datetime": ts(2), "reading_value": 50},  # outlier
                ]
            },
        },
        "2": {
            "Air_Temperature_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 21.0},
                    {"datetime": ts(1), "reading_value": 20.5},
                    {"datetime": ts(2), "reading_value": 21.2},
                ]
            },
            "Zone_Air_Humidity_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 42},
                    {"datetime": ts(1), "reading_value": 41},
                    {"datetime": ts(2), "reading_value": 43},
                ]
            },
            "CO2_Level_Sensor": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 850},
                    {"datetime": ts(1), "reading_value": 900},
                    {"datetime": ts(2), "reading_value": 950},
                ]
            },
            "PM2.5_Level_Sensor_Standard": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 18},
                    {"datetime": ts(1), "reading_value": 20},
                    {"datetime": ts(2), "reading_value": 19},
                ]
            },
            "PM10_Level_Sensor_Standard": {
                "timeseries_data": [
                    {"datetime": ts(0), "reading_value": 35},
                    {"datetime": ts(1), "reading_value": 38},
                    {"datetime": ts(2), "reading_value": 36},
                ]
            },
        },
    }


ANALYSES = [
    "analyze_recalibration_frequency",  # will adapt payload for flat form
    "analyze_failure_trends",
    "analyze_device_deviation",        # will adapt payload for flat form
    "analyze_sensor_status",
    "analyze_air_quality_trends",
    "analyze_hvac_anomalies",
    "analyze_supply_return_temp_difference",
    "analyze_air_flow_variation",
    "analyze_sensor_trend",
    "aggregate_sensor_data",
    "correlate_sensors",
    "compute_air_quality_index",
    "generate_health_alerts",
    "detect_anomalies",
    "analyze_noise_levels",
    "analyze_air_quality",
    "analyze_formaldehyde_levels",
    "analyze_co2_levels",
    "analyze_pm_levels",
    "analyze_temperatures",
    "analyze_humidity",
    "analyze_temperature_humidity",
    "detect_potential_failures",
    "forecast_downtimes",
]


def post_json(url, body):
    data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_flat(series):
    # Convert nested standard payload to flat for the functions that expect it in examples
    flat = {}
    for _, inner in series.items():
        for k, v in inner.items():
            if isinstance(v, dict):
                flat.setdefault(k, []).extend(v.get("timeseries_data", []))
    return flat


def main():
    nested = payload_standard()
    flat_subset = to_flat(nested)

    # Prepare special payloads for the flat-only style functions
    flat_recal = {k: v for k, v in list(flat_subset.items())[:2]}
    flat_device_dev = {k: v for k, v in list(flat_subset.items())[:2]}

    results = {}
    for analysis in ANALYSES:
        body = {"analysis_type": analysis}
        if analysis in ("analyze_recalibration_frequency", "analyze_device_deviation"):
            body.update(flat_recal if analysis == "analyze_recalibration_frequency" else flat_device_dev)
        else:
            body.update(nested)

        try:
            resp = post_json(BASE_URL, body)
            ok = isinstance(resp, dict) and "results" in resp and not (isinstance(resp["results"], dict) and resp["results"].get("error"))
            results[analysis] = {"ok": ok, "sample": resp.get("results")}
            print(f"{analysis}: {'OK' if ok else 'ERROR'}")
        except Exception as e:
            results[analysis] = {"ok": False, "error": str(e)}
            print(f"{analysis}: EXCEPTION {e}")

    # Summary
    passed = sum(1 for v in results.values() if v.get("ok"))
    total = len(results)
    print(f"\nSummary: {passed}/{total} analyses returned OK responses.")
    for name, info in results.items():
        if not info.get("ok"):
            print(f" - {name}: FAILED -> {info.get('error') or info.get('sample')}")


if __name__ == "__main__":
    main()
