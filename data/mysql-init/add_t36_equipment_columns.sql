-- T36: Equipment health telemetry columns
-- Column names are the FULL feed UUIDs as written by the feed adapter:
--   MD5("bldg1:<feed_id>") formatted 8-4-4-4-12 (see feeds/registry.py _derive_uuid()).
--   lift_vibration_floor0  -> 76fa0eed-da96-2ea5-b9ec-447fa7ae3989
--   ahu_runtime_floor5     -> 0fa68f99-b446-5ea9-4813-96d9016cb6d9
-- NOTE: plain ADD COLUMN (MySQL 8 does not support ADD COLUMN IF NOT EXISTS).

ALTER TABLE sensordb.sensor_data
  ADD COLUMN `76fa0eed-da96-2ea5-b9ec-447fa7ae3989` DECIMAL(5,2) COMMENT 'Lift vibration mm/s RMS — LIFT-01 (lift_vibration_floor0)',
  ADD COLUMN `0fa68f99-b446-5ea9-4813-96d9016cb6d9` DECIMAL(4,3) COMMENT 'AHU runtime h/h fraction — AHU-F5 (ahu_runtime_floor5)';
