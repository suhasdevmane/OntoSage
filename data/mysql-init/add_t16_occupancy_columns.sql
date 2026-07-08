-- T16: Add occupancy feed UUID columns to sensor_data table
-- UUIDs are MD5("bldg1:occupancy_floor<N>") — see orchestrator/services/feeds/registry.py _derive_uuid()

ALTER TABLE sensordb.sensor_data
  ADD COLUMN IF NOT EXISTS `b3924812-a682-102c-7043-afb895b09834` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor0 (persons)',
  ADD COLUMN IF NOT EXISTS `aee0c240-0d57-b1d5-25b4-9504d2af5022` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor1 (persons)',
  ADD COLUMN IF NOT EXISTS `ba28c854-fca1-1aa5-c932-7a0a823631a9` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor2 (persons)',
  ADD COLUMN IF NOT EXISTS `72a0f3e2-192b-b4c2-a802-338fece27847` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor3 (persons)',
  ADD COLUMN IF NOT EXISTS `9c5f3063-7ee8-c9b8-869d-9ae59209b2c0` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor4 (persons)',
  ADD COLUMN IF NOT EXISTS `21c73c16-0764-4db1-e01f-3cbe234c9146` DECIMAL(6,0) DEFAULT NULL COMMENT 'occupancy_floor5 (persons)';
