# 🔧 T5 Training GUI - Port 6000 → 6001 Fix

## 🐛 Problem

The T5 Training GUI sensor dropdown was showing "No options" due to Chrome's **ERR_UNSAFE_PORT** error.

### Root Cause

**Port 6000 is on Chrome's blocklist of "unsafe ports"**. Chrome blocks approximately 70+ ports that are commonly used for other protocols to prevent security vulnerabilities. Port 6000 is blocked because it's used by the X11 protocol.

When the browser tried to fetch `http://localhost:6000/api/t5/sensors`, Chrome blocked the request with:
```
net::ERR_UNSAFE_PORT
```

## ✅ Solution

Changed the **host port** from 6000 to 6001 while keeping the **container port** at 6000.

### Port Mapping Change

**Before:**
```yaml
ports:
  - "6000:6000"  # host 6000 → container 6000
```

**After:**
```yaml
ports:
  - "6001:6000"  # host 6001 → container 6000 (avoids Chrome ERR_UNSAFE_PORT)
```

## 📝 Files Updated

### 1. Docker Compose Files
All three building-specific docker-compose files:

✅ **`docker-compose.bldg1.yml`**
- Line 131: Changed port mapping to `"6001:6000"`
- Comment: Added note about Chrome ERR_UNSAFE_PORT

✅ **`docker-compose.bldg2.yml`**
- Line 262: Changed port mapping to `"6001:6000"`
- Comment: Added note about Chrome ERR_UNSAFE_PORT

✅ **`docker-compose.bldg3.yml`**
- Line 291: Changed port mapping to `"6001:6000"`
- Comment: Added note about Chrome ERR_UNSAFE_PORT

✅ **`docker-compose.yml`** (base file)
- Line 410: Already had `"6001:6000"` - no change needed

### 2. Frontend Code

✅ **`rasa-frontend/src/pages/ModelTrainingTab.js`**
- Replaced all instances of `localhost:6000` with `localhost:6001`
- Updated API endpoints:
  - `/api/t5/sensors`
  - `/api/t5/examples`
  - `/api/t5/models`
  - `/api/t5/train/${jobId}/status`
  - All other T5 training endpoints

### 3. Documentation Files

✅ **`MULTI_BUILDING_SUPPORT.md`**
- Updated port mappings in docker-compose examples
- Fixed sensor count table to show both host port (6001) and container port (6000)
- Updated troubleshooting section references
- Fixed all `localhost:6000` references to `localhost:6001`

✅ **`README.md`**
- Already correct: Shows `6001 (host→6000 container)` in port table
- Internal container URLs still use `http://microservices:6000` (correct - no change needed)

✅ **`microservices/README.md`**
- Already correct: Documents `http://localhost:6001 (host → container 6000)`

✅ **`PORTS.md`**
- Already correct: Shows `6001 | 6000` in port mapping table

### 4. Files That DON'T Need Changes

❌ **Container-internal references to port 6000**
These are correct and should NOT be changed:

- `microservices/Dockerfile` - `EXPOSE 6000` (container port)
- `microservices/app.py` - `port=6000` (container port)
- `docker-compose.bldg*.yml` - `ANALYTICS_URL=http://microservices:6000/analytics/run` (internal DNS)
- `docker-compose.bldg*.yml` - Healthcheck uses `http://localhost:6000/health` (inside container)
- `rasa-bldg1/actions/actions.py` - `http://microservices:6000` (internal DNS)

**Why?** These refer to the **container's internal port** or **Docker network DNS**, which remains 6000.

## 🔍 Port Architecture

### External Access (Browser → Host)
```
Browser (Chrome/Firefox/etc.)
    ↓
http://localhost:6001  ← Host port (safe, not blocked)
    ↓
Docker port mapping (6001→6000)
    ↓
Container port 6000
    ↓
Flask app listening on 0.0.0.0:6000
```

### Internal Docker Network
```
Container A (e.g., rasa action server)
    ↓
http://microservices:6000  ← Docker DNS (internal)
    ↓
Container B (microservices) listening on port 6000
```

## 🧪 Testing

### Verify Port 6001 is Accessible
```powershell
# Test network connectivity
Test-NetConnection -ComputerName localhost -Port 6001

# Test API endpoint
curl http://localhost:6001/api/t5/sensors

# Count sensors returned
curl http://localhost:6001/api/t5/sensors | ConvertFrom-Json | Select-Object -ExpandProperty sensors | Measure-Object
```

Expected result: **680 sensors** for Building 1

### Verify Frontend Works
1. Open browser to `http://localhost:3000`
2. Navigate to **Settings → T5 Model Training**
3. Check **Sensors Involved** dropdown
4. Should show: "Debug: 680 sensors loaded"
5. Dropdown should have 680 options

### Verify All Buildings
```powershell
# Building 1
docker-compose -f docker-compose.bldg1.yml up -d microservices
Start-Sleep -Seconds 5
curl http://localhost:6001/api/t5/sensors | ConvertFrom-Json | Select-Object -ExpandProperty sensors | Measure-Object
# Expected: Count = 680

# Building 2
docker-compose -f docker-compose.bldg1.yml down microservices
docker-compose -f docker-compose.bldg2.yml up -d microservices
Start-Sleep -Seconds 5
curl http://localhost:6001/api/t5/sensors | ConvertFrom-Json | Select-Object -ExpandProperty sensors | Measure-Object
# Expected: Count = 329

# Building 3
docker-compose -f docker-compose.bldg2.yml down microservices
docker-compose -f docker-compose.bldg3.yml up -d microservices
Start-Sleep -Seconds 5
curl http://localhost:6001/api/t5/sensors | ConvertFrom-Json | Select-Object -ExpandProperty sensors | Measure-Object
# Expected: Count = 597
```

## 📚 Chrome's Unsafe Ports

Chrome blocks these ports (partial list):
- **1** (tcpmux)
- **7** (echo)
- **9** (discard)
- **11** (systat)
- **13** (daytime)
- **15** (netstat)
- **17** (qotd)
- **19** (chargen)
- **20** (ftp-data)
- **21** (ftp)
- **22** (ssh)
- **23** (telnet)
- **25** (smtp)
- **37** (time)
- **42** (name)
- **43** (nicname)
- **53** (domain)
- **77** (priv-rjs)
- **79** (finger)
- **87** (ttylink)
- **95** (supdup)
- **101** (hostname)
- **102** (iso-tsap)
- **103** (gppitnp)
- **104** (acr-nema)
- **109** (pop2)
- **110** (pop3)
- **111** (sunrpc)
- **113** (auth)
- **115** (sftp)
- **117** (uucp-path)
- **119** (nntp)
- **123** (ntp)
- **135** (msrpc)
- **139** (netbios-ssn)
- **143** (imap)
- **179** (bgp)
- **389** (ldap)
- **465** (smtps)
- **512** (exec)
- **513** (login)
- **514** (shell)
- **515** (printer)
- **526** (tempo)
- **530** (courier)
- **531** (chat)
- **532** (netnews)
- **540** (uucp)
- **556** (remotefs)
- **563** (nntps)
- **587** (submission)
- **601** (syslog)
- **636** (ldaps)
- **993** (imaps)
- **995** (pop3s)
- **2049** (nfs)
- **3659** (apple-sasl)
- **4045** (lockd)
- **6000** (X11) ← **This was our problem!**
- **6665-6669** (IRC)

Source: [Chromium Source Code - net/base/port_util.cc](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/net/base/port_util.cc)

## ✅ Verification Checklist

- [x] Updated docker-compose.bldg1.yml port mapping
- [x] Updated docker-compose.bldg2.yml port mapping
- [x] Updated docker-compose.bldg3.yml port mapping
- [x] Updated frontend API calls to use localhost:6001
- [x] Updated MULTI_BUILDING_SUPPORT.md documentation
- [x] Verified port 6001 is accessible from host
- [x] Verified API returns sensors on port 6001
- [x] Tested frontend sensor dropdown loads correctly
- [x] Verified internal container communication still works
- [x] Documented change in this file

## 🎯 Summary

**Problem:** Chrome blocked port 6000 (X11 protocol port)  
**Solution:** Changed host port to 6001, kept container port at 6000  
**Result:** T5 Training GUI sensor dropdown now loads 680 sensors successfully  

**Files Changed:**
- 3 docker-compose files (port mapping)
- 1 frontend file (API endpoints)
- 1 documentation file (MULTI_BUILDING_SUPPORT.md)

**Files Verified (Already Correct):**
- README.md
- microservices/README.md
- PORTS.md
- docker-compose.yml (base)

---

**Date:** October 8, 2025  
**Issue:** T5 Training GUI sensor dropdown empty  
**Root Cause:** Chrome ERR_UNSAFE_PORT on port 6000  
**Resolution:** Changed to port 6001  
**Status:** ✅ **RESOLVED**
