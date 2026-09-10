-- ============================================================================
-- bldg1 narrow time-series tables — complete DDL for all 15 modalities
--
-- Schema for every table: (uuid CHAR(36), datetime DATETIME, value DOUBLE)
-- PRIMARY KEY (uuid, datetime) — one row per sensor per timestamp.
--
-- "Real" data source connection:
--   When the real Abacws sensor DB becomes available, populate these tables
--   by querying the source for each UUID listed in bldg1_sensor_uuids.csv
--   and inserting rows here with the matching uuid + datetime + value.
--
-- Ontology link (required — both halves of design contract #8):
--   Each UUID is declared in a bldg1_*.ttl file as:
--     bldg:<SensorIRI>  ref:hasExternalReference [
--         a ref:TimeseriesReference ;
--         ref:hasTimeseriesId "<uuid>" ;
--         ref:storedAt      bldg:<table>        -- matches the table name below
--     ] .
--
-- Tables not in the original create_narrow_timeseries_tables.sql
-- (co2_data, humidity_data, temperature_data, parking_data) were created
-- directly against MySQL during development and omitted from the DDL.
-- They are included here to make a fresh clone fully deployable.
-- ============================================================================

USE sensordb;

-- ---------------------------------------------------------------------------
-- Environmental / IAQ modalities
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS temperature_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Air temperature (°C)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_temperature_uuid     (uuid),
    INDEX idx_temperature_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Air Temperature Sensor readings (°C)';

CREATE TABLE IF NOT EXISTS humidity_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Relative humidity (%)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_humidity_uuid     (uuid),
    INDEX idx_humidity_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Humidity Sensor readings (%)';

CREATE TABLE IF NOT EXISTS co2_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'CO₂ concentration (ppm)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_co2_uuid     (uuid),
    INDEX idx_co2_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='CO₂ / Air Quality Sensor readings (ppm)';

CREATE TABLE IF NOT EXISTS iaq_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'PM2.5 (µg/m³) or TVOC (ppb) depending on sensor',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_iaq_uuid     (uuid),
    INDEX idx_iaq_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IAQ: PM2.5 (µg/m³) and TVOC (ppb)';

-- ---------------------------------------------------------------------------
-- Lighting / acoustics
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS light_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Illuminance (lux)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_light_uuid     (uuid),
    INDEX idx_light_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Illuminance sensor readings (lux)';

CREATE TABLE IF NOT EXISTS noise_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Noise level (dB)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_noise_uuid     (uuid),
    INDEX idx_noise_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Noise level sensor readings (dB)';

-- ---------------------------------------------------------------------------
-- Occupancy / access
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS occupancy_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Occupancy count (persons)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_occupancy_uuid     (uuid),
    INDEX idx_occupancy_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Occupancy sensor readings (persons)';

CREATE TABLE IF NOT EXISTS contact_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Contact state: 0=closed, 1=open',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_contact_uuid     (uuid),
    INDEX idx_contact_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Door and window contact sensor state (0=closed, 1=open)';

CREATE TABLE IF NOT EXISTS parking_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Free parking spaces (count)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_parking_uuid     (uuid),
    INDEX idx_parking_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Parking availability sensor (free spaces)';

-- ---------------------------------------------------------------------------
-- Energy / metering
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS energy_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Electrical energy (kWh)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_energy_uuid     (uuid),
    INDEX idx_energy_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Electrical energy meter readings (kWh)';

CREATE TABLE IF NOT EXISTS submeter_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Sub-circuit energy (kWh)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_submeter_uuid     (uuid),
    INDEX idx_submeter_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Sub-metered electrical circuits (kWh)';

-- ---------------------------------------------------------------------------
-- Water
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS water_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Water volume (litres) or flow (L/min)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_water_uuid     (uuid),
    INDEX idx_water_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Water meter / flow sensor readings';

CREATE TABLE IF NOT EXISTS waterflow_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Water flow rate (L/min)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_waterflow_uuid     (uuid),
    INDEX idx_waterflow_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Water flow rate sensor readings (L/min)';

-- ---------------------------------------------------------------------------
-- Plant / BMS equipment
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS plant_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Varies by point: supply/return air temp (°C), fan state (0/1), damper position (%), filter dP (Pa), supply air flow (L/s), runtime (h)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_plant_uuid     (uuid),
    INDEX idx_plant_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='BMS/plant telemetry: AHU supply+return air temp, fan state, damper, filter dP, flow';

CREATE TABLE IF NOT EXISTS equipment_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE    COMMENT 'Equipment metric: vibration (mm/s) or AHU runtime (h)',
    PRIMARY KEY (uuid, datetime),
    INDEX idx_equipment_uuid     (uuid),
    INDEX idx_equipment_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Equipment metrics: vibration (mm/s), AHU runtime (h)';
