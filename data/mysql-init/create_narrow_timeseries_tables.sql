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
