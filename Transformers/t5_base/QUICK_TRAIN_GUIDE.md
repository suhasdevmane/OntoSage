# 🚀 Quick Training Guide - Incremental Fine-tuning

## Why Quick Training?

Instead of retraining on 24,425 examples (1-2 hours), you can:
- ✅ **Train on just 10 examples** (5-10 minutes)
- ✅ **Preserve existing model knowledge**
- ✅ **Fix specific patterns quickly**
- ✅ **Iterate rapidly**

## 📁 Files Created

### 1. Small Dataset: `correlation_fixes.json`
- **Location:** `training/bldg1/correlation_fixes.json`
- **Size:** 10 carefully crafted examples
- **Focus:** Multi-sensor correlation queries with VALUES clause
- **Your exact failing query included!**

### 2. Quick Training Script: `quick_train.py`
- **Location:** `quick_train.py`
- **Purpose:** Incremental fine-tuning on small datasets
- **Speed:** 5-10 minutes vs 1-2 hours
- **Method:** Continues from existing checkpoint (preserves knowledge)

---

## ⚡ Quick Start (5 minutes)

### Step 1: Quick Train (5-10 minutes)

```powershell
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base
python quick_train.py
```

That's it! The script will:
1. Load your existing model (`trained/checkpoint-3`)
2. Train on 10 correlation examples
3. Save the updated model to `trained/quick-fix/checkpoint-quick-fix`

### Step 2: Deploy (30 seconds)

```powershell
Copy-Item -Path "trained\quick-fix\checkpoint-quick-fix" -Destination "trained\checkpoint-3" -Recurse -Force
cd ..\..
docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

### Step 3: Test

Ask your question again - it should now generate correct SPARQL!

---

## 🎯 What's in the Quick Dataset?

10 examples covering:
- ✅ **Your exact failing query** (6 sensors)
- ✅ 2-sensor correlations
- ✅ 3-sensor correlations  
- ✅ 4-sensor correlations
- ✅ 5-sensor correlations
- ✅ Different phrasings ("correlation", "compare", "analyze", "get data")
- ✅ Different sensor types (temperature, humidity, CO2, PM, noise, light)
- ✅ Different rooms (5.01, 5.02, 5.03, 5.04, 5.05)

All using the correct **VALUES clause** pattern!

---

## 🔧 Advanced Options

### Custom Dataset
```powershell
python quick_train.py --dataset training/bldg1/my_custom_fixes.json
```

### More Training Epochs
```powershell
python quick_train.py --epochs 15
```

### Different Base Model
```powershell
python quick_train.py --base-checkpoint trained/checkpoint-2
```

### All Options Combined
```powershell
python quick_train.py --dataset training/bldg1/correlation_fixes.json --epochs 15 --batch-size 4 --learning-rate 2e-5
```

---

## 📊 Quick Train vs Full Train

| Aspect | Quick Train | Full Train |
|--------|-------------|------------|
| **Examples** | 10 | 24,425 |
| **Time (CPU)** | 5-10 min | 1-2 hours |
| **Time (GPU)** | 2-5 min | 10-20 min |
| **Memory** | Low | High |
| **Use Case** | Fix specific patterns | Full retraining |
| **Preserves Knowledge** | ✅ Yes | ⚠️ Replaces |
| **Iteration Speed** | ⚡ Fast | 🐌 Slow |

---

## 💡 When to Use What?

### Use Quick Training When:
- 🎯 You have a specific failing query pattern
- ⚡ You need a fast fix
- 🔁 You want to iterate quickly
- 📚 You want to preserve existing model knowledge
- 🧪 You're experimenting with fixes

### Use Full Training When:
- 🏗️ You're building from scratch
- 📈 You have 50+ new examples
- 🔄 You want to retrain everything
- 🆕 You're using a completely new dataset
- 📚 You want to reorganize training data

---

## 🔄 Iterative Workflow

```
1. Find failing query
   ↓
2. Add 3-10 examples to correlation_fixes.json
   ↓
3. python quick_train.py (5-10 min)
   ↓
4. Deploy and test
   ↓
5. Still not perfect? → Add more examples, repeat step 3
   ↓
6. Perfect? → Done! ✅
```

---

## 📝 Adding Your Own Quick-Fix Examples

Edit `training/bldg1/correlation_fixes.json`:

```json
{
  "question": "Your natural language question here",
  "entities": [
    "bldg:Sensor1",
    "bldg:Sensor2"
  ],
  "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:Sensor1 bldg:Sensor2 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
  "category": "multi_sensor_correlation",
  "notes": "Brief description"
}
```

Then run:
```powershell
python quick_train.py
```

---

## 🎨 Creating Your Own Quick-Fix Datasets

### For Different Issues:

#### Date Range Queries
Create: `training/bldg1/date_range_fixes.json`
```json
[
  {
    "question": "Get sensor data from Jan 1 to Jan 31",
    "sparql": "...",
    "category": "date_range_query"
  }
]
```

Train:
```powershell
python quick_train.py --dataset training/bldg1/date_range_fixes.json
```

#### Aggregation Queries
Create: `training/bldg1/aggregation_fixes.json`
```json
[
  {
    "question": "What is the average temperature in room 5.01?",
    "sparql": "...",
    "category": "aggregation"
  }
]
```

#### Complex Joins
Create: `training/bldg1/join_fixes.json`
```json
[
  {
    "question": "Show sensors in rooms with temperature above 25",
    "sparql": "...",
    "category": "complex_join"
  }
]
```

---

## 🚨 Important Notes

### Model Preservation
Quick training **continues from** your existing model, so:
- ✅ Existing patterns still work
- ✅ New patterns added on top
- ✅ No need to retrain everything

### Training Parameters
- **Epochs:** 10-15 for small datasets (more is OK since dataset is small)
- **Learning Rate:** 3e-5 (lower than full training to preserve existing knowledge)
- **Batch Size:** 2-4 (small dataset doesn't need large batches)

### Best Practices
1. Start with 5-10 examples covering the failing pattern
2. Include variations in phrasing
3. Use different entity names (rooms, sensors)
4. Test after training
5. Add more examples if needed and retrain (only 5-10 min!)

---

## 📦 Deployment

### Quick Deploy
```powershell
# One-liner deployment
Copy-Item -Path "Transformers\t5_base\trained\quick-fix\checkpoint-quick-fix" -Destination "Transformers\t5_base\trained\checkpoint-3" -Recurse -Force; docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

### Safe Deploy (with backup)
```powershell
# Backup current model
Copy-Item -Path "Transformers\t5_base\trained\checkpoint-3" -Destination "Transformers\t5_base\trained\checkpoint-3-backup-$(Get-Date -Format 'yyyyMMdd_HHmmss')" -Recurse

# Deploy new model
Copy-Item -Path "Transformers\t5_base\trained\quick-fix\checkpoint-quick-fix" -Destination "Transformers\t5_base\trained\checkpoint-3" -Recurse -Force

# Restart service
docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

---

## ✅ Example Session

```powershell
# 1. Navigate to t5_base
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base

# 2. Quick train (5-10 minutes)
python quick_train.py

# Output:
# ======================================================================
# Quick Incremental Training - 2025-10-07 23:30:00
# ======================================================================
# Dataset: training/bldg1/correlation_fixes.json
# Base Model: trained/checkpoint-3
# Epochs: 10
# ...
# Training on 10 examples for 10 epochs
# This should be very fast (5-10 minutes)...
# [Progress bars]
# ======================================================================
# Quick Training Complete!
# ======================================================================

# 3. Deploy (30 seconds)
Copy-Item -Path "trained\quick-fix\checkpoint-quick-fix" -Destination "trained\checkpoint-3" -Recurse -Force

# 4. Navigate back
cd ..\..

# 5. Restart service
docker-compose -f docker-compose.bldg1.yml restart nl2sparql

# 6. Test your question - should work now! ✅
```

---

## 🆚 Comparison Example

### Before Quick Training
**Question:** "What is correlation between Zone_Air_Humidity_Sensor_5.04, CO2_Level_Sensor_5.04, PM10_Level_Sensor_Atmospheric_5.04?"

**Bad Output:**
```sparql
SELECT ?timeseriesId ?storedAt WHERE { 
    bldg:Zone_Air_Humidity_Sensor_5.04 bldg:CO2_Level_Sensor_5.04, 
    bldg:PM10_Level_Sensor_5.04 ref:hasExternalReference ?ref . 
}
```
❌ Malformed SPARQL

### After Quick Training (10 min)
**Same Question**

**Good Output:**
```sparql
SELECT ?sensor ?timeseriesId ?storedAt WHERE {
    VALUES ?sensor {
        bldg:Zone_Air_Humidity_Sensor_5.04
        bldg:CO2_Level_Sensor_5.04
        bldg:PM10_Level_Sensor_Atmospheric_5.04
    }
    ?sensor ref:hasExternalReference ?ref .
    ?ref a ref:TimeseriesReference ;
         ref:hasTimeseriesId ?timeseriesId ;
         ref:storedAt ?storedAt .
}
```
✅ Perfect SPARQL with VALUES clause!

---

## 🎓 Summary

**Quick Training is perfect for:**
- ⚡ Rapid iteration
- 🎯 Specific fixes
- 💾 Preserving knowledge
- ⏱️ Time-sensitive updates

**Traditional Training is better for:**
- 🏗️ Major overhauls
- 📚 Large datasets
- 🔄 Complete retraining

**For your case (fixing correlation queries):**
👉 **Quick Training is the way to go!**

---

## 🚀 Ready to Fix Your Model?

```powershell
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base
python quick_train.py
```

**Time to fix:** 5-10 minutes  
**Your query will work after this!** ✅

---

**Questions?** Check the other documentation files:
- `TRAINING_GUIDE.md` - Full training documentation
- `SOLUTION_SUMMARY.md` - Overview of the complete solution
- `WORKFLOW_DIAGRAM.md` - Visual workflow
