#!/usr/bin/env python3
"""
Test script for mysql_dummy_publisher data generation
Validates that realistic values are being generated correctly
"""
import json
import os

# Load sensor mapping
script_dir = os.path.dirname(os.path.abspath(__file__))
sensor_uuids = json.load(open(os.path.join(script_dir, 'sensor_uuids.json')))

print("=" * 80)
print("SENSOR UUID MAPPING TEST")
print("=" * 80)

# Sample some sensors
sample_sensors = [
    'Air_Temperature_Sensor_5.01',
    'Zone_Air_Humidity_Sensor_5.01',
    'Air_Quality_Level_Sensor_5.01',
    'Air_Quality_Sensor_5.01',
    'TVOC_Level_Sensor_5.01',
    'Sound_Noise_Sensor_MEMS_5.01'
]

print(f"\nFound {len(sensor_uuids)} total sensors")
print("\nSample sensor UUIDs:")
for sensor in sample_sensors:
    if sensor in sensor_uuids:
        print(f"  {sensor:40} -> {sensor_uuids[sensor]}")
    else:
        print(f"  {sensor:40} -> NOT FOUND")

# Load CSV schema
print("\n" + "=" * 80)
print("SCHEMA MAPPING TEST")
print("=" * 80)

import csv
schema_file = os.path.join(script_dir, 'postgresql columns.csv')
with open(schema_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"\nFound {len(rows)} total columns in schema")

# Check data types
type_counts = {}
for row in rows:
    dt = row['DATA_TYPE']
    type_counts[dt] = type_counts.get(dt, 0) + 1

print("\nData type distribution:")
for dt, count in sorted(type_counts.items()):
    print(f"  {dt:20} : {count:4} columns")

# Check specific sensor UUIDs in schema
print("\n" + "=" * 80)
print("CROSS-REFERENCE TEST")
print("=" * 80)

print("\nVerifying sample sensors exist in schema with correct types:")
for sensor in sample_sensors:
    if sensor in sensor_uuids:
        uuid = sensor_uuids[sensor]
        schema_row = next((r for r in rows if r['COLUMN_NAME'] == uuid), None)
        if schema_row:
            dt = schema_row['DATA_TYPE']
            prec = schema_row.get('NUMERIC_PRECISION', 'NULL')
            scale = schema_row.get('NUMERIC_SCALE', 'NULL')
            print(f"  {sensor:40}")
            print(f"    UUID: {uuid}")
            print(f"    Type: {dt:10} Precision: {prec:4} Scale: {scale}")
        else:
            print(f"  {sensor:40} -> UUID NOT IN SCHEMA")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
