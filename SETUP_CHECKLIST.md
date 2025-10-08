# 🚀 T5 Training GUI - Setup Checklist

## ✅ Pre-Flight Checklist

Use this checklist to ensure everything is ready before using the GUI.

---

## 1️⃣ Backend Setup

### Check Backend Dependencies
```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\microservices"
pip list | Select-String "Flask"
```

**Expected Output:**
```
Flask              2.0.3
Flask-Cors         3.0.10
```

If missing, install:
```powershell
pip install -r requirements.txt
```

### Verify Backend Files
- [ ] File exists: `microservices/blueprints/t5_training.py`
- [ ] File modified: `microservices/app.py` (has t5_training_bp import)
- [ ] File exists: `rasa-bldg1/actions/sensor_list.txt`

### Start Backend Service
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

**✅ Backend Ready**: Keep this terminal open

---

## 2️⃣ Frontend Setup

### Install Dependencies
```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\rasa-frontend"
npm install
```

**This will install:**
- react-select (new)
- All other existing dependencies

**Expected Output:**
```
added 1 package, and audited XXX packages in Xs
found 0 vulnerabilities
```

### Verify Frontend Files
- [ ] File exists: `rasa-frontend/src/pages/ModelTrainingTab.js`
- [ ] File modified: `rasa-frontend/src/pages/SettingsTabs.js` (has ModelTrainingTab)
- [ ] File modified: `rasa-frontend/package.json` (has react-select)

### Start Frontend Service
```powershell
cd "c:\Users\suhas\Documents\GitHub\OntoBot\rasa-frontend"
npm start
```

**Expected Output:**
```
Compiled successfully!
The app is running at: http://localhost:3000
```

**✅ Frontend Ready**: Browser opens automatically

---

## 3️⃣ Access the GUI

### Navigate to Training Tab
1. [ ] Browser opened to `http://localhost:3000`
2. [ ] Click **Settings** in top navigation
3. [ ] See 5 tabs: Edit & Validate | Train & Activate | Action Server | Analytics | **T5 Model Training**
4. [ ] Click **T5 Model Training** tab
5. [ ] Page loads without errors

### Verify Components Loaded
- [ ] "Add Training Example" card visible
- [ ] "Training Examples (N)" table visible
- [ ] "Train Model" card visible
- [ ] "Available Models" card visible

### Check Sensor Dropdown
- [ ] Click "Sensors Involved" dropdown
- [ ] Dropdown shows loading state
- [ ] Sensors load (680+ options)
- [ ] Can search by typing
- [ ] Can select multiple sensors

**✅ GUI Ready**: All components working

---

## 4️⃣ Test Basic Functionality

### Add a Test Example
```
Question: What is the temperature in zone 5.04?
Sensors: Zone_Air_Temperature_Sensor_5.04
SPARQL:
SELECT ?timeseriesId ?storedAt 
WHERE {
  bldg:Zone_Air_Temperature_Sensor_5.04 brick:timeseries ?timeseries .
  ?timeseries ref:hasTimeseriesId ?timeseriesId .
  ?timeseries ref:storedAt ?storedAt .
}
Category: Single Sensor
Notes: Test example
```

- [ ] Fill in form
- [ ] Click "Add Example"
- [ ] See success alert
- [ ] Example appears in table

### Test Edit Functionality
- [ ] Click ✏️ (Edit) button on test example
- [ ] Form populates with example data
- [ ] Modify question
- [ ] Click "Update Example"
- [ ] See updated data in table

### Test Delete Functionality
- [ ] Click 🗑️ (Delete) button on test example
- [ ] Confirm in dialog
- [ ] Example removed from table

**✅ Basic CRUD**: All operations working

---

## 5️⃣ Verify Data Files

### Check Training Dataset
```powershell
Get-Content "c:\Users\suhas\Documents\GitHub\OntoBot\Transformers\t5_base\training\bldg1\correlation_fixes.json"
```

- [ ] File exists
- [ ] Contains valid JSON
- [ ] Has array of examples
- [ ] Shows your added examples

### Check Sensor List
```powershell
Get-Content "c:\Users\suhas\Documents\GitHub\OntoBot\rasa-bldg1\actions\sensor_list.txt" | Measure-Object -Line
```

**Expected Output:**
```
Lines: 680+ (approximately)
```

**✅ Data Files**: Accessible and valid

---

## 6️⃣ Quick Training Test (Optional)

### Add Minimal Training Set
- [ ] Add 5 simple examples
- [ ] Examples cover different query types
- [ ] All examples have valid SPARQL

### Run Quick Training
- [ ] Set epochs to 3 (for quick test)
- [ ] Click "Start Training"
- [ ] Confirm dialog
- [ ] Progress bar appears and updates
- [ ] Logs stream in real-time
- [ ] Training completes (may take 3-5 minutes)

### Verify Training Output
- [ ] Status shows "COMPLETED"
- [ ] Progress bar at 100%
- [ ] "Deploy Model to Production" button appears
- [ ] No errors in logs

**✅ Training Works**: Model can be trained

---

## 7️⃣ Deployment Test (Optional)

### Deploy Trained Model
- [ ] Click "Deploy Model to Production"
- [ ] Confirm deployment
- [ ] See success message
- [ ] Refresh models list
- [ ] See backup created (checkpoint-3-backup-YYYYMMDD_HHMMSS)

### Restart Action Server
- [ ] Go to "Action Server" tab
- [ ] Click "Restart Action Server"
- [ ] Wait for "Restart completed successfully"
- [ ] Check logs for no errors

### Test in Chatbot
- [ ] Open chatbot
- [ ] Ask a question from your training examples
- [ ] Verify correct SPARQL generated
- [ ] Confirm query returns results

**✅ Deployment Works**: Model active in production

---

## 🎯 Final Verification

### All Systems Operational
- [x] Backend running (port 6000)
- [x] Frontend running (port 3000)
- [x] GUI accessible
- [x] Sensors load
- [x] Can add examples
- [x] Can edit examples
- [x] Can delete examples
- [x] Can start training
- [x] Progress monitoring works
- [x] Logs stream correctly
- [x] Can deploy models
- [x] Models list updates

### Documentation Available
- [x] QUICKSTART_GUI.md
- [x] T5_GUI_SETUP.md
- [x] GUI_TRAINING_GUIDE.md
- [x] T5_GUI_IMPLEMENTATION.md
- [x] T5_GUI_ARCHITECTURE.md
- [x] T5_GUI_COMPLETE.md

---

## 🆘 Troubleshooting Quick Reference

### Backend Issues
```powershell
# Check if port 6000 is in use
netstat -ano | findstr :6000

# Restart backend
cd microservices
python app.py
```

### Frontend Issues
```powershell
# Clear npm cache
npm cache clean --force

# Reinstall dependencies
rm -r node_modules
npm install

# Restart frontend
npm start
```

### Browser Issues
```powershell
# Clear browser cache
# Ctrl+Shift+R (hard refresh)
# Or clear cache in browser settings
```

### File Permission Issues
```powershell
# Check file exists and is readable
Test-Path "path\to\file"
Get-Content "path\to\file"
```

---

## 📊 Expected Results Summary

| Component | Expected State | How to Verify |
|-----------|---------------|---------------|
| Backend API | Running on port 6000 | Terminal shows "Running on http://0.0.0.0:6000" |
| Frontend | Running on port 3000 | Browser shows interface |
| Sensor Dropdown | 680+ sensors | Dropdown populates |
| Training Examples | Editable list | Table displays examples |
| Training | Progress monitoring | Progress bar updates |
| Logs | Real-time streaming | Logs scroll automatically |
| Deployment | One-click deploy | Success message appears |
| Models List | Shows checkpoints | Table displays models |

---

## ✅ Success Criteria

You're ready to use the GUI when ALL of these are true:

1. ✅ Backend terminal shows "Running on http://0.0.0.0:6000"
2. ✅ Frontend browser shows "Settings" page
3. ✅ "T5 Model Training" tab is visible and clickable
4. ✅ Sensor dropdown loads without errors
5. ✅ Can add/edit/delete examples without errors
6. ✅ Training can be started and monitored
7. ✅ Models can be deployed successfully

---

## 🎉 Ready to Go!

If all checkboxes are ✅, you're ready to start training your T5 model!

**Recommended Next Steps:**
1. Read **QUICKSTART_GUI.md** for a quick tutorial
2. Add 5-10 training examples
3. Train for 10 epochs
4. Deploy and test

**Happy Training!** 🚀

---

## 📞 Need Help?

### Quick References
- **Setup**: See QUICKSTART_GUI.md
- **Usage**: See GUI_TRAINING_GUIDE.md
- **Technical**: See T5_GUI_IMPLEMENTATION.md
- **Architecture**: See T5_GUI_ARCHITECTURE.md

### Check These First
1. Are both services running (ports 6000 and 3000)?
2. Did you run `npm install`?
3. Check browser console for errors (F12)
4. Check terminal output for errors
5. Try restarting both services

### Common Fixes
- **Sensors not loading**: Restart backend
- **Training won't start**: Add at least 1 example
- **Model not active**: Restart action server
- **Port in use**: Kill process on port and restart
