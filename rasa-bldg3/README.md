# Building 3 - Synthetic Data Center

**Rasa Conversational AI Stack for Building 3**

[![Rasa](https://img.shields.io/badge/Rasa-3.6.12-5A17EE?logo=rasa)](https://rasa.com/)
[![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Required-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

This directory contains the Rasa Open Source conversational AI stack specifically configured for **Building 3 (Data Center)**, a synthetic critical infrastructure facility focused on cooling systems, power distribution, and alarm monitoring with high-availability data storage.

## 🏢 Building Overview

| Property | Details |
|----------|---------|
| **Building Type** | Synthetic Critical Infrastructure |
| **Purpose** | Data Center Operations & Monitoring |
| **Sensor Coverage** | 597 sensors across multiple zones |
| **Focus Area** | Cooling Systems, Power Distribution & Alarms |
| **Database** | Cassandra (port 9042) - Distributed NoSQL |
| **Metadata Store** | PostgreSQL (port 5434) - ThingsBoard entities |
| **Knowledge Graph** | Brick Schema 1.3 via Jena Fuseki (port 3030) |
| **Compose File** | `docker-compose.bldg3.yml` (from repo root) |

### Sensor Types & Monitoring Systems

**Critical Infrastructure Monitoring:**
- **CRAC Units** (Computer Room Air Conditioning)
  - Supply/Return Air Temperature
  - Airflow Rate & Pressure
  - Cooling Capacity & Efficiency
  - Alarm Status

- **UPS Systems** (Uninterruptible Power Supply)
  - Input/Output Voltage
  - Battery Charge Level & Health
  - Power Load & Capacity
  - Alarm Conditions

- **PDUs** (Power Distribution Units)
  - Phase Voltages (L1, L2, L3)
  - Current Draw per Phase
  - Power Factor
  - Circuit Breaker Status

- **Rack-Level Monitoring**
  - Inlet/Outlet Temperature
  - Humidity
  - Hot Aisle/Cold Aisle Temps
  - Power Consumption per Rack

- **Alarm Systems**
  - Environmental Alarms
  - Equipment Failure Alerts
  - Threshold Violations
  - Critical System Warnings

**Data Center Metrics:**
- PUE (Power Usage Effectiveness)
- DCiE (Data Center Infrastructure Efficiency)
- Cooling Load & Efficiency
- Redundancy Status

## 🚀 Services

This stack includes eight integrated services optimized for critical infrastructure:

| Service | Port | Purpose | Health Endpoint |
|---------|------|---------|-----------------|
| **Rasa Core** | 5005 | NLU/Dialogue engine | `GET /version` |
| **Action Server** | 5055 | Custom actions & integrations | `GET /health` |
| **Duckling** | 8000 | Entity extraction (dates, times) | `GET /` |
| **File Server** | 8080 | Artifact hosting (charts, CSV) | `GET /health` |
| **Rasa Editor** | 6080 | Web-based NLU editor | `GET /health` |
| **Frontend UI** | 3000 | React chat interface | N/A |
| **ThingsBoard** | 8082 | IoT platform & visualization | UI |
| **Cassandra** | 9042 | Distributed telemetry storage | CQL |

### Service Architecture

```
User Query → Frontend (3000)
    ↓
Rasa Core (5005) → NLU Processing
    ↓
Action Server (5055)
    ├── Cassandra (9042) - Telemetry Data (High Availability)
    ├── PostgreSQL (5434) - ThingsBoard Metadata
    ├── Fuseki (3030) - Knowledge Graph (SPARQL)
    ├── Analytics (6001) - Time-series Analysis
    ├── Decider (6009) - Analytics Selection
    └── NL2SPARQL (6005) - Query Translation
    ↓
File Server (8080) ← Generated Artifacts
    ↓
Frontend (3000) ← Rich Response + Media
```

### Database Architecture

**Cassandra (Primary Telemetry Storage)**
- Distributed, fault-tolerant NoSQL database
- Optimized for time-series data at scale
- High write throughput for sensor data
- Linear scalability for critical infrastructure
- Replication for data redundancy

**PostgreSQL (Metadata)**
- ThingsBoard entity storage
- Device configurations
- Alarm rules & dashboards
- User management

**Integration Benefits:**
- ✅ High availability (no single point of failure)
- ✅ Massive scalability (millions of writes/sec)
- ✅ Geographic distribution capability
- ✅ Tunable consistency levels
- ✅ Time-series data compression

## 📦 Installation

### Prerequisites

- Docker Desktop 20.10+
- Docker Compose 2.0+
- 16GB RAM minimum (32GB recommended for Cassandra)
- 40GB free disk space (Cassandra data volumes)

### Quick Start

```powershell
# From repository root
cd c:\Users\suhas\Documents\GitHub\OntoBot

# Start Building 3 stack
docker-compose -f docker-compose.bldg3.yml up -d --build

# Wait for Cassandra to initialize (~3-5 minutes)
Start-Sleep -Seconds 300

# Verify services
docker-compose -f docker-compose.bldg3.yml ps

# Check Cassandra health
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool status
```

### Access Points

- **Frontend**: http://localhost:3000
- **Rasa Core**: http://localhost:5005/version
- **Action Server**: http://localhost:5055/health
- **File Server**: http://localhost:8080/health
- **Editor**: http://localhost:6080
- **Duckling**: http://localhost:8000
- **ThingsBoard**: http://localhost:8082
- **Cassandra CQL**: localhost:9042

## ⚙️ Configuration

### Environment Variables

Action Server configuration (set in `docker-compose.bldg3.yml`):

```yaml
environment:
  # File Server
  BASE_URL: http://localhost:8080
  BUNDLE_MEDIA: "true"
  
  # Cassandra Database
  CASSANDRA_HOST: cassandra
  CASSANDRA_PORT: 9042
  CASSANDRA_KEYSPACE: telemetry_bldg3
  CASSANDRA_REPLICATION_FACTOR: 1
  
  # PostgreSQL (ThingsBoard Metadata)
  POSTGRES_HOST: tb-postgres
  POSTGRES_DB: thingsboard
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres
  POSTGRES_PORT: 5432
  
  # Service Integrations
  ANALYTICS_URL: http://microservices:6000/analytics/run
  DECIDER_URL: http://decider-service:6009/decide
  NL2SPARQL_URL: http://nl2sparql:6005/predict
  FUSEKI_URL: http://fuseki:3030/datacenter/query
  
  # ThingsBoard
  TB_HOST: thingsboard
  TB_PORT: 9090
  
  # Feature Flags
  ENABLE_SUMMARIZATION: "true"
  ENABLE_ANALYTICS: "true"
  ENABLE_ALARMS: "true"
```

### Cassandra Configuration

```yaml
cassandra:
  image: cassandra:4.1
  environment:
    CASSANDRA_CLUSTER_NAME: "DataCenter-Cluster"
    CASSANDRA_DC: "DC1"
    CASSANDRA_ENDPOINT_SNITCH: "GossipingPropertyFileSnitch"
    MAX_HEAP_SIZE: "4G"
    HEAP_NEWSIZE: "800M"
  volumes:
    - cassandra_data:/var/lib/cassandra
```

### Volumes

```yaml
volumes:
  ./rasa-bldg3:/app                    # Rasa project files
  ./rasa-bldg3/shared_data:/app/shared_data  # Artifacts
  ./rasa-bldg3/actions:/app/actions    # Custom actions (live reload)
  ./rasa-bldg3/models:/app/models      # Trained models
  cassandra_data:/var/lib/cassandra    # Persistent storage
  postgres_data:/var/lib/postgresql/data  # TB metadata
```

## 💬 Usage

### Example Queries (Data Center Operations)

**Cooling System Monitoring:**
```
"Show me CRAC unit 1 temperature trends"
"What's the cooling efficiency in zone A?"
"Alert me if any CRAC units have alarms"
"Compare supply vs return air temperatures"
```

**Power Distribution:**
```
"What's the current load on PDU 3?"
"Show UPS battery status for all units"
"What's our current PUE?"
"Display power consumption by rack"
```

**Alarm Management:**
```
"Show all active alarms"
"What critical alarms were triggered today?"
"Display temperature threshold violations"
"Show equipment failure alerts"
```

**Environmental Monitoring:**
```
"Show hot aisle temperatures in zone B"
"What's the humidity in rack 15?"
"Display inlet/outlet temperature differential"
"Show me cooling load trends this week"
```

**Efficiency Metrics:**
```
"Calculate our DCiE for today"
"Show power usage effectiveness trend"
"What's the cooling efficiency?"
"Display energy consumption by zone"
```

### Query Flow

1. User asks question via Frontend (3000)
2. Rasa NLU detects intent (e.g., `query_crac_temperature`)
3. Action Server retrieves data from Cassandra/PostgreSQL
4. Analytics performs time-series analysis
5. Decider selects visualization type
6. File Server hosts generated charts
7. Frontend displays results with media

## 🔧 Development

### Project Structure

```
rasa-bldg3/
├── actions/
│   ├── actions.py           # Custom actions (live reload)
│   └── cassandra_client.py  # Cassandra integration
├── data/
│   ├── nlu.yml             # NLU training data (data center specific)
│   ├── rules.yml           # Conversation rules
│   └── stories.yml         # Conversation flows
├── models/                  # Trained Rasa models
├── shared_data/
│   ├── artifacts/          # Generated charts, CSV files
│   └── sensor_mappings/    # UUID to sensor name mappings
├── config.yml              # Rasa pipeline configuration
├── domain.yml              # Intents, entities, responses
├── endpoints.yml           # Action server & event broker
└── credentials.yml         # Channel credentials
```

### Cassandra Schema

```cql
-- Telemetry keyspace
CREATE KEYSPACE IF NOT EXISTS telemetry_bldg3
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- Sensor readings table
CREATE TABLE IF NOT EXISTS telemetry_bldg3.sensor_data (
    sensor_uuid UUID,
    timestamp TIMESTAMP,
    value DOUBLE,
    unit TEXT,
    zone TEXT,
    equipment_type TEXT,
    PRIMARY KEY ((sensor_uuid), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC);

-- Alarms table
CREATE TABLE IF NOT EXISTS telemetry_bldg3.alarms (
    alarm_id UUID,
    timestamp TIMESTAMP,
    severity TEXT,
    equipment_id TEXT,
    message TEXT,
    acknowledged BOOLEAN,
    PRIMARY KEY ((equipment_id), timestamp)
) WITH CLUSTERING ORDER BY (timestamp DESC);
```

### Custom Actions (Cassandra Integration)

```python
# actions/cassandra_client.py
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider

class CassandraClient:
    def __init__(self, hosts=['cassandra'], port=9042, keyspace='telemetry_bldg3'):
        self.cluster = Cluster(hosts, port=port)
        self.session = self.cluster.connect(keyspace)
    
    def get_sensor_data(self, sensor_uuid, start_time, end_time):
        query = """
        SELECT timestamp, value, unit
        FROM sensor_data
        WHERE sensor_uuid = %s
        AND timestamp >= %s
        AND timestamp <= %s
        """
        return self.session.execute(query, (sensor_uuid, start_time, end_time))
    
    def get_active_alarms(self, severity=None):
        if severity:
            query = "SELECT * FROM alarms WHERE severity = %s AND acknowledged = false"
            return self.session.execute(query, (severity,))
        else:
            query = "SELECT * FROM alarms WHERE acknowledged = false"
            return self.session.execute(query)
```

### Adding Data Center-Specific Intents

```yaml
# data/nlu.yml
- intent: query_crac_status
  examples: |
    - show me CRAC unit [1](equipment_id) status
    - what's the temperature of [CRAC-A-01](equipment_id)
    - display cooling efficiency for [zone A](zone_name)
    - how is [CRAC unit 3](equipment_id) performing

- intent: query_ups_status
  examples: |
    - show UPS battery levels
    - what's the status of [UPS 2](equipment_id)
    - display power load on [UPS-B-01](equipment_id)
    - how much charge does [UPS 1](equipment_id) have

- intent: query_alarms
  examples: |
    - show all active alarms
    - what [critical](alarm_severity) alarms do we have
    - display [temperature](alarm_type) alarms
    - show me equipment failure alerts

- intent: calculate_pue
  examples: |
    - what's our PUE
    - calculate power usage effectiveness
    - show me energy efficiency
    - what's the DCiE
```

### Sensor Mapping

```python
# shared_data/sensor_mappings/bldg3_sensors.json
{
  "crac_units": {
    "uuid-crac-001": "CRAC-A-01-Supply-Temp",
    "uuid-crac-002": "CRAC-A-01-Return-Temp",
    "uuid-crac-003": "CRAC-A-01-Airflow"
  },
  "ups_systems": {
    "uuid-ups-001": "UPS-01-Input-Voltage",
    "uuid-ups-002": "UPS-01-Battery-Level",
    "uuid-ups-003": "UPS-01-Load-Percentage"
  },
  "pdus": {
    "uuid-pdu-001": "PDU-01-L1-Voltage",
    "uuid-pdu-002": "PDU-01-L2-Voltage",
    "uuid-pdu-003": "PDU-01-L3-Voltage"
  }
}
```

## 📊 Analytics Integration

Building 3 leverages the Analytics Microservice (port 6001) with focus on:

### Critical Infrastructure Analytics

**Temperature Monitoring:**
- Time-series analysis of CRAC supply/return temperatures
- Hot aisle/cold aisle differential monitoring
- Rack-level thermal mapping
- Anomaly detection for temperature spikes

**Power Analysis:**
- UPS load trending
- PDU phase balance analysis
- PUE/DCiE calculation
- Power consumption forecasting

**Cooling Efficiency:**
- CRAC efficiency scoring
- Cooling capacity utilization
- Airflow optimization analysis
- Energy consumption per cooling ton

**Alarm Analytics:**
- Alarm frequency analysis
- Root cause correlation
- Predictive maintenance triggers
- Threshold optimization

### Analytics API Examples

```bash
# Get CRAC temperature analysis
curl -X POST http://localhost:6001/analytics/run \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_type": "time_series",
    "sensor_id": "CRAC-A-01-Supply-Temp",
    "start_time": "2025-10-01T00:00:00Z",
    "end_time": "2025-10-08T23:59:59Z",
    "aggregation": "1h"
  }'

# Calculate PUE
curl -X POST http://localhost:6001/analytics/run \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_type": "pue_calculation",
    "building_id": "bldg3",
    "timestamp": "2025-10-08T12:00:00Z"
  }'

# Detect temperature anomalies
curl -X POST http://localhost:6001/analytics/run \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_type": "anomaly_detection",
    "sensor_id": "CRAC-A-01-Supply-Temp",
    "method": "isolation_forest",
    "sensitivity": 0.95
  }'
```

## 🧪 Testing

### Health Checks

```powershell
# Check all services
docker-compose -f docker-compose.bldg3.yml ps

# Rasa health
curl http://localhost:5005/version

# Action Server health
curl http://localhost:5055/health

# File Server health
curl http://localhost:8080/health

# Cassandra status
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool status

# Cassandra connectivity
docker-compose -f docker-compose.bldg3.yml exec cassandra cqlsh -e "DESCRIBE KEYSPACES"

# PostgreSQL health
docker-compose -f docker-compose.bldg3.yml exec tb-postgres pg_isready
```

### Test Conversations

```powershell
# Start interactive shell
docker-compose -f docker-compose.bldg3.yml exec rasa rasa shell

# Example conversation:
# You: show me CRAC unit 1 temperature
# Bot: [Displays temperature chart and current readings]
# You: what's our PUE?
# Bot: [Shows PUE calculation with breakdown]
# You: show active alarms
# Bot: [Lists current alarms with severity]
```

### Cassandra Query Testing

```bash
# Connect to Cassandra
docker-compose -f docker-compose.bldg3.yml exec cassandra cqlsh

# Query sensor data
USE telemetry_bldg3;
SELECT * FROM sensor_data WHERE sensor_uuid = <uuid> LIMIT 10;

# Check alarms
SELECT * FROM alarms WHERE acknowledged = false LIMIT 10;

# Verify data ingestion
SELECT COUNT(*) FROM sensor_data;
```

## 🐛 Troubleshooting

### Cassandra Issues

**Problem: Cassandra fails to start**
```powershell
# Check logs
docker-compose -f docker-compose.bldg3.yml logs cassandra

# Common issues:
# - Insufficient memory (increase Docker memory to 8GB+)
# - Port conflict on 9042
# - Corrupted data volume

# Solution: Reset Cassandra
docker-compose -f docker-compose.bldg3.yml down -v
docker volume rm ontobot_cassandra_data
docker-compose -f docker-compose.bldg3.yml up -d cassandra
```

**Problem: Slow Cassandra queries**
```bash
# Check node status
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool status

# Monitor compaction
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool compactionstats

# Optimize table
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool compact telemetry_bldg3 sensor_data
```

### ThingsBoard Integration

**Problem: ThingsBoard not connecting to Cassandra**
```yaml
# Check TB environment variables in docker-compose.bldg3.yml
environment:
  - DATABASE_TS_TYPE=cassandra
  - CASSANDRA_HOST=cassandra
  - CASSANDRA_PORT=9042
```

**Problem: Device data not showing**
```bash
# Check PostgreSQL for device entities
docker-compose -f docker-compose.bldg3.yml exec tb-postgres psql -U postgres -d thingsboard -c "SELECT * FROM device LIMIT 10;"

# Check Cassandra for telemetry
docker-compose -f docker-compose.bldg3.yml exec cassandra cqlsh -e "SELECT * FROM thingsboard.ts_kv_latest LIMIT 10;"
```

### Performance Optimization

**Memory Settings:**
```yaml
# docker-compose.bldg3.yml
cassandra:
  environment:
    MAX_HEAP_SIZE: "8G"      # Increase for production
    HEAP_NEWSIZE: "2G"       # 1/4 of MAX_HEAP_SIZE
```

**Compaction Strategy:**
```cql
-- Optimize for time-series data
ALTER TABLE telemetry_bldg3.sensor_data 
WITH compaction = {
  'class': 'TimeWindowCompactionStrategy',
  'compaction_window_unit': 'HOURS',
  'compaction_window_size': '24'
};
```

## 🔗 Related Documentation

### Building-Specific Docs
- [Building 3 Data Directory](../bldg3/README.md) - Dataset documentation
- [Building 1 README](../rasa-bldg1/README.md) - Real testbed (MySQL)
- [Building 2 README](../rasa-bldg2/README.md) - Office building (TimescaleDB)

### Service Documentation
- [Analytics Microservices](../microservices/README.md) - Analytics API reference
- [Decider Service](../decider-service/README.md) - Decision logic & training
- [NL2SPARQL & Ollama](../Transformers/README.md) - Language translation
- [Frontend](../rasa-frontend/README.md) - React UI configuration

### GitHub Pages Documentation
- [Backend Services Guide](https://suhasdevmane.github.io/_docs/backend_services.md)
- [Multi-Building Guide](https://suhasdevmane.github.io/_docs/multi_building.md)
- [Quick Start](https://suhasdevmane.github.io/_docs/quickstart.md)
- [API Reference](https://suhasdevmane.github.io/_docs/api_reference.md)

### Additional Resources
- [Multi-Building Support](../MULTI_BUILDING_SUPPORT.md) - Switching buildings
- [Port Reference](../PORTS.md) - Complete port mappings
- [Analytics Deep Dive](../analytics.md) - Analytics capabilities

## 🚀 Deployment

### Production Considerations

**High Availability:**
- Multi-node Cassandra cluster (3+ nodes)
- Replication factor: 3
- Consistency level: QUORUM
- Geographic distribution for DR

**Monitoring:**
- Cassandra metrics (nodetool)
- ThingsBoard monitoring
- Rasa conversation analytics
- Alarm dashboard

**Backup:**
```bash
# Cassandra snapshots
docker-compose -f docker-compose.bldg3.yml exec cassandra nodetool snapshot telemetry_bldg3

# Export PostgreSQL
docker-compose -f docker-compose.bldg3.yml exec tb-postgres pg_dump -U postgres thingsboard > backup.sql
```

**Security:**
- Enable Cassandra authentication
- SSL/TLS for all connections
- Network isolation (Docker networks)
- API authentication tokens
- Role-based access control

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

---

## 🆘 Support

**Issues?**
- Check [Troubleshooting](#-troubleshooting) section
- Review [GitHub Pages Documentation](https://suhasdevmane.github.io/)
- See [Multi-Building Guide](https://suhasdevmane.github.io/_docs/multi_building.md)

**Resources:**
- [Rasa Documentation](https://rasa.com/docs/)
- [Cassandra Documentation](https://cassandra.apache.org/doc/)
- [ThingsBoard Documentation](https://thingsboard.io/docs/)
- [Brick Schema](https://brickschema.org/)

---

**Building 3** represents a critical infrastructure deployment with focus on:
- ✅ High-availability data storage (Cassandra)
- ✅ Real-time alarm monitoring
- ✅ Cooling system optimization
- ✅ Power distribution tracking
- ✅ Predictive maintenance
- ✅ Energy efficiency (PUE/DCiE)
