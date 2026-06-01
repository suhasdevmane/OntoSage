-- ============================================================================
-- OntoSage Phase 19 - Admin triage views for the unified user-report intake.
--
-- These views sit on top of the `user_reports` table in the postgres-user-data
-- database (the same DB pgAdmin connects to on port 5050).  An administrator
-- opens pgAdmin, expands ontobot -> Schemas -> public -> Views, and double-clicks
-- any of these to triage incoming complaints / faults / safety reports without
-- writing SQL.
--
-- The orchestrator auto-creates these on startup (Phase 19 lifespan), so you
-- normally do not need to run this file by hand.  It is kept here as the
-- canonical definition and for manual (re)creation:
--
--     docker exec -i postgres-user-data psql -U ontobot -d ontobot \
--         < scripts/sql/report_admin_views.sql
--
-- To ACT on a report, edit the row directly in pgAdmin (or run an UPDATE):
--     UPDATE user_reports
--        SET status='IN_PROGRESS', assignee='facilities', admin_notes='dispatched'
--      WHERE id='REP-XXXXXX';
-- Setting status='RESOLVED' should also set resolved_at = NOW() (the app does
-- this automatically when resolving through the service).
-- ============================================================================

-- 1. All OPEN / in-flight reports, URGENT first, then newest.
CREATE OR REPLACE VIEW v_open_reports AS
SELECT id, created_at, building_id, category, priority, status,
       persona, title, location, device, reporter_id, assignee
FROM user_reports
WHERE status NOT IN ('RESOLVED', 'CLOSED', 'REJECTED')
ORDER BY CASE priority
            WHEN 'URGENT' THEN 0
            WHEN 'HIGH'   THEN 1
            WHEN 'NORMAL' THEN 2
            ELSE 3
         END,
         created_at DESC;

-- 2. URGENT + HIGH not yet being worked on - the "act now" queue (oldest first).
CREATE OR REPLACE VIEW v_urgent_reports AS
SELECT id, created_at, building_id, category, priority, status,
       persona, title, location, device, reporter_id
FROM user_reports
WHERE priority IN ('URGENT', 'HIGH')
  AND status IN ('OPEN', 'ACKNOWLEDGED')
ORDER BY CASE priority WHEN 'URGENT' THEN 0 ELSE 1 END,
         created_at ASC;

-- 3. Counts grouped by persona - who is reporting issues, and of what kind.
CREATE OR REPLACE VIEW v_reports_by_persona AS
SELECT COALESCE(persona, '(unknown)') AS persona,
       category,
       COUNT(*)                         AS total,
       COUNT(*) FILTER (WHERE status NOT IN ('RESOLVED','CLOSED','REJECTED')) AS open_count,
       MAX(created_at)                  AS latest
FROM user_reports
GROUP BY COALESCE(persona, '(unknown)'), category
ORDER BY total DESC;

-- 4. Counts grouped by category + status - the triage dashboard.
CREATE OR REPLACE VIEW v_reports_by_category AS
SELECT category, status, priority, COUNT(*) AS total, MAX(created_at) AS latest
FROM user_reports
GROUP BY category, status, priority
ORDER BY category, status;

-- 5. Resolution SLA - how long resolved reports took, by category.
CREATE OR REPLACE VIEW v_reports_resolution_time AS
SELECT category,
       COUNT(*)                                                   AS resolved_count,
       ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0)::numeric, 1)
                                                                  AS avg_hours_to_resolve,
       ROUND(MAX(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0)::numeric, 1)
                                                                  AS max_hours_to_resolve
FROM user_reports
WHERE status = 'RESOLVED' AND resolved_at IS NOT NULL
GROUP BY category
ORDER BY avg_hours_to_resolve DESC;
