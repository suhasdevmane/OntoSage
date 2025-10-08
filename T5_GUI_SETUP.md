# T5 Model Training GUI - Quick Setup

## 🎯 Overview

This guide will help you set up and use the new **T5 Model Training GUI** - a web interface for training your NL2SPARQL model without touching code or JSON files.

## ⚡ Quick Start (5 Minutes)

### Step 1: Install Dependencies

**Backend:**
```bash
cd microservices
pip install -r requirements.txt
```

**Frontend:**
```bash
cd rasa-frontend
npm install
```

### Step 2: Start Services

**Terminal 1 - Backend:**
```bash
cd microservices
python app.py
```

**Terminal 2 - Frontend:**
```bash
cd rasa-frontend
npm start
```

### Step 3: Access the GUI

1. Open browser: `http://localhost:3000`
2. Navigate to: **Settings** → **T5 Model Training** tab
3. Start adding training examples!

## 📋 What You Can Do

### ✅ Add Training Examples
- Write natural language questions
- Select sensors from dropdown (680+ sensors)
- Enter SPARQL queries
- Categorize examples
- Add notes

### ✅ Manage Examples
- View all training examples in a table
- Edit existing examples
- Delete unwanted examples
- Refresh to see latest changes

### ✅ Train Models
- Set training epochs (1-50)
- Start training with one click
- Monitor progress in real-time
- View detailed training logs
- See completion status

### ✅ Deploy Models
- Deploy trained models to production
- Automatic backup of current model
- View all available models
- Check model sizes and dates

## 🚀 Example Workflow

### 1. Add a Training Example

**Question:**
```
What is the correlation between temperature and humidity in zone 5.04?
```

**Select Sensors:**
- Zone_Air_Temperature_Sensor_5.04
- Zone_Air_Humidity_Sensor_5.04

**SPARQL Query:**
```sparql
SELECT ?sensor ?timeseriesId ?storedAt 
WHERE {
  VALUES ?sensor { 
    bldg:Zone_Air_Humidity_Sensor_5.04 
    bldg:Zone_Air_Temperature_Sensor_5.04 
  }
  ?sensor brick:hasLocation ?location .
  ?sensor brick:timeseries ?timeseries .
  ?timeseries ref:hasTimeseriesId ?timeseriesId .
  ?timeseries ref:storedAt ?storedAt .
}
```

**Category:** Multi-Sensor Correlation

**Notes:** Zone 5.04 correlation query

### 2. Train the Model

1. Set epochs to **10**
2. Click **Start Training**
3. Wait ~5-10 minutes
4. Watch progress bar and logs

### 3. Deploy to Production

1. After training completes, click **Deploy Model to Production**
2. Go to **Action Server** tab
3. Click **Restart Action Server**
4. Test your queries!

## 📊 Training Time Guide

| Examples | Epochs | Time Estimate |
|----------|--------|---------------|
| 10 | 10 | 5-10 minutes |
| 10 | 15 | 7-15 minutes |
| 25 | 10 | 10-20 minutes |
| 50 | 10 | 15-30 minutes |

*Times vary based on hardware (GPU/CPU)*

## 🎨 GUI Features

### 1. Training Examples Form
- **Question field**: Natural language input
- **Sensor selector**: Multi-select dropdown with search
- **SPARQL editor**: Monospace text area for queries
- **Category dropdown**: Organize by type
- **Notes field**: Add context or reminders

### 2. Examples Table
- Displays all training examples
- Shows question, entity count, category, notes
- Edit (✏️) and Delete (🗑️) buttons
- Refresh button to reload
- Example counter in header

### 3. Training Monitor
- **Progress bar**: Visual progress indicator (0-100%)
- **Status badge**: RUNNING / COMPLETED / ERROR
- **Training logs**: Real-time console output
- **Auto-scroll**: Always shows latest logs
- **Deploy button**: Appears after successful training

### 4. Model Manager
- Lists all trained model checkpoints
- Shows last modified date/time
- Displays model size in MB
- Highlights production model with badge

## 🛠️ Technical Details

### Architecture

```
┌─────────────────┐         ┌─────────────────┐
│  React Frontend │ ◄─────► │ Flask Backend   │
│  (Port 3000)    │   REST  │  (Port 6000)    │
└─────────────────┘   API   └─────────────────┘
                                    │
                                    ▼
                            ┌─────────────────┐
                            │ quick_train.py  │
                            │ T5 Fine-tuning  │
                            └─────────────────┘
```

### API Endpoints

- `GET /api/t5/sensors` - Load sensor list
- `GET /api/t5/examples` - Get training examples
- `POST /api/t5/examples` - Add new example
- `PUT /api/t5/examples/:id` - Update example
- `DELETE /api/t5/examples/:id` - Delete example
- `POST /api/t5/train` - Start training
- `GET /api/t5/train/:jobId/status` - Poll training status
- `POST /api/t5/deploy` - Deploy to production
- `GET /api/t5/models` - List models

### Data Storage

**Training Examples:**
```
Transformers/t5_base/training/bldg1/correlation_fixes.json
```

**Trained Models:**
```
Transformers/t5_base/trained/checkpoint-quick-fix/
Transformers/t5_base/trained/checkpoint-3/  (production)
```

**Sensor List:**
```
rasa-bldg1/actions/sensor_list.txt
```

## 🔧 Configuration

### Backend Configuration

File: `microservices/blueprints/t5_training.py`

```python
# Path configurations
T5_BASE_DIR = '../../Transformers/t5_base'
TRAINING_DATASET = 'training/bldg1/correlation_fixes.json'
SENSOR_LIST_FILE = '../../rasa-bldg1/actions/sensor_list.txt'
```

### Training Parameters

Adjustable in GUI or via code:
- **Epochs**: 1-50 (default: 10)
- **Batch size**: 2 (default)
- **Learning rate**: 3e-5 (default)
- **Base checkpoint**: checkpoint-3 (production model)

## 📝 Best Practices

### 1. Writing Questions
- ✅ "What is the CO2 level in zone 5.04?"
- ✅ "Show correlation between temperature and humidity"
- ❌ "sensor query" (too vague)
- ❌ "give me data" (not specific)

### 2. SPARQL Patterns

**Multi-Sensor (Use VALUES):**
```sparql
VALUES ?sensor { bldg:Sensor1 bldg:Sensor2 }
```

**Single Sensor (Direct):**
```sparql
bldg:Sensor1 brick:hasLocation ?location .
```

### 3. Training Strategy
1. Start with 5-10 examples
2. Train for 10 epochs
3. Test in chatbot
4. Add more examples for failures
5. Re-train incrementally

### 4. Model Management
- Keep backups of successful models
- Test before deploying to production
- Document what each training session improves
- Use notes field to track changes

## ❓ Troubleshooting

### Cannot Load Sensors
- Check `sensor_list.txt` exists
- Verify backend is running (port 6000)
- Refresh the page

### Training Won't Start
- Ensure at least 1 example exists
- Check no other training is running
- Verify Python environment has all dependencies

### Model Not Working After Deploy
- Restart action server (Action Server tab)
- Wait for restart to complete
- Clear browser cache and retry

### Logs Show Errors
- Check SPARQL syntax in examples
- Verify sensor names are correct
- Ensure JSON format is valid
- Check Python dependencies installed

## 📚 Additional Documentation

- **GUI_TRAINING_GUIDE.md**: Detailed GUI usage guide
- **QUICK_TRAIN_GUIDE.md**: Command-line quick training
- **TRAINING_GUIDE.md**: Full training documentation
- **SOLUTION_SUMMARY.md**: Technical implementation details

## 🎯 Common Use Cases

### Case 1: Fix Malformed SPARQL
**Problem**: Model generates syntax errors for multi-sensor queries

**Solution**:
1. Add 5-10 examples with correct VALUES clause pattern
2. Train for 10 epochs
3. Deploy and test

### Case 2: New Sensor Types
**Problem**: Model doesn't handle new sensor types

**Solution**:
1. Add examples for each new sensor type
2. Include various question phrasings
3. Train for 15 epochs
4. Deploy and verify

### Case 3: Complex Queries
**Problem**: Model struggles with nested or complex queries

**Solution**:
1. Add examples breaking down the complexity
2. Include subquery patterns
3. Train for 20 epochs
4. Test incrementally

## 🔒 Security Notes

- GUI runs on localhost only by default
- No authentication required (local development)
- Training data stored locally
- Models stored locally

For production deployment:
- Add authentication
- Implement access controls
- Use HTTPS
- Secure API endpoints

## 🚀 Next Steps

1. ✅ Complete setup following Quick Start
2. ✅ Add your first training example
3. ✅ Train with 10 epochs
4. ✅ Deploy and test
5. ✅ Iterate based on results

## 💡 Tips & Tricks

- **Use search in sensor dropdown**: Type to filter 680+ sensors
- **Copy-paste SPARQL**: Test queries first, then paste
- **Monitor logs during training**: Catch errors early
- **Keep notes updated**: Document what each example teaches
- **Start small**: 5-10 good examples > 50 mediocre ones
- **Test immediately**: Deploy and test after each training session

## 📞 Support

For issues or questions:
1. Check training logs in GUI
2. Review console output of services
3. Read troubleshooting section above
4. Check individual guide files

---

**Happy Training!** 🎉

Your T5 model is now trainable with just a few clicks!
