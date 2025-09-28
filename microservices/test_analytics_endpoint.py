import requests

# Change this if your Flask app is running on a different port or host
BASE_URL = "http://localhost:6000/analytics"

# Example payload for the 'analyze_recalibration_frequency' analysis
data = {
    "analysis_type": "analyze_humidity",
    "timeseriesId_1": [
        {"datetime": "2025-02-10 05:31:59", "reading_value": 27.99},
        {"datetime": "2025-02-10 06:00:00", "reading_value": 28.10},
        {"datetime": "2025-02-10 07:00:00", "reading_value": 27.95}
    ],
    "timeseriesId_2": [
        {"datetime": "2025-02-10 05:31:59", "reading_value": 30.01},
        {"datetime": "2025-02-10 06:00:00", "reading_value": 30.10},
        {"datetime": "2025-02-10 07:00:00", "reading_value": 30.05}
    ]
}

response = requests.post(f"{BASE_URL}/run", json=data)
print("Status Code:", response.status_code)
print("Response JSON:", response.json())
