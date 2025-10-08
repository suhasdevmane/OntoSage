"""
Add new training examples to the T5 NL2SPARQL model dataset.

This script helps you quickly add new natural language questions and their 
corresponding SPARQL queries to the training dataset, then retrain the model.

Usage:
    python add_training_example.py

The script will:
1. Load the existing training dataset
2. Add your new example(s)
3. Save the updated dataset
4. Optionally trigger retraining

Author: AI Assistant
Date: October 2025
"""

import json
import os
from datetime import datetime

# File paths
BLDG1_DATASET = "bldg1/bldg1_dataset_extended.json"
BACKUP_DIR = "backups"

def load_dataset(filepath):
    """Load the existing training dataset."""
    print(f"Loading dataset from: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} existing examples")
    return data

def save_dataset(data, filepath):
    """Save the updated dataset."""
    # Create backup first
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"bldg1_dataset_backup_{timestamp}.json")
    
    print(f"\nCreating backup at: {backup_path}")
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(original)
    
    print(f"Saving updated dataset to: {filepath}")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} examples (added {len(data) - len(json.loads(original))} new)")

def add_example(data, question, entities, sparql, category="correlation", notes=""):
    """Add a new training example to the dataset."""
    new_example = {
        "question": question,
        "entities": entities,
        "sparql": sparql
    }
    if category:
        new_example["category"] = category
    if notes:
        new_example["notes"] = notes
    
    data.append(new_example)
    return data

def add_correlation_example():
    """
    Add the specific correlation example that was failing.
    
    Original Question:
    "What is the correlation between Zone_Air_Humidity_Sensor_5.04, 
    CO_Level_Sensor_5.04, humidity, PM10_Level_Sensor_Atmospheric_5.04, 
    NO2_Level_Sensor_5.04, CO2_Level_Sensor_5.04, 
    PM2.5_Level_Sensor_Atmospheric_5.04 sensors readings and the overall 
    building air quality index based on the dates 01/02/2025 to 05/02/2025?"
    
    Bad Output (from model):
    SELECT ?timeseriesId ?storedAt WHERE { 
        bldg:Zone_Air_Humidity_Sensor_5.04 bldg:CO2_Level_Sensor_5.04, 
        bldg:CO2_Level_Sensor_5.04, bldg:PM10_Level_Sensor_5.04, 
        bldg:PM2.5_Level_Sensor_Atmospheric_5.04 ref:hasExternalReference ?ref . 
    }
    
    Correct Output (should be):
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
    """
    
    examples = []
    
    # Main correlation example
    examples.append({
        "question": "What is the correlation between Zone_Air_Humidity_Sensor_5.04, CO_Level_Sensor_5.04, PM10_Level_Sensor_Atmospheric_5.04, NO2_Level_Sensor_5.04, CO2_Level_Sensor_5.04, PM2.5_Level_Sensor_Atmospheric_5.04 sensors readings and the overall building air quality index?",
        "entities": [
            "bldg:Zone_Air_Humidity_Sensor_5.04",
            "bldg:CO_Level_Sensor_5.04",
            "bldg:PM10_Level_Sensor_Atmospheric_5.04",
            "bldg:NO2_Level_Sensor_5.04",
            "bldg:CO2_Level_Sensor_5.04",
            "bldg:PM2.5_Level_Sensor_Atmospheric_5.04"
        ],
        "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:Zone_Air_Humidity_Sensor_5.04 bldg:CO_Level_Sensor_5.04 bldg:PM10_Level_Sensor_Atmospheric_5.04 bldg:NO2_Level_Sensor_5.04 bldg:CO2_Level_Sensor_5.04 bldg:PM2.5_Level_Sensor_Atmospheric_5.04 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
        "category": "multi_sensor_correlation",
        "notes": "Multiple sensor correlation query using VALUES clause"
    })
    
    # Variations with different sensors
    examples.append({
        "question": "Show correlation between temperature, humidity and CO2 sensors in room 5.04.",
        "entities": [
            "bldg:Air_Temperature_Sensor_5.04",
            "bldg:Zone_Air_Humidity_Sensor_5.04",
            "bldg:CO2_Level_Sensor_5.04"
        ],
        "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:Air_Temperature_Sensor_5.04 bldg:Zone_Air_Humidity_Sensor_5.04 bldg:CO2_Level_Sensor_5.04 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
        "category": "multi_sensor_correlation",
        "notes": "Three sensor correlation"
    })
    
    # Another variation
    examples.append({
        "question": "Compare readings from Air_Quality_Sensor_5.01, CO2_Level_Sensor_5.01, and NO2_Level_Sensor_5.01.",
        "entities": [
            "bldg:Air_Quality_Sensor_5.01",
            "bldg:CO2_Level_Sensor_5.01",
            "bldg:NO2_Level_Sensor_5.01"
        ],
        "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:Air_Quality_Sensor_5.01 bldg:CO2_Level_Sensor_5.01 bldg:NO2_Level_Sensor_5.01 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
        "category": "multi_sensor_correlation",
        "notes": "Multiple sensor comparison"
    })
    
    # Simpler two-sensor correlation
    examples.append({
        "question": "Get data for humidity and temperature sensors in room 5.02.",
        "entities": [
            "bldg:Zone_Air_Humidity_Sensor_5.02",
            "bldg:Air_Temperature_Sensor_5.02"
        ],
        "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:Zone_Air_Humidity_Sensor_5.02 bldg:Air_Temperature_Sensor_5.02 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
        "category": "multi_sensor_correlation",
        "notes": "Two sensor correlation"
    })
    
    # Four sensor correlation
    examples.append({
        "question": "Fetch timeseries data for CO_Level_Sensor_5.03, NO2_Level_Sensor_5.03, PM10_Level_Sensor_Atmospheric_5.03, and PM2.5_Level_Sensor_Atmospheric_5.03.",
        "entities": [
            "bldg:CO_Level_Sensor_5.03",
            "bldg:NO2_Level_Sensor_5.03",
            "bldg:PM10_Level_Sensor_Atmospheric_5.03",
            "bldg:PM2.5_Level_Sensor_Atmospheric_5.03"
        ],
        "sparql": "SELECT ?sensor ?timeseriesId ?storedAt WHERE { VALUES ?sensor { bldg:CO_Level_Sensor_5.03 bldg:NO2_Level_Sensor_5.03 bldg:PM10_Level_Sensor_Atmospheric_5.03 bldg:PM2.5_Level_Sensor_Atmospheric_5.03 } ?sensor ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }",
        "category": "multi_sensor_correlation",
        "notes": "Four sensor correlation"
    })
    
    return examples

def main():
    """Main execution function."""
    print("=" * 70)
    print("T5 NL2SPARQL Training Data Updater")
    print("=" * 70)
    
    # Load existing dataset
    data = load_dataset(BLDG1_DATASET)
    original_count = len(data)
    
    print("\n" + "=" * 70)
    print("Adding Correlation Examples")
    print("=" * 70)
    
    # Add correlation examples
    new_examples = add_correlation_example()
    print(f"\nAdding {len(new_examples)} correlation examples:")
    for i, ex in enumerate(new_examples, 1):
        print(f"  {i}. {ex['question'][:70]}...")
        data.append(ex)
    
    # Save updated dataset
    print("\n" + "=" * 70)
    print("Saving Dataset")
    print("=" * 70)
    save_dataset(data, BLDG1_DATASET)
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Original examples: {original_count}")
    print(f"New examples added: {len(data) - original_count}")
    print(f"Total examples: {len(data)}")
    
    print("\n" + "=" * 70)
    print("Next Steps")
    print("=" * 70)
    print("1. Review the updated dataset: bldg1/bldg1_dataset_extended.json")
    print("2. Run the training script to retrain the model")
    print("3. Test the updated model with your original question")
    print("\nTo retrain:")
    print("  cd c:\\Users\\suhas\\Documents\\GitHub\\OntoBot\\Transformers\\t5_base")
    print("  python train_t5_model.py")
    print("=" * 70)

if __name__ == "__main__":
    main()
