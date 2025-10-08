# 🔧 T5 Training GUI - Troubleshooting: Sensor Dropdown Fix

## 🐛 **Problem**
Sensor dropdown in T5 Model Training tab showed no options (empty dropdown).

## 🔍 **Root Causes Found**

### Issue 1: Port Mismatch
- **Docker port mapping**: `6001:6000`
- **Frontend API calls**: `http://localhost:6000`
- **Result**: Frontend couldn't reach backend API

### Issue 2: Missing Volume Mounts
- Docker container had no access to `rasa-bldg1/` folder
- Docker container had no access to `Transformers/` folder
- **Result**: Backend couldn't read `sensor_list.txt`

### Issue 3: Incorrect Path Resolution
- Code used: `../../rasa-bldg1/actions/sensor_list.txt`
- Resolved to: `/app/blueprints/../../rasa-bldg1/` → `/rasa-bldg1/` (doesn't exist)
- Should resolve to: `/app/rasa-bldg1/actions/sensor_list.txt`

## ✅ **Solutions Applied**

### 1. Fixed Port Mapping in `docker-compose.bldg1.yml`

**Before:**
```yaml
ports:
  - "6001:6000"  # host 6001 -> container 6000
```

**After:**
```yaml
ports:
  - "6000:6000"  # host 6000 -> container 6000 (matches frontend API calls)
```

### 2. Added Volume Mounts in `docker-compose.bldg1.yml`

**Added these volumes:**
```yaml
volumes:
  # ... existing volumes ...
  # Mount rasa-bldg1 actions for sensor list access
  - ./rasa-bldg1:/app/rasa-bldg1:ro
  # Mount Transformers directory for T5 training
  - ./Transformers:/app/Transformers
```

### 3. Fixed Path Resolution in `microservices/blueprints/t5_training.py`

**Before:**
```python
SENSOR_LIST_FILE = os.path.join(os.path.dirname(__file__), '../../rasa-bldg1/actions/sensor_list.txt')
```

**After:**
```python
# For Docker: use /app/rasa-bldg1, for local: use relative path
if os.path.exists('/app/rasa-bldg1/actions/sensor_list.txt'):
    SENSOR_LIST_FILE = '/app/rasa-bldg1/actions/sensor_list.txt'
else:
    SENSOR_LIST_FILE = os.path.join(os.path.dirname(__file__), '../../rasa-bldg1/actions/sensor_list.txt')
```

## 📊 **Verification**

### Test 1: Backend Health Check
```bash
curl http://localhost:6000/health
```
**Result:**
```json
{
  "components": ["analytics", "decider", "t5_training"],
  "status": "ok"
}
```
✅ **PASS**

### Test 2: Sensors API
```bash
curl http://localhost:6000/api/t5/sensors
```
**Result:**
```json
{
  "ok": true,
  "sensors": [
    "Air_Quality_Level_Sensor_5.01",
    "Air_Quality_Level_Sensor_5.02",
    ... (680 total sensors)
  ]
}
```
✅ **PASS** - 680 sensors returned!

### Test 3: Frontend Access
1. Open browser: `http://localhost:3000`
2. Navigate to: Settings → T5 Model Training tab
3. Click "Sensors Involved" dropdown
4. **Result**: Dropdown shows all 680 sensors with search functionality

✅ **PASS**

## 🚀 **How to Apply These Fixes**

If you encounter this issue again:

### Step 1: Update docker-compose.bldg1.yml
```yaml
# Around line 131
ports:
  - "6000:6000"  # Change from 6001 to 6000

# Around line 136-139 (add these new volumes)
volumes:
  - ./rasa-bldg1:/app/rasa-bldg1:ro
  - ./Transformers:/app/Transformers
```

### Step 2: Update microservices/blueprints/t5_training.py
```python
# Around line 28-31
# For Docker: use /app/rasa-bldg1, for local: use relative path
if os.path.exists('/app/rasa-bldg1/actions/sensor_list.txt'):
    SENSOR_LIST_FILE = '/app/rasa-bldg1/actions/sensor_list.txt'
else:
    SENSOR_LIST_FILE = os.path.join(os.path.dirname(__file__), '../../rasa-bldg1/actions/sensor_list.txt')
```

### Step 3: Rebuild and Restart
```bash
# Rebuild microservices with updated code
docker-compose -f docker-compose.bldg1.yml build microservices

# Restart both services
docker-compose -f docker-compose.bldg1.yml up -d microservices rasa-frontend
```

### Step 4: Verify
```bash
# Test sensors API
curl http://localhost:6000/api/t5/sensors | ConvertFrom-Json | Select-Object -ExpandProperty sensors | Measure-Object

# Should show: Count = 680
```

## 🎓 **Lessons Learned**

### 1. Docker Path Resolution
- Paths inside containers are different from host paths
- Use absolute paths when mounting volumes
- Check path existence with `os.path.exists()` for cross-environment compatibility

### 2. Port Management
- Frontend and backend ports must match
- Document port mappings in docker-compose
- Use consistent ports across all services

### 3. Volume Mounts
- Mount all required directories for service functionality
- Use read-only (`:ro`) for directories that shouldn't be modified
- Test file access inside container after mounting

### 4. Debugging Strategy
1. Check if service is running (`docker ps`)
2. Check port mappings (`netstat` or `docker ps`)
3. Test API endpoints (`curl` or `Invoke-WebRequest`)
4. Check container logs (`docker logs`)
5. Exec into container to test paths (`docker exec`)
6. Fix and rebuild/restart

## 📝 **Files Modified**

1. ✅ `docker-compose.bldg1.yml` - Port and volume configuration
2. ✅ `microservices/blueprints/t5_training.py` - Path resolution fix

## ✅ **Status: RESOLVED**

**Sensor dropdown now displays all 680 sensors with search functionality!** 🎉

## 🔄 **Next Steps**

1. ✅ Sensors dropdown working
2. ✅ Can add training examples
3. ✅ Can train model
4. ✅ Can deploy model

**You can now use the T5 Training GUI!** 🚀

---

**Date Fixed:** October 8, 2025  
**Issue Duration:** ~30 minutes  
**Severity:** High (blocked main functionality)  
**Resolution:** Complete
