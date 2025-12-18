-- MySQL initialization script for Building 1 (Abacws)
-- Creates tables and inserts sample sensor data

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS abacws;
USE abacws;

-- Sensor metadata table
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id VARCHAR(100) PRIMARY KEY,
    sensor_type VARCHAR(50) NOT NULL,
    location VARCHAR(200),
    zone VARCHAR(100),
    unit VARCHAR(20),
    min_value FLOAT,
    max_value FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sensor_type (sensor_type),
    INDEX idx_location (location),
    INDEX idx_zone (zone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sensor readings table (time-series data)
CREATE TABLE IF NOT EXISTS sensor_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    value FLOAT NOT NULL,
    quality VARCHAR(20) DEFAULT 'good',
    INDEX idx_sensor_timestamp (sensor_id, timestamp),
    INDEX idx_timestamp (timestamp),
    FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Aggregated data table (for performance)
CREATE TABLE IF NOT EXISTS sensor_hourly_aggregates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(100) NOT NULL,
    hour_timestamp TIMESTAMP NOT NULL,
    avg_value FLOAT,
    min_value FLOAT,
    max_value FLOAT,
    count INT,
    INDEX idx_sensor_hour (sensor_id, hour_timestamp),
    FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Insert sample sensors
INSERT INTO sensors (sensor_id, sensor_type, location, zone, unit, min_value, max_value) VALUES
-- Temperature sensors
('TEMP_101', 'Temperature', 'Room 101', 'HVAC_Zone_1', '°C', 15.0, 30.0),
('TEMP_102', 'Temperature', 'Room 102', 'HVAC_Zone_1', '°C', 15.0, 30.0),
('TEMP_103', 'Temperature', 'Room 103', 'HVAC_Zone_1', '°C', 15.0, 30.0),
('TEMP_201', 'Temperature', 'Room 201', 'HVAC_Zone_2', '°C', 15.0, 30.0),
('TEMP_202', 'Temperature', 'Room 202', 'HVAC_Zone_2', '°C', 15.0, 30.0),
('TEMP_AHU1', 'Temperature', 'AHU-1 Supply', 'HVAC_Zone_1', '°C', 10.0, 25.0),
('TEMP_AHU2', 'Temperature', 'AHU-2 Supply', 'HVAC_Zone_2', '°C', 10.0, 25.0),

-- Humidity sensors
('HUM_101', 'Humidity', 'Room 101', 'HVAC_Zone_1', '%RH', 30.0, 70.0),
('HUM_102', 'Humidity', 'Room 102', 'HVAC_Zone_1', '%RH', 30.0, 70.0),
('HUM_103', 'Humidity', 'Room 103', 'HVAC_Zone_1', '%RH', 30.0, 70.0),
('HUM_201', 'Humidity', 'Room 201', 'HVAC_Zone_2', '%RH', 30.0, 70.0),
('HUM_202', 'Humidity', 'Room 202', 'HVAC_Zone_2', '%RH', 30.0, 70.0),

-- CO2 sensors
('CO2_101', 'CO2', 'Room 101', 'HVAC_Zone_1', 'ppm', 400.0, 1500.0),
('CO2_102', 'CO2', 'Room 102', 'HVAC_Zone_1', 'ppm', 400.0, 1500.0),
('CO2_201', 'CO2', 'Room 201', 'HVAC_Zone_2', 'ppm', 400.0, 1500.0),

-- Occupancy sensors
('OCC_101', 'Occupancy', 'Room 101', 'HVAC_Zone_1', 'count', 0.0, 50.0),
('OCC_102', 'Occupancy', 'Room 102', 'HVAC_Zone_1', 'count', 0.0, 50.0),
('OCC_201', 'Occupancy', 'Room 201', 'HVAC_Zone_2', 'count', 0.0, 50.0),

-- Energy meters
('ENERGY_BLDG', 'Energy', 'Main Meter', 'Building', 'kWh', 0.0, 100000.0),
('ENERGY_HVAC', 'Energy', 'HVAC System', 'HVAC_Zone_1', 'kWh', 0.0, 50000.0),
('ENERGY_LIGHTING', 'Energy', 'Lighting', 'Building', 'kWh', 0.0, 20000.0);

-- Insert sample time-series data (last 7 days)
DELIMITER $$

CREATE PROCEDURE GenerateSampleData()
BEGIN
    DECLARE i INT DEFAULT 0;
    DECLARE sensor_cursor_sensor_id VARCHAR(100);
    DECLARE sensor_cursor_sensor_type VARCHAR(50);
    DECLARE sensor_cursor_min FLOAT;
    DECLARE sensor_cursor_max FLOAT;
    DECLARE done INT DEFAULT FALSE;
    
    DECLARE sensor_cursor CURSOR FOR 
        SELECT sensor_id, sensor_type, min_value, max_value FROM sensors;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;
    
    OPEN sensor_cursor;
    
    sensor_loop: LOOP
        FETCH sensor_cursor INTO sensor_cursor_sensor_id, sensor_cursor_sensor_type, sensor_cursor_min, sensor_cursor_max;
        IF done THEN
            LEAVE sensor_loop;
        END IF;
        
        -- Generate data for last 7 days, every 15 minutes
        SET i = 0;
        WHILE i < (7 * 24 * 4) DO
            INSERT INTO sensor_data (sensor_id, timestamp, value, quality)
            VALUES (
                sensor_cursor_sensor_id,
                NOW() - INTERVAL (i * 15) MINUTE,
                sensor_cursor_min + (RAND() * (sensor_cursor_max - sensor_cursor_min)),
                IF(RAND() > 0.95, 'degraded', 'good')
            );
            SET i = i + 1;
        END WHILE;
    END LOOP;
    
    CLOSE sensor_cursor;
END$$

DELIMITER ;

-- Execute the procedure to generate sample data
CALL GenerateSampleData();

-- Drop the procedure after use
DROP PROCEDURE GenerateSampleData;

-- Create hourly aggregates
INSERT INTO sensor_hourly_aggregates (sensor_id, hour_timestamp, avg_value, min_value, max_value, count)
SELECT 
    sensor_id,
    DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00') as hour_timestamp,
    AVG(value) as avg_value,
    MIN(value) as min_value,
    MAX(value) as max_value,
    COUNT(*) as count
FROM sensor_data
GROUP BY sensor_id, DATE_FORMAT(timestamp, '%Y-%m-%d %H:00:00');

-- Create indexes for performance
CREATE INDEX idx_quality ON sensor_data(quality);
CREATE INDEX idx_sensor_id_timestamp_value ON sensor_data(sensor_id, timestamp, value);

-- Create a view for latest sensor readings
CREATE OR REPLACE VIEW latest_sensor_readings AS
SELECT 
    s.sensor_id,
    s.sensor_type,
    s.location,
    s.zone,
    s.unit,
    sd.value as latest_value,
    sd.timestamp as latest_timestamp,
    sd.quality
FROM sensors s
INNER JOIN (
    SELECT sensor_id, MAX(timestamp) as max_timestamp
    FROM sensor_data
    GROUP BY sensor_id
) latest ON s.sensor_id = latest.sensor_id
INNER JOIN sensor_data sd ON sd.sensor_id = latest.sensor_id AND sd.timestamp = latest.max_timestamp;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON abacws.* TO 'root'@'%';
FLUSH PRIVILEGES;

-- Display summary
SELECT 'Database initialized successfully!' AS status;
SELECT COUNT(*) AS total_sensors FROM sensors;
SELECT COUNT(*) AS total_readings FROM sensor_data;
SELECT sensor_type, COUNT(*) AS count FROM sensors GROUP BY sensor_type;
