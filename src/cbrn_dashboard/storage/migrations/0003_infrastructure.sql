-- 0003_infrastructure.sql: assets, their status history and their maintenance (PLAN.md section 5.2,
-- task T3.1, A05, A06, D16). All tables are STRICT with integer primary keys (section 5.1).
--
-- The database does not protect the built-in asset types: that rule (a built-in type cannot be
-- deleted or have its code changed) belongs to the service (task T3.3), not to a trigger.

-- Asset types. The four built-in ones are seeded below; users may add their own (D16).
CREATE TABLE asset_type (
    id   INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    built_in INTEGER NOT NULL DEFAULT 0 CHECK (built_in IN (0, 1)),  -- seeded: bed, bay, neg_pressure_filtration, decon_tent (L76)
    label_pt_br TEXT,                           -- required for non-built-in rows (service, D16)
    label_en_us TEXT,
    label_es_es TEXT,
    default_maintenance_interval_days INTEGER
        CHECK (default_maintenance_interval_days >= 0),  -- NULL = not set; 0 = no scheduled maintenance (A06)
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
) STRICT;

-- Built-in types mirror the wording of L76 (D16). Their label columns stay empty (NULL): their
-- names come from labels.py. The default maintenance interval is not set (A06).
INSERT INTO asset_type (code, built_in, active) VALUES ('bed', 1, 1);
INSERT INTO asset_type (code, built_in, active) VALUES ('bay', 1, 1);
INSERT INTO asset_type (code, built_in, active) VALUES ('neg_pressure_filtration', 1, 1);
INSERT INTO asset_type (code, built_in, active) VALUES ('decon_tent', 1, 1);

-- One row per physical asset. A type that has assets cannot be deleted (RESTRICT).
CREATE TABLE asset (
    id          INTEGER PRIMARY KEY,
    type_id     INTEGER NOT NULL REFERENCES asset_type (id) ON DELETE RESTRICT,
    tag         TEXT NOT NULL UNIQUE,
    description TEXT,
    location    TEXT,
    in_service_from  TEXT NOT NULL
        CHECK (in_service_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    in_service_until TEXT
        CHECK (in_service_until GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    maintenance_interval_days INTEGER
        CHECK (maintenance_interval_days >= 0),  -- overrides the type default; 0 = no scheduled maintenance (A06)
    notes TEXT,
    CHECK (in_service_until IS NULL OR in_service_until >= in_service_from)  -- ISO text sorts as dates
) STRICT;

CREATE INDEX asset_type_id_idx ON asset (type_id);

-- Status history of an asset: one event per asset and day.
CREATE TABLE asset_status_event (
    id           INTEGER PRIMARY KEY,
    asset_id     INTEGER NOT NULL REFERENCES asset (id) ON DELETE CASCADE,
    effective_on TEXT NOT NULL
        CHECK (effective_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status       TEXT NOT NULL CHECK (status IN ('operational', 'degraded', 'out_of_service')),  -- A05
    note         TEXT,
    UNIQUE (asset_id, effective_on)
) STRICT;

-- Maintenance performed on an asset.
CREATE TABLE maintenance_event (
    id           INTEGER PRIMARY KEY,
    asset_id     INTEGER NOT NULL REFERENCES asset (id) ON DELETE CASCADE,
    performed_on TEXT NOT NULL                                       -- L76
        CHECK (performed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    kind         TEXT NOT NULL CHECK (kind IN ('preventive', 'corrective', 'inspection')),
    next_due_on  TEXT
        CHECK (next_due_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    note         TEXT,
    CHECK (next_due_on IS NULL OR next_due_on >= performed_on),
    UNIQUE (asset_id, performed_on, kind)                            -- import natural key (T8.4)
) STRICT;
