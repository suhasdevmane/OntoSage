-- T17: Add per-floor energy submeter UUID columns to sensor_data table
-- UUIDs are MD5("bldg1:energy_meter_floor<N>") — see orchestrator/services/feeds/registry.py _derive_uuid()
-- Values are kWh per hour (DECIMAL(8,3) to accommodate fractional kWh).

ALTER TABLE sensordb.sensor_data
  ADD COLUMN IF NOT EXISTS `56c3107a-8b03-c759-48e6-1f2909aac0be` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor0 (kWh)',
  ADD COLUMN IF NOT EXISTS `f00327c3-dd72-a502-abce-eeb7f8b80eec` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor1 (kWh)',
  ADD COLUMN IF NOT EXISTS `f1d029c9-0de0-1f7e-334e-cdf629c6bbbe` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor2 (kWh)',
  ADD COLUMN IF NOT EXISTS `2cc9ee2b-9d5a-ed5d-212c-e0d8d5d75be9` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor3 (kWh)',
  ADD COLUMN IF NOT EXISTS `fbb4943d-63c9-b06d-2eea-1aba7c8bed73` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor4 (kWh)',
  ADD COLUMN IF NOT EXISTS `632c8450-569c-00e5-aa3f-fb5ba8bda3e4` DECIMAL(8,3) DEFAULT NULL COMMENT 'energy_meter_floor5 (kWh)';
