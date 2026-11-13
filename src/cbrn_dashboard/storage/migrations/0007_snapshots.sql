-- 0007_snapshots.sql: readiness snapshots (PLAN.md section 5.2, task T8.1, D13, D21, R31, K13).
-- A snapshot is the ONLY record of what was known and configured at the time (D13): the value,
-- the status and the targets in force of every indicator and dimension, with the application
-- version, the configuration hash and the hashed configuration itself.
--
-- All three tables are STRICT and APPEND-ONLY. A snapshot is never updated and never deleted
-- (K13): a snapshot that must not count is WITHDRAWN by appending a snapshot_withdrawal row with
-- a reason. Each table has a BEFORE UPDATE and a BEFORE DELETE trigger that abort, and a BEFORE
-- INSERT trigger that refuses a row whose key already exists, so INSERT OR REPLACE cannot
-- overwrite evidence either (the lesson of change_log_no_replace in 0001).
--
-- origin is decided by the service, not here: it is retroactive whenever the local date on which
-- the snapshot is taken is after as_of, whatever triggered it (K13, services/snapshots.py).
-- indicator_code refers to the code registry, not to a table, so there is no foreign key.
-- This migration creates new tables only. It is not a table rebuild.

CREATE TABLE readiness_snapshot (
    id            INTEGER PRIMARY KEY,
    taken_at_utc  TEXT NOT NULL,                -- ISO 8601 UTC, ending in Z (section 5.1)
    as_of         TEXT NOT NULL,                -- ISO date the readings are for
    origin        TEXT NOT NULL CHECK (origin IN ('manual', 'monthly', 'report', 'retroactive')),
    app_version   TEXT NOT NULL,
    config_hash   TEXT NOT NULL,                -- SHA-256 hex of config_json
    config_json   TEXT NOT NULL,                -- exactly the fields that were hashed (T8.1)
    note          TEXT
) STRICT;

CREATE INDEX readiness_snapshot_as_of_idx ON readiness_snapshot (as_of);

CREATE TABLE readiness_snapshot_value (
    snapshot_id    INTEGER NOT NULL REFERENCES readiness_snapshot (id) ON DELETE RESTRICT,
    indicator_code TEXT NOT NULL,
    dimension      TEXT NOT NULL DEFAULT '',
    value          REAL,                        -- NULL when the indicator has no data
    status         TEXT NOT NULL,
    warning_value  REAL,                        -- the targets in force when the snapshot was taken
    critical_value REAL,
    PRIMARY KEY (snapshot_id, indicator_code, dimension)
) STRICT;

CREATE TABLE snapshot_withdrawal (
    id               INTEGER PRIMARY KEY,
    snapshot_id      INTEGER NOT NULL UNIQUE REFERENCES readiness_snapshot (id) ON DELETE RESTRICT,
    withdrawn_at_utc TEXT NOT NULL,
    reason           TEXT NOT NULL CHECK (length(reason) > 0),
    operator         TEXT NOT NULL DEFAULT ''
) STRICT;

-- readiness_snapshot: append-only.
CREATE TRIGGER readiness_snapshot_no_update BEFORE UPDATE ON readiness_snapshot
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot is append-only');
END;

CREATE TRIGGER readiness_snapshot_no_delete BEFORE DELETE ON readiness_snapshot
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot is append-only');
END;

CREATE TRIGGER readiness_snapshot_no_replace BEFORE INSERT ON readiness_snapshot
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM readiness_snapshot WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot is append-only');
END;

-- readiness_snapshot_value: append-only.
CREATE TRIGGER readiness_snapshot_value_no_update BEFORE UPDATE ON readiness_snapshot_value
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot_value is append-only');
END;

CREATE TRIGGER readiness_snapshot_value_no_delete BEFORE DELETE ON readiness_snapshot_value
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot_value is append-only');
END;

CREATE TRIGGER readiness_snapshot_value_no_replace BEFORE INSERT ON readiness_snapshot_value
WHEN EXISTS (
    SELECT 1 FROM readiness_snapshot_value
    WHERE snapshot_id = NEW.snapshot_id
      AND indicator_code = NEW.indicator_code
      AND dimension = NEW.dimension
)
BEGIN
    SELECT RAISE(ABORT, 'readiness_snapshot_value is append-only');
END;

-- snapshot_withdrawal: append-only. A snapshot is withdrawn once, so the replace guard also
-- covers the UNIQUE snapshot_id, which INSERT OR REPLACE would otherwise resolve by deleting the
-- earlier withdrawal.
CREATE TRIGGER snapshot_withdrawal_no_update BEFORE UPDATE ON snapshot_withdrawal
BEGIN
    SELECT RAISE(ABORT, 'snapshot_withdrawal is append-only');
END;

CREATE TRIGGER snapshot_withdrawal_no_delete BEFORE DELETE ON snapshot_withdrawal
BEGIN
    SELECT RAISE(ABORT, 'snapshot_withdrawal is append-only');
END;

CREATE TRIGGER snapshot_withdrawal_no_replace BEFORE INSERT ON snapshot_withdrawal
WHEN (NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM snapshot_withdrawal WHERE id = NEW.id))
  OR EXISTS (SELECT 1 FROM snapshot_withdrawal WHERE snapshot_id = NEW.snapshot_id)
BEGIN
    SELECT RAISE(ABORT, 'snapshot_withdrawal is append-only');
END;
