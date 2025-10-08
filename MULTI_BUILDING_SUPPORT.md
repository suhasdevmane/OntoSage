# 🏢 T5 Training GUI - Multi-Building Support

## 📊 Overview

The T5 Training GUI now supports **all three buildings** in your OntoBot system:
- **Building 1** (bldg1): 680 sensors
- **Building 2** (bldg2): 329 sensors  
- **Building 3** (bldg3): 597 sensors

The frontend automatically detects and loads sensors from whichever building is currently active in Docker.

## 🔧 Changes Made

### 1. Docker Compose Files Updated

All three docker-compose files have been updated with the necessary volume mounts:

#### `docker-compose.bldg1.yml`
```yaml
microservices:
  ports:
    - "6001:6000"  # host 6001 -> container 6000 - Using 6001 to avoid Chrome ERR_UNSAFE_PORT
  volumes:
    - microservices-bldg1-plugins:/app/analytics_plugins
    - microservices-bldg1-meta:/app/analytics_meta
    - microservices-bldg1-cache:/app/.cache
    # Mount rasa-bldg1 actions for sensor list access
    - ./rasa-bldg1:/app/rasa-bldg1:ro
    # Mount Transformers directory for T5 training
    - ./Transformers:/app/Transformers
```

#### `docker-compose.bldg2.yml`
```yaml
microservices:
  ports:
    - "6001:6000"  # host 6001 -> container 6000 - Using 6001 to avoid Chrome ERR_UNSAFE_PORT
  volumes:
    - microservices-bldg2-plugins:/app/analytics_plugins
    - microservices-bldg2-meta:/app/analytics_meta
    - microservices-bldg2-cache:/app/.cache
    # Mount rasa-bldg2 actions for sensor list access
    - ./rasa-bldg2:/app/rasa-bldg2:ro
    # Mount Transformers directory for T5 training
    - ./Transformers:/app/Transformers
```

#### `docker-compose.bldg3.yml`
```yaml
microservices:
  ports:
    - "6001:6000"  # host 6001 -> container 6000 - Using 6001 to avoid Chrome ERR_UNSAFE_PORT
  volumes:
    - microservices-bldg3-plugins:/app/analytics_plugins
    - microservices-bldg3-meta:/app/analytics_meta
    - microservices-bldg3-cache:/app/.cache
    # Mount rasa-bldg3 actions for sensor list access
    - ./rasa-bldg3:/app/rasa-bldg3:ro
    # Mount Transformers directory for T5 training
    - ./Transformers:/app/Transformers
```

### 2. Backend Auto-Detection

Updated `microservices/blueprints/t5_training.py` to automatically detect which building's sensors to load:

```python
# Auto-detect which building's sensor list to use
SENSOR_LIST_FILE = None
for building in ['bldg1', 'bldg2', 'bldg3']:
    docker_path = f'/app/rasa-{building}/actions/sensor_list.txt'
    local_path = os.path.join(os.path.dirname(__file__), f'../../rasa-{building}/actions/sensor_list.txt')
    
    if os.path.exists(docker_path):
        SENSOR_LIST_FILE = docker_path
        logger.info(f"Using sensor list from {building} (Docker path)")
        break
    elif os.path.exists(local_path):
        SENSOR_LIST_FILE = local_path
        logger.info(f"Using sensor list from {building} (local path)")
        break
```

**How it works:**
1. Checks for `/app/rasa-bldg1/actions/sensor_list.txt` first (Docker)
2. If not found, checks for `/app/rasa-bldg2/actions/sensor_list.txt`
3. If not found, checks for `/app/rasa-bldg3/actions/sensor_list.txt`
4. Falls back to local paths if not running in Docker
5. Loads the first available sensor list automatically

### 3. File Consistency

Fixed naming inconsistency in Building 3:
- **Old name**: `rasa-bldg3/actions/sensors_list.txt` (with 's')
- **New name**: `rasa-bldg3/actions/sensor_list.txt` (without 's')
- Created copy for consistency with other buildings

## 🚀 How to Use

### Switching Between Buildings

#### Run with Building 1:
```bash
# Start Building 1 services
docker-compose -f docker-compose.bldg1.yml up -d microservices rasa-frontend

# Access GUI at http://localhost:3000
# Settings → T5 Model Training
# Sensor dropdown will show 680 sensors from Building 1
```

#### Run with Building 2:
```bash
# Stop Building 1 first (to free port 6001)
docker-compose -f docker-compose.bldg1.yml down microservices

# Start Building 2 services
docker-compose -f docker-compose.bldg2.yml up -d microservices rasa-frontend

# Access GUI at http://localhost:3000
# Settings → T5 Model Training
# Sensor dropdown will show 329 sensors from Building 2
```

#### Run with Building 3:
```bash
# Stop current building first
docker-compose -f docker-compose.bldg2.yml down microservices

# Start Building 3 services
docker-compose -f docker-compose.bldg3.yml up -d microservices rasa-frontend

# Access GUI at http://localhost:3000
# Settings → T5 Model Training
# Sensor dropdown will show 597 sensors from Building 3
```

## 📊 Sensor Count by Building

| Building | Container Name | Sensor Count | Host Port | Container Port | Status |
|----------|---------------|--------------|-----------|----------------|--------|
| Building 1 | `microservices_container` | 680 | 6001 | 6000 | ✅ Ready |
| Building 2 | `microservices_container` | 329 | 6001 | 6000 | ✅ Ready |
| Building 3 | `microservices_container` | 597 | 6001 | 6000 | ✅ Ready |

**Note:** All buildings use the same container name and host port (6001). Only one building can run at a time.

## 🔄 Workflow for Each Building

### 1. Training Model for Building 1

```bash
# Start Building 1
docker-compose -f docker-compose.bldg1.yml up -d microservices rasa-frontend

# Open http://localhost:3000
# Go to Settings → T5 Model Training

# Add training examples using Building 1 sensors
# Train model
# Deploy to production
# Models saved in: Transformers/t5_base/trained/checkpoint-3
```

### 2. Training Model for Building 2

```bash
# Switch to Building 2
docker-compose -f docker-compose.bldg1.yml down microservices
docker-compose -f docker-compose.bldg2.yml up -d microservices rasa-frontend

# Open http://localhost:3000
# Go to Settings → T5 Model Training

# Add training examples using Building 2 sensors
# Train model
# Deploy to production
# Models saved in: Transformers/t5_base/trained/checkpoint-3
```

### 3. Training Model for Building 3

```bash
# Switch to Building 3
docker-compose -f docker-compose.bldg2.yml down microservices
docker-compose -f docker-compose.bldg3.yml up -d microservices rasa-frontend

# Open http://localhost:3000
# Go to Settings → T5 Model Training

# Add training examples using Building 3 sensors
# Train model
# Deploy to production
# Models saved in: Transformers/t5_base/trained/checkpoint-3
```

## 🎯 Frontend Behavior

The **same frontend works for all buildings**! 

When you access `http://localhost:3000`:
- Frontend always calls `http://localhost:6001/api/t5/sensors`
- Backend auto-detects which building is mounted
- Returns sensors from the active building
- Dropdown shows the correct sensors automatically

**No frontend changes needed when switching buildings!** 🎉

## 📁 Directory Structure

```
OntoBot/
├── docker-compose.bldg1.yml    ✅ Updated - mounts rasa-bldg1
├── docker-compose.bldg2.yml    ✅ Updated - mounts rasa-bldg2
├── docker-compose.bldg3.yml    ✅ Updated - mounts rasa-bldg3
│
├── microservices/
│   └── blueprints/
│       └── t5_training.py      ✅ Updated - auto-detects building
│
├── rasa-bldg1/
│   └── actions/
│       └── sensor_list.txt     ✅ 680 sensors
│
├── rasa-bldg2/
│   └── actions/
│       └── sensor_list.txt     ✅ 329 sensors
│
├── rasa-bldg3/
│   └── actions/
│       ├── sensors_list.txt    (old name)
│       └── sensor_list.txt     ✅ 597 sensors (created)
│
└── Transformers/
    └── t5_base/
        └── trained/
            └── checkpoint-3     (shared across all buildings)
```

## ⚠️ Important Notes

### 1. One Building at a Time
- Only **one building** can run at a time (same port 6001 on host)
- Must stop current building before starting another
- Use `docker-compose down` to stop properly

### 2. Shared Model Directory
- All buildings share the same `Transformers/` directory
- Training data and models are **shared**
- Be careful when deploying models - they affect all buildings
- Consider creating separate model directories if needed

### 3. Port Conflicts
- All buildings use port 6001 for microservices (host) → 6000 (container)
- Frontend always on port 3000
- Rasa on port 5005
- Ensure no conflicts before starting

### 4. Data Persistence
- Training examples stored in: `Transformers/t5_base/training/bldg1/correlation_fixes.json`
- Models stored in: `Transformers/t5_base/trained/`
- Consider creating separate training files for each building

## 🔧 Troubleshooting

### Sensor Dropdown Empty

**Check which building is running:**
```bash
docker ps | Select-String "microservices"
```

**Check logs:**
```bash
docker logs microservices_container --tail 20
```

**Look for:** `Using sensor list from bldg1/bldg2/bldg3 (Docker path)`

### Wrong Sensors Showing

**Problem:** Building 2 sensors showing when Building 1 is running

**Solution:** 
```bash
# Completely stop and remove container
docker-compose -f docker-compose.bldg2.yml down microservices

# Rebuild Building 1
docker-compose -f docker-compose.bldg1.yml build microservices
docker-compose -f docker-compose.bldg1.yml up -d microservices
```

### Port Already in Use

**Problem:** Can't start building, port 6001 in use

**Solution:**
```bash
# Find what's using port 6001
netstat -ano | findstr :6001

# Stop all buildings
docker-compose -f docker-compose.bldg1.yml down microservices
docker-compose -f docker-compose.bldg2.yml down microservices
docker-compose -f docker-compose.bldg3.yml down microservices

# Start desired building
docker-compose -f docker-compose.bldg1.yml up -d microservices
```

## 🎓 Best Practices

### 1. Separate Training Data
Consider creating separate training datasets for each building:
```
Transformers/t5_base/training/
├── bldg1/
│   └── correlation_fixes.json
├── bldg2/
│   └── correlation_fixes.json
└── bldg3/
    └── correlation_fixes.json
```

### 2. Model Naming
Consider naming models by building:
```
Transformers/t5_base/trained/
├── checkpoint-bldg1/
├── checkpoint-bldg2/
├── checkpoint-bldg3/
└── checkpoint-3/  (current production)
```

### 3. Clear Switching
Always use this sequence when switching buildings:
```bash
# 1. Stop current
docker-compose -f docker-compose.bldgX.yml down microservices

# 2. Start new
docker-compose -f docker-compose.bldgY.yml up -d microservices

# 3. Verify
docker logs microservices_container --tail 5
```

## ✅ Verification Commands

### Check Active Building
```bash
docker logs microservices_container 2>&1 | Select-String "Using sensor list from"
```

### Test Sensor API
```bash
$response = Invoke-RestMethod -Uri "http://localhost:6001/api/t5/sensors"
Write-Host "Sensor Count: $($response.sensors.Count)"
$response.sensors | Select-Object -First 5
```

### Test All Buildings
```bash
# Building 1
docker-compose -f docker-compose.bldg1.yml up -d microservices
Start-Sleep 5
Invoke-RestMethod "http://localhost:6001/api/t5/sensors" | Select-Object -ExpandProperty sensors | Measure-Object | Select-Object Count

# Building 2
docker-compose -f docker-compose.bldg1.yml down microservices
docker-compose -f docker-compose.bldg2.yml up -d microservices
Start-Sleep 5
Invoke-RestMethod "http://localhost:6001/api/t5/sensors" | Select-Object -ExpandProperty sensors | Measure-Object | Select-Object Count

# Building 3
docker-compose -f docker-compose.bldg2.yml down microservices
docker-compose -f docker-compose.bldg3.yml up -d microservices
Start-Sleep 5
Invoke-RestMethod "http://localhost:6001/api/t5/sensors" | Select-Object -ExpandProperty sensors | Measure-Object | Select-Object Count
```

## 🎉 Summary

✅ **All three buildings supported**
✅ **Same frontend for all buildings**
✅ **Auto-detection of active building**
✅ **Consistent file naming**
✅ **Volume mounts configured**
✅ **Ready to use!**

**Your T5 Training GUI now works seamlessly with all three buildings!** 🚀

---

**Last Updated:** October 8, 2025  
**Buildings Configured:** 3 (bldg1, bldg2, bldg3)  
**Total Sensors:** 1,606 (680 + 329 + 597)
