# T5 Model Training GUI Guide

## Overview

The T5 Model Training GUI allows you to easily add training examples and train the NL2SPARQL model directly from the web interface without needing to use command-line tools or edit JSON files manually.

## Prerequisites

1. **Backend Service Running**: Microservices must be running on port 6000
2. **Frontend Running**: Rasa-frontend must be running on port 3000
3. **Dependencies Installed**: Both backend and frontend dependencies must be installed

## Installation Steps

### 1. Install Backend Dependencies

```bash
cd microservices
pip install -r requirements.txt
```

### 2. Install Frontend Dependencies

```bash
cd rasa-frontend
npm install
```

This will install the new `react-select` package needed for the sensor dropdown.

### 3. Start Services

**Terminal 1 - Start Microservices:**
```bash
cd microservices
python app.py
```

**Terminal 2 - Start Frontend:**
```bash
cd rasa-frontend
npm start
```

## Using the GUI

### Accessing the Training Interface

1. Open your browser and navigate to: `http://localhost:3000`
2. Click on **Settings** in the navigation
3. Click on the **T5 Model Training** tab (the 5th tab)

### Adding Training Examples

The training form has the following fields:

#### 1. Question (Required)
- Enter the natural language question
- Example: "What is the correlation between temperature and humidity in zone 5.04?"

#### 2. Sensors Involved (Optional)
- Multi-select dropdown with all 680+ available sensors
- Start typing to search for sensors
- Select all sensors mentioned in your question
- Example: Select "Zone_Air_Humidity_Sensor_5.04" and "Zone_Air_Temperature_Sensor_5.04"

#### 3. SPARQL Query (Required)
- Enter the correct SPARQL query that answers the question
- Use the VALUES clause pattern for multi-sensor queries
- Example:
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

#### 4. Category (Optional)
- Select from predefined categories:
  - **User Defined** (default)
  - **Multi-Sensor Correlation**
  - **Single Sensor**
  - **Complex Query**

#### 5. Notes (Optional)
- Add any notes or context about this example
- Example: "Multi-sensor correlation query for zone 5.04"

#### 6. Submit
- Click **Add Example** to save
- The example will appear in the training examples table below

### Managing Training Examples

#### View Examples
- All examples are displayed in a table below the form
- Shows: Question, Number of Entities, Category, Notes, Actions
- Current count displayed in header

#### Edit Examples
- Click the ✏️ (Edit) button next to any example
- Form will populate with the example's data
- Modify as needed and click **Update Example**
- Click **Cancel Edit** to discard changes

#### Delete Examples
- Click the 🗑️ (Delete) button next to any example
- Confirm deletion in the popup
- Example will be permanently removed

#### Refresh List
- Click the **Refresh** button in the table header
- Reloads examples from the server

### Training the Model

#### Configure Training

1. **Set Epochs**:
   - Default: 10 epochs
   - Range: 1-50 epochs
   - More epochs = better learning but longer training time
   - Recommended: 10-15 epochs for quick training

2. **Start Training**:
   - Click **Start Training** button
   - Confirm the training in the popup
   - Training will start in the background

#### Monitor Training Progress

1. **Progress Bar**:
   - Shows percentage complete (0-100%)
   - Updates automatically every 2 seconds
   - Color-coded:
     - Blue (animated): Training in progress
     - Green: Completed successfully
     - Red: Error occurred

2. **Status Badge**:
   - Shows current status: RUNNING, COMPLETED, ERROR
   - Located next to progress percentage

3. **Training Logs**:
   - Real-time logs displayed in console-style window
   - Auto-scrolls to latest output
   - Shows:
     - Training command
     - Epoch progress
     - Loss values
     - Completion messages
     - Any errors

#### Training Time Estimates

- **10 examples, 10 epochs**: ~5-10 minutes
- **10 examples, 15 epochs**: ~7-15 minutes
- **25 examples, 10 epochs**: ~10-20 minutes

*Times vary based on your hardware (GPU/CPU)*

### Deploying Trained Models

#### After Training Completes

1. **Deploy Button Appears**:
   - Once training status shows COMPLETED
   - Click **Deploy Model to Production**

2. **Deployment Process**:
   - Backs up current production model
   - Copies new model to production location
   - Shows success message

3. **Restart Required**:
   - The action server needs to be restarted to use the new model
   - Go to **Action Server** tab
   - Click **Restart Action Server**
   - Wait for restart to complete

#### Model Management

The **Available Models** section shows:
- List of all trained models
- Last modified date/time
- Model size in MB
- Production model is marked with green "Production" badge

Current production model: `checkpoint-3`

Quick-trained models saved as: `checkpoint-quick-fix`

## Best Practices

### Writing Good Training Examples

1. **Be Specific**:
   - Write questions as users would ask them
   - Include sensor names, zone numbers, or specific identifiers

2. **Cover Variations**:
   - Add multiple phrasings of similar questions
   - Include synonyms and alternative terms

3. **Test SPARQL First**:
   - Test your SPARQL query in the Rasa chatbot first
   - Ensure it returns correct results before adding to training

4. **Use Correct Patterns**:
   - Multi-sensor queries: Use VALUES clause
   - Single sensor: Direct entity reference
   - Complex queries: Break into subqueries if needed

### Training Strategy

1. **Start Small**:
   - Add 5-10 examples for a specific pattern
   - Train and test
   - Add more examples based on results

2. **Incremental Training**:
   - Use quick training for small improvements
   - Add examples addressing specific failures
   - Re-train with new examples

3. **Category Organization**:
   - Group related examples by category
   - Makes it easier to manage and update

4. **Regular Backups**:
   - The system automatically backs up models when deploying
   - Backups named: `checkpoint-3-backup-YYYYMMDD_HHMMSS`
   - Keep successful models for rollback if needed

## Troubleshooting

### Backend Not Responding

**Error**: "Failed to load sensors" or "Failed to load examples"

**Solution**:
1. Check if microservices are running on port 6000
2. Open terminal and run:
   ```bash
   cd microservices
   python app.py
   ```
3. Check console for any error messages

### Training Won't Start

**Error**: "No training examples found"

**Solution**:
- Add at least one training example before starting training

**Error**: Training button disabled

**Solution**:
- Wait for any currently running training to complete
- Check that examples list is not empty

### Training Failed

**Check Logs**:
- Scroll through training logs for error messages
- Common issues:
  - Invalid JSON format in examples
  - Missing dependencies
  - Insufficient disk space
  - Python environment issues

**Solution**:
1. Fix any errors in training examples
2. Ensure all dependencies installed
3. Check Python environment is activated
4. Try training again

### Model Not Loading After Deployment

**Solution**:
1. Go to **Action Server** tab
2. Click **Restart Action Server**
3. Wait for "Restart completed successfully" message
4. Test a query in the chatbot

### Sensor Dropdown Not Loading

**Error**: Dropdown shows "Loading..." indefinitely

**Solution**:
1. Check that `rasa-bldg1/actions/sensor_list.txt` exists
2. Verify file contains sensor names (one per line)
3. Restart backend service
4. Refresh the browser page

## API Endpoints Reference

The GUI uses these backend endpoints:

- `GET /api/t5/sensors` - Get sensor list
- `GET /api/t5/examples` - Get training examples
- `POST /api/t5/examples` - Add new example
- `PUT /api/t5/examples/:index` - Update example
- `DELETE /api/t5/examples/:index` - Delete example
- `POST /api/t5/train` - Start training job
- `GET /api/t5/train/:jobId/status` - Poll training status
- `POST /api/t5/deploy` - Deploy model to production
- `GET /api/t5/models` - List available models

## Files Modified

### Backend Files
- `microservices/blueprints/t5_training.py` - New API blueprint
- `microservices/app.py` - Registered new blueprint

### Frontend Files
- `rasa-frontend/src/pages/ModelTrainingTab.js` - New training tab component
- `rasa-frontend/src/pages/SettingsTabs.js` - Added new tab
- `rasa-frontend/package.json` - Added react-select dependency

### Training Data
- `Transformers/t5_base/training/bldg1/correlation_fixes.json` - Training examples storage

## Support

For issues or questions:
1. Check the logs in the training interface
2. Review the console output of backend/frontend services
3. Refer to QUICK_TRAIN_GUIDE.md for command-line training
4. Check TRAINING_GUIDE.md for full training documentation

## Quick Reference

| Action | Location | Button/Field |
|--------|----------|--------------|
| Add Example | Training Form | "Add Example" button |
| Edit Example | Examples Table | ✏️ icon |
| Delete Example | Examples Table | 🗑️ icon |
| Start Training | Train Model Card | "Start Training" button |
| Deploy Model | Train Model Card | "Deploy Model to Production" |
| View Models | Available Models Card | Table list |
| Restart Action Server | Action Server Tab | "Restart Action Server" |

Enjoy training your T5 model with the new GUI! 🚀
