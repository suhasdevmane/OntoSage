# 🚀 Abacws Quick Start - Historical Sensor Data Visualization

## ✅ Implementation Complete!

**What**: Abacws API + Visualiser now connected to MySQL with 576,846 historical sensor readings  
**Status**: ✅ All services running and healthy  
**Access**: http://localhost:8090 (3D Visualiser)

---

## 📍 Quick Access

```bash
# 3D Building Visualiser
http://localhost:8090

# API Health Check
http://localhost:5000/health

# API Documentation
http://localhost:5000

# pgAdmin (Database Management)
http://localhost:5050
```

---

## 🔧 Essential Commands

### Check Service Status
```bash
docker ps --filter "name=abacws" --format "table {{.Names}}\t{{.Status}}"
```

### View API Logs
```bash
docker logs abacws-api --tail 50
```

### View Visualiser Logs
```bash
docker logs abacws-visualiser --tail 50
```

### Restart Services
```bash
cd OntoBot2.0
docker-compose -f docker-compose.agentic.yml restart api visualiser
```

### Stop Services
```bash
cd OntoBot2.0
docker-compose -f docker-compose.agentic.yml stop api visualiser
```

### Rebuild from Scratch
```bash
cd OntoBot2.0
docker-compose -f docker-compose.agentic.yml down
docker-compose -f docker-compose.agentic.yml up -d --build api visualiser
```

---

## 🗄️ Database Access

### MySQL (Sensor Time-Series Data)
```bash
# Access MySQL CLI
docker exec -it mysql-bldg1 mysql -uroot -pmysql sensordb

# Query sensor data
docker exec mysql-bldg1 mysql -uroot -pmysql -e \
  "SELECT Datetime FROM sensordb.sensor_data ORDER BY Datetime DESC LIMIT 5;"

# Count records
docker exec mysql-bldg1 mysql -uroot -pmysql -sN -e \
  "SELECT COUNT(*) FROM sensordb.sensor_data;"
# Expected: 576846
```

### PostgreSQL (ThingsBoard Device Metadata)
```bash
# Access PostgreSQL CLI
docker exec -it postgres-thingsboard psql -U thingsboard -d thingsboard

# List tables
docker exec postgres-thingsboard psql -U thingsboard -d thingsboard -c "\dt"
```

---

## 🧪 Health Checks

### Quick Validation (All-in-One)
```bash
curl http://localhost:5000/health && curl http://localhost:8090/health
```

**Expected Output**:
```json
{"status":"ok","db":{"engine":"mysql","status":"ok"}}
{"status":"ok"}
```

### Comprehensive Test Suite
```bash
cd C:\Users\suhas\Documents\GitHub\OntoBot
pwsh -NoProfile -File .\scripts\test-database-connections.ps1
```

---

## 📊 Current Configuration

### Database Details
| Database | Container | Port | Records | Purpose |
|----------|-----------|------|---------|---------|
| MySQL | mysql-bldg1 | 3307 (ext) / 3306 (int) | 576,846 | Sensor time-series |
| PostgreSQL | postgres-thingsboard | 5432 | - | Device metadata |
| MongoDB | mongo-chat-history | 27017 | - | Chat history |

### Service Details
| Service | Container | Port | Status |
|---------|-----------|------|--------|
| API | abacws-api | 5000 | ✅ Healthy |
| Visualiser | abacws-visualiser | 8090 | ✅ Healthy |

---

## ⚙️ Key Configuration

### Environment Variables (`.env`)
```bash
# CRITICAL: Use internal port 3306 (not external 3307)
API_MYSQL_PORT=3306

# Database credentials
API_MYSQL_HOST=mysql-bldg1
API_MYSQL_DATABASE=sensordb
API_MYSQL_USER=root
API_MYSQL_PASSWORD=mysql

# Dual database mode
API_ENABLE_MYSQL=true
API_ENABLE_POSTGRES=true

# Visualiser → API connection
VISUALISER_API_HOST=abacws-api:5000
VISUALISER_ENABLE_HISTORICAL=true
```

---

## 🐛 Common Issues

### Issue: API Cannot Connect to MySQL
**Symptom**: API logs show "ECONNREFUSED"

**Fix**:
```bash
# Check .env file has correct port
grep API_MYSQL_PORT .env
# Should show: API_MYSQL_PORT=3306 (NOT 3307)

# Restart API
docker-compose -f docker-compose.agentic.yml restart api
```

---

### Issue: Visualiser Shows Blank Page
**Symptom**: Browser shows empty screen

**Fix**:
```bash
# Check API is healthy
curl http://localhost:5000/health

# Check browser console (F12) for errors
# Verify API_HOST is correct
docker inspect abacws-visualiser | grep API_HOST
# Should show: API_HOST=abacws-api:5000
```

---

### Issue: "Container name already in use"
**Symptom**: Docker error when starting services

**Fix**:
```bash
# Remove old containers
docker rm -f abacws-api abacws-visualiser

# Restart services
cd OntoBot2.0
docker-compose -f docker-compose.agentic.yml up -d api visualiser
```

---

## 📚 Documentation

- **Complete Integration Guide**: `docs/ABACWS_MYSQL_INTEGRATION_GUIDE.md`
- **Implementation Summary**: `ABACWS_IMPLEMENTATION_SUMMARY.md`
- **Test Suite**: `scripts/test-database-connections.ps1`

---

## 🎯 Next Steps

### 1. Create Sensor Metadata Mapping
Map UUID sensor columns to human-readable names:
```sql
CREATE TABLE sensor_metadata (
  sensor_uuid VARCHAR(36) PRIMARY KEY,
  sensor_name VARCHAR(100),
  sensor_type VARCHAR(50),
  location VARCHAR(100)
);
```

### 2. Link to Brick Ontology
Import sensor-to-Brick-class mappings from TTL files in `bldg1/`

### 3. Add Real-Time Data
```bash
# Start ThingsBoard
docker-compose -f docker-compose.agentic.yml up -d thingsboard

# Access ThingsBoard UI
http://localhost:8082
```

---

## ✅ Success Checklist

- [x] MySQL running with 576,846 sensor records
- [x] PostgreSQL running with ThingsBoard schema
- [x] Abacws API connected to MySQL (port 3306)
- [x] Abacws Visualiser accessible at http://localhost:8090
- [x] API health check returns `{"status":"ok"}`
- [x] Visualiser health check returns `{"status":"ok"}`
- [x] Historical sensor data accessible via API
- [x] Container networking properly configured
- [x] Documentation complete

---

**Last Updated**: 2025-11-23  
**Status**: ✅ **PRODUCTION READY**  
**Goal Achieved**: Historical sensor data visualization in 3D building model 🎉
