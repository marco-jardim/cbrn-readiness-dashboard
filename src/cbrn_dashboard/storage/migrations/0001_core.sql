-- 0001_core.sql: the core tables every database has (PLAN.md section 5.2, D05, D06).
-- All tables are STRICT with integer primary keys (section 5.1).
--
-- app_meta is NOT seeded here. The keys is_demo and created_with are written by the service that
-- creates the database (tasks T1.7 and T1.9), because only that service knows whether the database
-- is the real one or the demo one.

-- Key/value facts about the database itself: is_demo, created_with.
CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- Application settings as JSON, for example the readiness configuration (P01..P09).
CREATE TABLE setting (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
) STRICT;

-- Append-only audit trail (D05). Rows are written by the repository helpers (task T1.4), one per
-- affected row, in the same transaction as the change they describe.
CREATE TABLE change_log (
    id          INTEGER PRIMARY KEY,
    at_utc      TEXT NOT NULL,                  -- ISO 8601 UTC, ending in Z (section 5.1)
    operator    TEXT NOT NULL DEFAULT '',       -- optional operator label (D05)
    entity      TEXT NOT NULL,
    entity_id   INTEGER,
    entity_key  TEXT,                           -- natural key as JSON, for tables without an integer id
    action      TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete', 'import', 'restore')),
    before_json TEXT,
    after_json  TEXT
) STRICT;

CREATE INDEX change_log_entity_idx ON change_log (entity, entity_id);

-- change_log is append-only (D05): neither UPDATE nor DELETE is ever allowed.
CREATE TRIGGER change_log_no_update BEFORE UPDATE ON change_log
BEGIN
    SELECT RAISE(ABORT, 'change_log is append-only');
END;

CREATE TRIGGER change_log_no_delete BEFORE DELETE ON change_log
BEGIN
    SELECT RAISE(ABORT, 'change_log is append-only');
END;

-- INSERT OR REPLACE / REPLACE INTO with an existing id would overwrite a log row; SQLite fires the
-- DELETE trigger for that implicit delete only when recursive_triggers is on, so refuse it here
-- (D05). A new row, with or without an explicit new id, is not affected.
CREATE TRIGGER change_log_no_replace BEFORE INSERT ON change_log
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM change_log WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'change_log is append-only');
END;
