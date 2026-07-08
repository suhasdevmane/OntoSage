-- T18: IAQ / Noise / Light / Water feed columns
-- Column names are the FULL feed UUIDs as written by the feed adapter:
--   MD5("bldg1:<feed_id>") formatted 8-4-4-4-12 (see feeds/registry.py _derive_uuid()).
--   iaq_pm25_floor3   -> 4e483458-f410-04a7-f3a8-a27d1c170c75
--   iaq_voc_floor3    -> 275b27d7-f498-1e4c-4882-659570bbc3e9
--   noise_floor5      -> 38593f4e-edff-f8fd-c6de-02e09b01796b
--   light_floor5      -> 4ca62679-af5e-d0ad-b6c9-d686a6e9197c
--   water_main        -> 0ce63224-2bf9-2317-1ff2-915cf3e07975
-- NOTE: plain ADD COLUMN (MySQL 8 does not support ADD COLUMN IF NOT EXISTS).
-- Re-running on an already-migrated table errors harmlessly with "Duplicate column".

ALTER TABLE sensordb.sensor_data
  ADD COLUMN `4e483458-f410-04a7-f3a8-a27d1c170c75` DECIMAL(6,2) COMMENT 'PM2.5 ug/m3 — Floor 3 (iaq_pm25_floor3)',
  ADD COLUMN `275b27d7-f498-1e4c-4882-659570bbc3e9` DECIMAL(7,1) COMMENT 'TVOC ppb — Floor 3 (iaq_voc_floor3)',
  ADD COLUMN `38593f4e-edff-f8fd-c6de-02e09b01796b` DECIMAL(5,1) COMMENT 'Noise dB — Floor 5 (noise_floor5)',
  ADD COLUMN `4ca62679-af5e-d0ad-b6c9-d686a6e9197c` DECIMAL(7,1) COMMENT 'Illuminance lux — Floor 5 (light_floor5)',
  ADD COLUMN `0ce63224-2bf9-2317-1ff2-915cf3e07975` DECIMAL(6,3) COMMENT 'Water flow L/min — Building main (water_main)';
