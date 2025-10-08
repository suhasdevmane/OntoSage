# 🚀 Quick Start - T5 Training GUI

## ⚡ 3-Step Setup

### Step 1: Install Frontend Dependency

Open PowerShell and run:

```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\rasa-frontend"
npm install
```

This will install the new `react-select` package needed for the sensor dropdown.

### Step 2: Start Backend (Microservices)

Open a new PowerShell terminal:

```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\microservices"
python app.py
```

**Expected Output:**
```
 * Serving Flask app 'app'
 * Debug mode: on
 * Running on http://0.0.0.0:6000
```

Keep this terminal open.

### Step 3: Start Frontend

Open another PowerShell terminal:

```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\rasa-frontend"
npm start
```

**Expected Output:**
```
Compiled successfully!
The app is running at: http://localhost:3000
```

Browser should automatically open.

---

## 🎯 Access the GUI

1. **Browser opens automatically** to `http://localhost:3000`
2. **Click "Settings"** in the top navigation
3. **Click "T5 Model Training"** tab (the 5th tab)
4. **You're ready!** 🎉

---

## 📝 Add Your First Training Example

### Example: Multi-Sensor Correlation

**1. Question:**
```
What is the correlation between temperature and humidity in zone 5.04?
```

**2. Sensors Involved:**
- Start typing "Zone_Air_Temperature" and select `Zone_Air_Temperature_Sensor_5.04`
- Start typing "Zone_Air_Humidity" and select `Zone_Air_Humidity_Sensor_5.04`

**3. SPARQL Query:**
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

**4. Category:** Multi-Sensor Correlation

**5. Notes:** Zone 5.04 temperature-humidity correlation

**6. Click "Add Example"**

---

## 🏋️ Train Your Model

1. **Set Epochs:** 10 (recommended for quick testing)
2. **Click "Start Training"**
3. **Confirm** the dialog
4. **Wait ~5-10 minutes** - watch the progress bar!
5. **Monitor logs** - they update in real-time
6. **When complete**, click **"Deploy Model to Production"**

---

## 🔄 Activate the New Model

1. Go to **"Action Server"** tab
2. Click **"Restart Action Server"**
3. Wait for "Restart completed successfully"
4. **Done!** Test your queries in the chatbot

---

## ✅ Verify It Works

Test in your chatbot:
```
What is the correlation between temperature and humidity in zone 5.04?
```

The model should now generate the correct SPARQL query with the VALUES clause!

---

## 🆘 Troubleshooting

### Backend won't start
```powershell
cd microservices
pip install Flask Flask-Cors
python app.py
```

### Frontend won't start
```powershell
cd rasa-frontend
npm install
npm start
```

### Can't see sensor dropdown
- Check backend is running (port 6000)
- Verify `rasa-bldg1/actions/sensor_list.txt` exists
- Refresh the browser page

### Training fails
- Check at least 1 example exists
- Verify Python environment has dependencies
- Check training logs for specific errors

---

## 📚 Need More Help?

Check these guides:
- **T5_GUI_SETUP.md** - Detailed setup guide
- **GUI_TRAINING_GUIDE.md** - Complete usage guide
- **T5_GUI_IMPLEMENTATION.md** - Technical details

---

## 🎉 That's It!

You can now train your T5 model using the GUI!

**No more command-line needed!** 🚀
