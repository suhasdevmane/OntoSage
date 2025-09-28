import requests, json, time, random

DEVICE_NAME = "node_5.20"
API_BASE = "http://localhost:8090/api"
HEADERS = {"Content-Type": "application/json", "x-api-key": "V3rySecur3Pas3word"}

def generate_sensor_data():
    return {
        "uv_light": {"value": round(random.uniform(0.0, 1.0), 2), "units": "UV Index"},
        "loudness": {"value": round(random.uniform(30.0, 80.0), 1), "units": "dB"},
        "pm1.0atmospheric": {"value": round(random.uniform(5.0, 20.0), 1), "units": "µg/m³"},
        "pm2.5atmospheric": {"value": round(random.uniform(10.0, 30.0), 1), "units": "µg/m³"},
        "visible_light": {"value": random.randint(200, 600), "units": "Lux"},
        "ir_light": {"value": random.randint(200, 600), "units": "Lux"},
        "mq5_sensor_voltage": {"value": round(random.uniform(0.5, 1.0), 2), "units": "Volts"},
        "humidity": {"value": round(random.uniform(15.0, 60.0), 2), "units": "%"},
        "luminance": {"value": round(random.uniform(20.0, 50.0), 2), "units": "cd/m²"},
        "no2": {"value": random.randint(100, 300), "units": ""},
    }

def send(device_name, payload):
    url = f"{API_BASE}/devices/{device_name}/data"
    r = requests.put(url, headers=HEADERS, data=json.dumps(payload))
    try:
        r.raise_for_status()
        if r.text.strip():
            print("Response:", r.json())
        else:
            print(f"202 Accepted for {device_name}")
    except Exception as e:
        print("Error:", e, "status:", r.status_code, "body:", r.text[:200])

while True:
    data = generate_sensor_data()
    print("Sending:", json.dumps(data, indent=2))
    send(DEVICE_NAME, data)
    time.sleep(5)