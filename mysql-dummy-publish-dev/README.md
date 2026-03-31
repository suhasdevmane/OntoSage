# MySQL Dummy Data Publisher

## Overview
This script publishes realistic sensor data to the MySQL `sensordb.sensor_data` table every 30 seconds.

## Features
- **Realistic Data Generation**: Values are based on sensor types (temperature, humidity, CO2, etc.)
- **Type-Aware**: Respects database schema (enum, smallint, decimal, tinyint)
- **Auto-mapping**: Uses `sensor_uuids.json` and `postgresql columns.csv` to generate appropriate data
- **Debug Logging**: Prints sample data every 5 minutes

## Quick Start

### 1. Prerequisites
```bash
pip install PyMySQL
```

### 2. Run the Publisher
```bash
cd mysql-dummy-publish-dev
python mysql_dummy_publisher.py
```

The script will:
- Connect to MySQL at `localhost:3307`
- Load sensor mappings from `sensor_uuids.json`
- Load schema definitions from `postgresql columns.csv`
- Insert data every 30 seconds (configurable in SETTINGS)
- Print debug samples every 5 minutes

### 3. Configuration
Edit the `SETTINGS` dictionary in `mysql_dummy_publisher.py`:

```python
SETTINGS = {
    'HOST': 'localhost',
    'PORT': 3307,
    'USER': 'thingsboard',
    'PASSWORD': 'thingsboard',
    'DB': 'sensordb',
    'TABLE': 'sensor_data',
    'INTERVAL_SECONDS': 30,     # Time between inserts
    'BATCH_SIZE': 1,            # Number of rows per insert
    'VERBOSE': True,            # Print status messages
}
```

## Data Generation Examples

| Sensor Type | Data Type | Example Range | Example Value |
|-------------|-----------|---------------|---------------|
| Temperature | DECIMAL(6,2) | 18-28°C | 22.45 |
| Humidity | DECIMAL(6,2) | 30-70% | 55.23 |
| CO2 | DECIMAL(8,2) | 400-1200 ppm | 850.50 |
| TVOC | SMALLINT | 0-500 ppb | 125 |
| Noise/Sound | SMALLINT | 30-80 dB | 55 |
| Illuminance | SMALLINT | 0-1000 lux | 450 |
| Occupancy | TINYINT | 0 or 1 | 1 |
| Air Quality Level | ENUM | Good/Moderate/Poor | 'Good' |
| Air Quality Index | SMALLINT | 0-150 | 75 |

## Debug Output
Every 5 minutes, the script will print:
```
================================================================================
[DEBUG] Sample of last sent data:
================================================================================
Timestamp: 2025-12-16 14:30:45
Total columns: 680

Sample values (first 20):
  [ 1] Air_Quality_Level_Sensor_5.01           = 'Good'         (enum)
  [ 2] Air_Quality_Level_Sensor_5.02           = 'Moderate'     (enum)
  [ 3] Air_Temperature_Sensor_5.01             = 23.45          (decimal)
  [ 4] Zone_Air_Humidity_Sensor_5.01           = 52.30          (decimal)
  ... and 660 more columns
================================================================================
```

## Stopping the Script
Press `Ctrl+C` to gracefully stop the publisher. It will finish the current insert and then exit.

## Testing
Run the test script to verify sensor mappings:
```bash
python test_publisher.py
```

## Files
- `mysql_dummy_publisher.py` - Main publisher script
- `sensor_uuids.json` - Sensor name to UUID mapping
- `postgresql columns.csv` - Database schema definition
- `test_publisher.py` - Validation script
