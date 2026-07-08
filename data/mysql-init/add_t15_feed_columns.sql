-- T15: Add MySQL column for energy_tariff feed UUID (bldg1)
-- UUIDs are deterministic: MD5("bldg1:<feed_id>")
-- Run: docker exec -i abacws-mysql mysql -u root -p<password> sensordb < add_t15_feed_columns.sql

ALTER TABLE sensor_data
  ADD COLUMN IF NOT EXISTS `1acbd253-0f12-f875-38d3-427aed45127e` DECIMAL(6,4) NULL
    COMMENT 'energy_tariff';
