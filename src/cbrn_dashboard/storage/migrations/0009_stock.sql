-- 0009_stock.sql: stock by lot of antidotes, decontaminants, detectors and protective equipment
-- (PLAN.md section 5.2, task T11.3, owner requests O01-O04, D32-D35, A16).
-- All tables are STRICT with integer primary keys (section 5.1). Money is stored as integers in the
-- minor unit of the currency (unit_price_minor), never as floating point. The quantity of a lot is
-- never stored: it is the signed sum of its dated movements (D33), the sign comes from the kind.
--
-- The database does not protect the built-in types from deletion or edits, does not check that a
-- date exists, does not restrict the currency to the allow-list and does not keep the balance of a
-- lot from going negative: those are service rules (tasks T11.5 and T11.6).
--
-- Like every schema or seed migration, this one writes no change_log rows.

-- What is kept in stock. The 17 built-in types are seeded below (O01); users can add their own.
-- Built-in names come from the translation catalogue, so the label columns stay NULL for them.
CREATE TABLE stock_item_type (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,                   -- seeded codes are upper snake case
    built_in    INTEGER NOT NULL DEFAULT 0 CHECK (built_in IN (0, 1)),
    category    TEXT NOT NULL                                              -- A16
        CHECK (category IN ('antidote', 'decontaminant', 'detector', 'ppe', 'other')),
    label_pt_br TEXT,
    label_en_us TEXT,
    label_es_es TEXT,
    minimum_quantity INTEGER                                               -- O04: NULL = not set
        CHECK (minimum_quantity IS NULL OR minimum_quantity >= 0),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
) STRICT;

-- One lot of one type. A type that has lots cannot be deleted (RESTRICT). Price and currency are
-- both set or both empty (D15).
CREATE TABLE stock_lot (
    id               INTEGER PRIMARY KEY,
    type_id          INTEGER NOT NULL REFERENCES stock_item_type (id) ON DELETE RESTRICT,
    lot_code         TEXT NOT NULL,
    -- ISO date shape YYYY-MM-DD; that the date exists is a service rule. NULL = no expiry date.
    expires_on       TEXT
        CHECK (expires_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    unit_price_minor INTEGER CHECK (unit_price_minor IS NULL OR unit_price_minor >= 0),
    -- ISO 4217 code shape (D15): three upper-case letters.
    currency         TEXT
        CHECK (currency IS NULL OR (length(currency) = 3 AND currency GLOB '[A-Z][A-Z][A-Z]')),
    notes            TEXT,
    CHECK ((unit_price_minor IS NULL) = (currency IS NULL)),
    UNIQUE (type_id, lot_code)                                 -- import natural key (T11.14)
) STRICT;

CREATE INDEX stock_lot_type_id_idx ON stock_lot (type_id);

-- Dated movements of a lot (D33). The quantity is always positive. Deleting a lot deletes its
-- movements. An empty reference is the empty string, not NULL, so the UNIQUE constraint also
-- holds without one.
CREATE TABLE stock_movement (
    id        INTEGER PRIMARY KEY,
    lot_id    INTEGER NOT NULL REFERENCES stock_lot (id) ON DELETE CASCADE,
    moved_on  TEXT NOT NULL
        CHECK (moved_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    kind      TEXT NOT NULL
        CHECK (kind IN ('receipt', 'issue', 'disposal', 'loss', 'adjustment_in', 'adjustment_out')),
    quantity  INTEGER NOT NULL CHECK (quantity > 0),
    reference TEXT NOT NULL DEFAULT '',
    note      TEXT,
    UNIQUE (lot_id, moved_on, kind, quantity, reference)       -- import natural key (T11.14)
) STRICT;

-- Built-in types (O01, A16). Their names come from the translation catalogue, so the label
-- columns and the minimum stay NULL.
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('ANTIDOTE_CHEMICAL', 1, 'antidote', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('ANTIDOTE_RAD_NUCLEAR', 1, 'antidote', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('ANTIDOTE_BIOLOGICAL', 1, 'antidote', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('DECONTAMINANT', 1, 'decontaminant', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('DETECTOR_CHEMICAL', 1, 'detector', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('DETECTOR_RAD_NUCLEAR', 1, 'detector', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('DETECTOR_BIOLOGICAL', 1, 'detector', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('MASK_FULL_FACE', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('FILTER_CBRN', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('PPE_LEVEL_A', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('PPE_LEVEL_B', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('PPE_LEVEL_C', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('GLOVE', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('BOOT', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('APRON', 1, 'ppe', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('OXYGEN_CYLINDER', 1, 'other', 1);
INSERT INTO stock_item_type (code, built_in, category, active)
VALUES ('ISOLATION_STRETCHER', 1, 'other', 1);
