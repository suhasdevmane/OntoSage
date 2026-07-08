-- demo_seed.sql — seed for the Admin Console "Load demo database" rehearsal.
--
-- A throwaway external building database used to demonstrate the full
-- connect-external-DB flow (Add connection → Register sensors → answer) without
-- touching the real stores. Narrow schema (uuid, datetime, value) matches
-- OntoSage's mysql_narrow adapter. Runs only under `docker compose --profile demo`.
--
-- Two sensors with FIXED uuids so the matching sensor registration (returned by
-- GET /api/v1/admin/databases/demo-template) references the exact same ids:
--   aaaaaaaa-0000-4000-8000-000000000001  Temperature (deg C)
--   aaaaaaaa-0000-4000-8000-000000000002  Relative humidity (%)

USE demodb;

CREATE TABLE IF NOT EXISTS demo_readings (
  uuid     CHAR(36) NOT NULL,
  datetime DATETIME NOT NULL,
  value    DOUBLE   NULL,
  PRIMARY KEY (uuid, datetime),
  INDEX idx_uuid (uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A 0..47 numbers set via cross join (portable — avoids recursive-CTE quirks).
-- Temperature: 48 hourly points ending now.
INSERT IGNORE INTO demo_readings (uuid, datetime, value)
SELECT 'aaaaaaaa-0000-4000-8000-000000000001',
       NOW() - INTERVAL n HOUR,
       ROUND(21.0 + 2.5 * SIN(n / 3.8) + (RAND() - 0.5), 2)
FROM (
  SELECT (t.n * 10 + u.n) AS n
  FROM (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4) t
  CROSS JOIN (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
              UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) u
) nums
WHERE n < 48;

-- Relative humidity: 48 hourly points ending now.
INSERT IGNORE INTO demo_readings (uuid, datetime, value)
SELECT 'aaaaaaaa-0000-4000-8000-000000000002',
       NOW() - INTERVAL n HOUR,
       ROUND(45.0 + 8.0 * SIN(n / 5.1) + (RAND() - 0.5) * 2, 2)
FROM (
  SELECT (t.n * 10 + u.n) AS n
  FROM (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4) t
  CROSS JOIN (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
              UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) u
) nums
WHERE n < 48;
