# Building 2 - Synthetic Office Building

**Rasa Conversational AI Stack for Building 2**

[![Rasa](https://img.shields.io/badge/Rasa-3.6.12-5A17EE?logo=rasa)](https://rasa.com/)
[![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Required-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

This directory contains the Rasa Open Source conversational AI stack specifically configured for **Building 2**, a synthetic commercial office building designed to validate HVAC optimization, AHU (Air Handling Unit) monitoring, and zone-based thermal comfort control.

## 🏢 Building Overview

| Property | Details |
|----------|---------|
| **Building Type** | Synthetic Commercial Office |
| **Purpose** | HVAC Optimization & Thermal Comfort Research |
| **Sensor Coverage** | 329 sensors (15 AHUs, 50 zones, 3 chillers, 2 boilers) |
| **Focus Area** | AHU process variables & zone thermal comfort |
| **Database** | TimescaleDB (PostgreSQL with time-series extension, port 5433) |
| **Knowledge Graph** | Brick Schema 1.4 via Jena Fuseki (port 3030) |
| **Compose File** | `docker-compose.bldg2.yml` (from repo root) |

### Sensor Distribution

**By System:**
- **AHU Systems**: 15 units with supply/return temperatures, flow rates, pressures
- **Zones**: 50 zones with temperature sensors, setpoints, occupancy
- **Chillers**: 3 units with chilled water monitoring
- **Boilers**: 2 units with hot water supply/return
- **Total Sensors**: 329

**By Measurement Type:**
- Temperature Sensors: 120
- Pressure Sensors: 45
- Flow Rate Sensors: 35
- Status Indicators: 89
- Occupancy Sensors: 40

### Naming Convention

Structured, hierarchical naming for easy querying:

```
AHU_01_Supply_Air_Temp_Sensor
AHU_01_Return_Air_Temp_Sensor
AHU_01_Chilled_Water_Supply_Temp
Zone_101_Temp_Sensor
Zone_101_Temp_Setpoint
Zone_102_Occupancy_Sensor
Chiller_01_Supply_Water_Temp
Boiler_01_Hot_Water_Return_Temp
```

## 🚀 Services

This stack includes six integrated services:

| Service | Port | Purpose | Health Endpoint |
|---------|------|---------|-----------------|
| **Rasa Core** | 5005 | NLU/Dialogue engine | `GET /version` |
| **Action Server** | 5055 | Custom actions & integrations | `GET /health` |
| **Duckling** | 8000 | Entity extraction (dates, times) | `GET /` |
| **File Server** | 8080 | Artifact hosting (charts, CSV) | `GET /health` |
| **Rasa Editor** | 6080 | Web-based NLU editor | `GET /health` |
| **Frontend UI** | 3000 | React chat interface | N/A |

### Service Architecture

```
User Query → Frontend (3000)
    ↓
Rasa Core (5005) → NLU Processing
    ↓
Action Server (5055)
    ├── TimescaleDB (5433) - Time-series Telemetry
    ├── Fuseki (3030) - Knowledge Graph (SPARQL)
    ├── Analytics (6001) - HVAC Analysis
    ├── Decider (6009) - Query Classification
    └── NL2SPARQL (6005) - Query Translation
    ↓
File Server (8080) ← Generated Artifacts
    ↓
Frontend (3000) ← Rich Response + Media
```

## 📦 Installation

### Prerequisites

- Docker Desktop 20.10+
- Docker Compose 2.0+
- 8GB RAM minimum (16GB recommended)
- 20GB free disk space

### Quick Start

```powershell
# From repository root
cd c:\Users\suhas\Documents\GitHub\OntoBot

# Start Building 2 stack
docker-compose -f docker-compose.bldg2.yml up -d --build

# Wait for services to be healthy (~2-3 minutes)
Start-Sleep -Seconds 180

# Verify services
docker-compose -f docker-compose.bldg2.yml ps
```

### Access Points

- **Frontend**: http://localhost:3000
- **Rasa Core**: http://localhost:5005/version
- **Action Server**: http://localhost:5055/health
- **File Server**: http://localhost:8080/health
- **Editor**: http://localhost:6080
- **pgAdmin**: http://localhost:5050 (TimescaleDB management)
- **ThingsBoard**: http://localhost:8082 (IoT platform)

## ⚙️ Configuration

### Environment Variables

Action Server configuration (set in `docker-compose.bldg2.yml`):

```yaml
environment:
  # Building Identifier
  BUILDING_ID: bldg2
  
  # File Server
  BASE_URL: http://localhost:8080
  BUNDLE_MEDIA: "true"
  
  # TimescaleDB (PostgreSQL)
  DB_HOST: timescaledb
  DB_NAME: building2_telemetry
  DB_USER: thingsboard
  DB_PASSWORD: thingsboard
  DB_PORT: 5432
  DB_TYPE: timescale
  
  # Service Integrations
  ANALYTICS_URL: http://microservices:6000/analytics/run
  DECIDER_URL: http://decider-service:6009/decide
  NL2SPARQL_URL: http://nl2sparql:6005/predict
  FUSEKI_URL: http://fuseki:3030/building2/query
  
  # Feature Flags
  ENABLE_ANALYTICS: "true"
  ENABLE_HVAC_OPTIMIZATION: "true"
```

### TimescaleDB Benefits

- **Fast Time-Series Queries**: Optimized for temporal data
- **Automatic Compression**: Reduces storage by 90%+
- **Retention Policies**: Auto-delete old data
- **SQL Compatible**: Standard PostgreSQL syntax
- **Continuous Aggregates**: Pre-computed rollups

## 💬 Usage

### Example Queries

**AHU Queries:**
```
What's the supply air temperature for AHU 01?
Show me AHU 05 return air temperature trends
Compare supply and return temperatures for AHU 03
Is AHU 10 operating efficiently?
```

**Zone Thermal Comfort:**
```
What's the temperature in Zone 101?
Show me Zone 205 temperature over the last day
Compare actual vs setpoint temperature in Zone 150
Which zones are too hot?
```

**Chiller Queries:**
```
What's the chilled water supply temperature for Chiller 01?
Show me chiller performance trends
Compare efficiency across all chillers
```

**Optimization Queries:**
```
Detect AHU supply/return temperature anomalies
Analyze zone temperature deviation from setpoints
Forecast cooling demand for the next 4 hours
Show correlation between occupancy and temperature
```

**HVAC Process Variables:**
```
What's the air flow rate for AHU 02?
Show me pressure trends across all AHUs
Analyze filter status indicators
Detect potential AHU failures
```

### Response Format

The bot returns structured responses with:
- **Text**: Human-readable answer with units
- **Data**: Numerical values (°C, cfm, psi, %)
- **Visualizations**: HVAC-specific charts
- **Recommendations**: Energy optimization suggestions
- **Alerts**: Out-of-range warnings

## 🔧 Development

### Project Structure

```
rasa-bldg2/
├── actions/
│   ├── actions.py           # Custom action logic for Building 2
│   ├── sensor_list.txt      # 329 office building sensors
│   ├── sensor_uuids.txt     # UUID mappings
│   └── requirements.txt     # Action dependencies
├── data/
│   ├── nlu.yml              # NLU training examples (AHU/Zone focused)
│   ├── rules.yml            # Conversation rules
│   └── stories.yml          # Dialogue stories
├── models/                  # Trained Rasa models
├── shared_data/
│   └── artifacts/           # Generated charts/CSV
├── config.yml               # Pipeline configuration
├── domain.yml               # Intents, entities, slots
├── endpoints.yml            # Service endpoints
└── credentials.yml          # Channel credentials
```

### Training a New Model

```powershell
# Using Docker Compose
docker-compose -f docker-compose.bldg2.yml run --rm rasa_bldg2 train

# Models are saved to ./models/
# Training focuses on AHU/Zone vocabulary
```

### Testing Locally

```powershell
# Test NLU only
docker-compose -f docker-compose.bldg2.yml run --rm rasa_bldg2 shell nlu

# Interactive chat
docker-compose -f docker-compose.bldg2.yml run --rm rasa_bldg2 shell

# REST API test
Invoke-RestMethod -Method Post -Uri http://localhost:5005/webhooks/rest/webhook `
  -ContentType "application/json" `
  -Body (@{sender="test"; message="What's AHU 01 supply temp?"} | ConvertTo-Json)
```

## 🏗️ Building-Specific Features

### HVAC-Focused Analytics

**Supply/Return Temperature Difference:**
```json
{
  "analysis_type": "analyze_supply_return_temp_difference",
  "ahu_id": "AHU_01",
  "acceptable_range": [10, 20]
}
```

**Zone Setpoint Deviation:**
```json
{
  "analysis_type": "analyze_zone_temperature_deviation",
  "zone_id": "Zone_101",
  "setpoint": 22,
  "tolerance": 2
}
```

**HVAC Anomaly Detection:**
```json
{
  "analysis_type": "analyze_hvac_anomalies",
  "equipment_type": "AHU",
  "method": "isolation_forest"
}
```

### TimescaleDB Queries

**Time-Bucketed Averages:**
```sql
SELECT 
  time_bucket('1 hour', ts) AS hour,
  sensor_name,
  AVG(value) as avg_value
FROM sensor_timeseries
WHERE sensor_name = 'AHU_01_Supply_Air_Temp_Sensor'
  AND ts > NOW() - INTERVAL '24 hours'
GROUP BY hour, sensor_name
ORDER BY hour;
```

**Continuous Aggregates (Pre-computed):**
```sql
-- Created automatically
CREATE MATERIALIZED VIEW hourly_ahu_temps
WITH (timescaledb.continuous) AS
SELECT 
  time_bucket('1 hour', ts) AS bucket,
  sensor_name,
  AVG(value) as avg,
  MAX(value) as max,
  MIN(value) as min
FROM sensor_timeseries
WHERE sensor_name LIKE 'AHU_%Temp%'
GROUP BY bucket, sensor_name;
```

**Retention Policy:**
```sql
-- Auto-delete data older than 90 days
SELECT add_retention_policy('sensor_timeseries', INTERVAL '90 days');
```

### Brick Schema (Building 2)

The Brick 1.4 ontology includes:
- 15 AHU equipment instances
- 50 zone instances
- 3 chiller instances
- 2 boiler instances
- Relationships (feeds, controls, monitors)

**Example SPARQL Query:**
```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?ahu ?sensor WHERE {
  ?ahu a brick:AHU .
  ?sensor brick:isPointOf ?ahu .
  ?sensor a brick:Supply_Air_Temperature_Sensor .
}
```

## 📊 HVAC Optimization

### Energy Efficiency Metrics

**Chiller Efficiency:**
- kW/Ton calculations
- COP (Coefficient of Performance)
- Delta-T analysis

**AHU Efficiency:**
- Supply/Return temperature differential
- Fan energy consumption
- Filter pressure drop

**Zone Comfort:**
- PMV (Predicted Mean Vote)
- PPD (Percentage People Dissatisfied)
- Temperature setpoint adherence

### Predictive Maintenance

**Equipment Failure Prediction:**
```json
{
  "analysis_type": "detect_potential_failures",
  "equipment_id": "AHU_05",
  "forecast_hours": 48
}
```

**Filter Replacement Scheduling:**
```json
{
  "analysis_type": "analyze_filter_status",
  "ahu_id": "AHU_01",
  "pressure_threshold": 1.5
}
```

## 🔍 Troubleshooting

### Common Issues

**1. TimescaleDB Connection Errors**
```powershell
# Check TimescaleDB is running
docker-compose -f docker-compose.bldg2.yml ps timescaledb

# Verify from action server
docker-compose -f docker-compose.bldg2.yml exec action_server_bldg2 \
  psql -h timescaledb -U thingsboard -d building2_telemetry -c "SELECT 1;"
```

**2. pgAdmin Can't Connect**
```powershell
# Verify servers.json is mounted
docker-compose -f docker-compose.bldg2.yml exec pgadmin ls /pgadmin4/servers.json

# Login: pgadmin@example.com / admin
# Server should auto-configure with Building 2 credentials
```

**3. Slow Time-Series Queries**
```sql
-- Create indexes
CREATE INDEX idx_sensor_ts ON sensor_timeseries (sensor_name, ts DESC);

-- Use continuous aggregates for frequent queries
-- Enable compression for old data
SELECT add_compression_policy('sensor_timeseries', INTERVAL '7 days');
```

## 🧪 Testing

### Health Checks

```powershell
# Check all services
curl http://localhost:5005/version        # Rasa
curl http://localhost:5055/health         # Actions
curl http://localhost:8080/health         # File Server

# Test TimescaleDB
docker-compose -f docker-compose.bldg2.yml exec timescaledb \
  psql -U thingsboard -d building2_telemetry -c "\dx"
# Should show timescaledb extension
```

### End-to-End HVAC Test

```powershell
# Test AHU query
$response = Invoke-RestMethod -Method Post `
  -Uri http://localhost:5005/webhooks/rest/webhook `
  -ContentType "application/json" `
  -Body (@{
    sender = "test_user"
    message = "What's the supply air temperature for AHU 01?"
  } | ConvertTo-Json)

Write-Output $response
# Should return temperature with °C unit
```

## 📖 References

- **Rasa Documentation**: https://rasa.com/docs/rasa/
- **Brick Schema 1.4**: https://ontology.brickschema.org/
- **TimescaleDB**: https://docs.timescale.com/
- **HVAC Optimization**: ASHRAE Standards
- **OntoBot Main README**: [../README.md](../README.md)
- **Multi-Building Support**: [../MULTI_BUILDING_SUPPORT.md](../MULTI_BUILDING_SUPPORT.md)

## 🆘 Support

For issues specific to Building 2 (Office):
- Check logs: `docker-compose -f docker-compose.bldg2.yml logs`
- Review main README: [../README.md](../README.md)
- TimescaleDB docs: https://docs.timescale.com/

## 📄 License

This project is part of OntoBot. See [../LICENSE](../LICENSE) for details.

---

**Next Steps:**
- [Building 1 (ABACWS)](../rasa-bldg1/README.md) - Real University Testbed (680 sensors)
- [Building 3 (Data Center)](../rasa-bldg3/README.md) - Synthetic Data Center (597 sensors)
- [Frontend Documentation](../suhasdevmane.github.io/_docs/frontend_ui.md)
- [API Reference](../suhasdevmane.github.io/_docs/api_reference.md)
