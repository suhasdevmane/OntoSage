-- V5-T07: the generic S2 interval/event store — ONE table per building DB holds
-- every IntervalRecord subtype (booking / workorder / access / alarm /
-- compliance / anomaly:<detector>). Vocabulary: ontology/ontosage_schema.ttl
-- Module J; attrs JSON keys per type: tasks/V5_OCBV2_DELTA_SPEC.md.
-- Idempotent: CREATE IF NOT EXISTS, safe to run on every building DB.

CREATE TABLE IF NOT EXISTS events (
    event_id     CHAR(36)     NOT NULL,
    event_type   VARCHAR(64)  NOT NULL,
    subject_uuid CHAR(36)     NOT NULL,
    start_dt     DATETIME     NOT NULL,
    end_dt       DATETIME     NULL,       -- NULL = ongoing / open-ended
    status       VARCHAR(32)  NOT NULL DEFAULT 'open',
    attrs        JSON         NULL,
    PRIMARY KEY (event_id),
    INDEX idx_events_type_start   (event_type, start_dt),
    INDEX idx_events_subject      (subject_uuid, start_dt),
    INDEX idx_events_type_status  (event_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='S2 interval records (V5 Event Framework)';
