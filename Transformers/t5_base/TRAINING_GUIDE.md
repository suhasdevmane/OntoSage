# T5 NL2SPARQL Training Guide

## Quick Fix for Your Current Issue

Your model generated a malformed SPARQL query. Here's how to fix it quickly:

### Problem
**Question:** "What is the correlation between Zone_Air_Humidity_Sensor_5.04, CO_Level_Sensor_5.04, PM10_Level_Sensor_Atmospheric_5.04, NO2_Level_Sensor_5.04, CO2_Level_Sensor_5.04, PM2.5_Level_Sensor_Atmospheric_5.04 sensors readings?"

**Bad Output:**
```sparql
SELECT ?timeseriesId ?storedAt WHERE { 
    bldg:Zone_Air_Humidity_Sensor_5.04 bldg:CO2_Level_Sensor_5.04, 
    bldg:CO2_Level_Sensor_5.04, bldg:PM10_Level_Sensor_5.04, 
    bldg:PM2.5_Level_Sensor_Atmospheric_5.04 ref:hasExternalReference ?ref . 
}
```

**Correct Output:**
```sparql
SELECT ?sensor ?timeseriesId ?storedAt WHERE {
    VALUES ?sensor {
        bldg:Zone_Air_Humidity_Sensor_5.04
        bldg:CO_Level_Sensor_5.04
        bldg:PM10_Level_Sensor_Atmospheric_5.04
        bldg:NO2_Level_Sensor_5.04
        bldg:CO2_Level_Sensor_5.04
        bldg:PM2.5_Level_Sensor_Atmospheric_5.04
    }
    ?sensor ref:hasExternalReference ?ref .
    ?ref a ref:TimeseriesReference ;
         ref:hasTimeseriesId ?timeseriesId ;
         ref:storedAt ?storedAt .
}
```

---

## Step-by-Step Solution

### Step 1: Add Training Examples

Navigate to the training directory:
```powershell
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base\training
```

Run the example addition script:
```powershell
python add_training_example.py
```

This will:
- ✅ Backup your current dataset
- ✅ Add 5 correlation examples (including your exact question)
- ✅ Save the updated dataset

**What it adds:**
1. Your exact question with 6 sensors
2. Temperature + Humidity + CO2 correlation (3 sensors)
3. Air Quality + CO2 + NO2 comparison (3 sensors)
4. Humidity + Temperature pair (2 sensors)
5. CO + NO2 + PM10 + PM2.5 query (4 sensors)

### Step 2: Retrain the Model

Navigate to the t5_base directory:
```powershell
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base
```

Run training with default settings:
```powershell
python train_t5_model.py
```

Or customize training parameters:
```powershell
python train_t5_model.py --epochs 5 --batch-size 8 --learning-rate 3e-5
```

**Training Parameters:**
- `--base-model`: Model to fine-tune (default: `t5-base`)
  - Options: `t5-small` (60M params, faster), `t5-base` (220M params), `t5-large` (770M params)
- `--epochs`: Number of training epochs (default: 3)
  - More epochs = better learning but risk of overfitting
  - Recommended: 3-5 for incremental updates
- `--batch-size`: Batch size (default: 4)
  - Larger = faster but needs more GPU memory
  - Reduce if you get OOM errors
- `--learning-rate`: Learning rate (default: 5e-5)
  - Lower = more stable but slower convergence
  - Higher = faster but may overshoot
- `--output-dir`: Output directory (default: `trained`)

**Expected Training Time:**
- T5-small on CPU: ~30-60 minutes
- T5-base on CPU: ~1-2 hours
- T5-base on GPU: ~10-20 minutes

### Step 3: Deploy the New Model

After training completes, you'll see:
```
Model saved to: trained/checkpoint-final
```

#### Option A: Copy to Deployment (Recommended)
```powershell
# Copy the trained checkpoint
Copy-Item -Path "trained\checkpoint-final" -Destination "trained\checkpoint-3" -Recurse -Force

# Restart the nl2sparql service
cd c:\Users\suhas\Documents\GitHub\OntoBot
docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

#### Option B: Update Docker Compose
Edit `docker-compose.bldg1.yml`:
```yaml
nl2sparql:
  volumes:
    - ./Transformers/t5_base/trained/checkpoint-final:/app/checkpoint-3:ro
```

Then restart:
```powershell
docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

### Step 4: Test the Updated Model

Send your original question again and verify the SPARQL is correct.

---

## Adding Future Examples

### Manual Method

1. Open the dataset file:
```
Transformers/t5_base/training/bldg1/bldg1_dataset_extended.json
```

2. Add your example at the end (before the closing `]`):
```json
{
  "question": "Your natural language question here",
  "entities": [
    "bldg:Sensor1",
    "bldg:Sensor2"
  ],
  "sparql": "SELECT ?var WHERE { ... }",
  "category": "correlation",
  "notes": "Optional description"
}
```

3. Save the file

4. Retrain the model (Step 2 above)

### Programmatic Method

Edit `add_training_example.py` and add to the `add_correlation_example()` function:

```python
examples.append({
    "question": "Your question here",
    "entities": ["bldg:Sensor1", "bldg:Sensor2"],
    "sparql": "SELECT ?var WHERE { ... }",
    "category": "my_category",
    "notes": "Description"
})
```

Then run:
```powershell
python training/add_training_example.py
```

---

## SPARQL Pattern Examples

### Single Sensor Query
```sparql
SELECT ?timeseriesId ?storedAt WHERE { 
    bldg:Zone_Air_Humidity_Sensor_5.01 ref:hasExternalReference ?ref . 
    ?ref a ref:TimeseriesReference ; 
         ref:hasTimeseriesId ?timeseriesId ; 
         ref:storedAt ?storedAt . 
}
```

### Multiple Sensor Query (VALUES clause)
```sparql
SELECT ?sensor ?timeseriesId ?storedAt WHERE {
    VALUES ?sensor {
        bldg:Sensor1
        bldg:Sensor2
        bldg:Sensor3
    }
    ?sensor ref:hasExternalReference ?ref .
    ?ref a ref:TimeseriesReference ;
         ref:hasTimeseriesId ?timeseriesId ;
         ref:storedAt ?storedAt .
}
```

### Sensor Type Query
```sparql
SELECT ?sensor ?timeseriesId WHERE {
    ?sensor a brick:Temperature_Sensor ;
            brick:isPointOf bldg:Room5.01 ;
            ref:hasExternalReference ?ref .
    ?ref ref:hasTimeseriesId ?timeseriesId .
}
```

### Label Query
```sparql
SELECT ?label WHERE { 
    bldg:Zone_Air_Humidity_Sensor_5.01 rdfs:label ?label . 
}
```

---

## Troubleshooting

### Issue: "Out of Memory" Error
**Solution:** Reduce batch size
```powershell
python train_t5_model.py --batch-size 2
```

Or use a smaller model:
```powershell
python train_t5_model.py --base-model t5-small
```

### Issue: Training Too Slow
**Solution:** 
- Use GPU if available (automatic detection)
- Reduce epochs: `--epochs 2`
- Use smaller model: `--base-model t5-small`

### Issue: Model Not Improving
**Solution:**
- Add more diverse examples (10-20 similar patterns)
- Increase epochs: `--epochs 5`
- Lower learning rate: `--learning-rate 3e-5`

### Issue: Model Overfitting
**Solution:**
- Reduce epochs: `--epochs 2`
- Add more diverse training data
- Use regularization (built into Trainer)

### Issue: "Model checkpoint not found"
**Solution:** Check the output directory after training:
```powershell
ls trained/checkpoint-final
```

If it's in a different location, update the path in your docker-compose.yml

---

## Training Best Practices

1. **Start Small:** Add 5-10 examples, train, test, repeat
2. **Diverse Examples:** Include variations of the same pattern
3. **Backup First:** Always backup before retraining
4. **Validate Output:** Test the model before deploying
5. **Version Control:** Keep track of which checkpoint performs best
6. **Monitor Metrics:** Watch eval_loss during training

---

## File Structure

```
Transformers/t5_base/
├── training/
│   ├── bldg1/
│   │   └── bldg1_dataset_extended.json  # Main training data
│   ├── backups/                         # Auto-generated backups
│   └── add_training_example.py          # Script to add examples
├── trained/
│   ├── checkpoint-3/                    # Current production model
│   ├── checkpoint-final/                # Latest trained model
│   └── checkpoint_YYYYMMDD_HHMMSS/      # Timestamped checkpoints
├── train_t5_model.py                    # Training script
└── TRAINING_GUIDE.md                    # This file
```

---

## Quick Reference

### Add Examples + Retrain
```powershell
cd c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base
python training/add_training_example.py
python train_t5_model.py
Copy-Item -Path "trained\checkpoint-final" -Destination "trained\checkpoint-3" -Recurse -Force
cd ../..
docker-compose -f docker-compose.bldg1.yml restart nl2sparql
```

### Train with Custom Settings
```powershell
python train_t5_model.py --epochs 5 --batch-size 8 --base-model t5-base
```

### Test Model Locally
```python
from transformers import T5Tokenizer, T5ForConditionalGeneration

tokenizer = T5Tokenizer.from_pretrained("trained/checkpoint-final")
model = T5ForConditionalGeneration.from_pretrained("trained/checkpoint-final")

question = "Your test question here"
input_text = f"Translate to SPARQL: {question}"
input_ids = tokenizer(input_text, return_tensors="pt").input_ids

outputs = model.generate(input_ids, max_length=512, num_beams=4)
sparql = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(sparql)
```

---

## Need Help?

- Check training logs in: `trained/checkpoint_YYYYMMDD_HHMMSS/logs/`
- Review backup files in: `training/backups/`
- Compare model outputs before/after training
- Add more examples if model still produces bad queries

---

**Last Updated:** October 2025  
**Author:** AI Assistant  
**Version:** 1.0
