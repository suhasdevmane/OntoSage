-- Workstream B: Narrow per-modality time-series tables
-- Schema: (uuid CHAR(36), datetime DATETIME, value DOUBLE)
-- One table per sensor modality; reached from the ontology via
--   ref:storedAt bldg:<table>  (see input/database_registry.yaml)
-- UUIDs are sourced from input/bldg1_timeseries_extension_uuids.json
-- and registered in input/bldg1_timeseries_extension.ttl.

USE sensordb;

CREATE TABLE IF NOT EXISTS energy_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_energy_uuid     (uuid),
    INDEX idx_energy_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Electrical energy (kWh) — 6 floors';

CREATE TABLE IF NOT EXISTS occupancy_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_occupancy_uuid     (uuid),
    INDEX idx_occupancy_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Occupancy count (persons) — 6 floors';

CREATE TABLE IF NOT EXISTS water_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_water_uuid     (uuid),
    INDEX idx_water_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Water flow (L/min) — main supply';

CREATE TABLE IF NOT EXISTS noise_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_noise_uuid     (uuid),
    INDEX idx_noise_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Noise level (dB) — floor 5';

CREATE TABLE IF NOT EXISTS iaq_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_iaq_uuid     (uuid),
    INDEX idx_iaq_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IAQ: PM2.5 (ug/m3) and TVOC (ppb) — floor 3';

CREATE TABLE IF NOT EXISTS light_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_light_uuid     (uuid),
    INDEX idx_light_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Illuminance (lux) — floor 5';

CREATE TABLE IF NOT EXISTS equipment_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_equipment_uuid     (uuid),
    INDEX idx_equipment_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Equipment metrics: vibration (mm/s), AHU runtime (h)';

-- ============================================================================
-- V6-T26: tables that existed only in the live database until 2026-08-24.
--
-- plant_data is new. The other three were created by earlier SATURATE work
-- directly against MySQL and never written down here, so a fresh clone ran
-- create_narrow_timeseries_tables.sql and still could not answer the questions
-- their registry entries promised. Both halves of design contract #8 are
-- required -- a triple in the graph AND rows in a registered store -- and a DDL
-- that omits the table breaks the half nobody notices until a new deployment.
-- ============================================================================

-- BMS/plant telemetry: supply+return air temp (degC), fan state (0/1), damper position (%), filter dP (Pa), supply air flow (L/s)
CREATE TABLE IF NOT EXISTS plant_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_plant_uuid     (uuid),
    INDEX idx_plant_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='BMS/plant telemetry: supply+return air temp (degC), fan state (0/1), damper position (%), filter dP (Pa), supply air flow (L/s)';

-- Door and window contact state (0=closed, 1=open)
CREATE TABLE IF NOT EXISTS contact_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_contact_uuid     (uuid),
    INDEX idx_contact_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Door and window contact state (0=closed, 1=open)';

-- Sub-metered electrical circuits (kWh)
CREATE TABLE IF NOT EXISTS submeter_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_submeter_uuid     (uuid),
    INDEX idx_submeter_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Sub-metered electrical circuits (kWh)';

-- Water flow rate (L/min)
CREATE TABLE IF NOT EXISTS waterflow_data (
    uuid     CHAR(36)  NOT NULL,
    datetime DATETIME  NOT NULL,
    value    DOUBLE,
    PRIMARY KEY (uuid, datetime),
    INDEX idx_waterflow_uuid     (uuid),
    INDEX idx_waterflow_datetime (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Water flow rate (L/min)';
