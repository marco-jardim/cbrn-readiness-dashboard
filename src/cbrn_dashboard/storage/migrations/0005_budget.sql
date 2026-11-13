-- 0005_budget.sql: funding sources, budget entries and dated budget execution
-- (PLAN.md section 5.2, task T5.1, A08, D15, D16, D27).
-- All tables are STRICT with integer primary keys (section 5.1). Money is stored as integers in the
-- minor unit of the currency (amount_minor), never as floating point.
--
-- The database does not protect the built-in funding sources from deletion or edits and does not
-- restrict the currency to the allow-list (BRL, USD, EUR): both are service rules (task T5.3, D15).

-- Where the money comes from. DIRSA and OPCW_TRUST_FUND are seeded below (L80, D16). Users can add
-- their own sources.
CREATE TABLE funding_source (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,               -- seeded: DIRSA, OPCW_TRUST_FUND (L80)
    built_in    INTEGER NOT NULL DEFAULT 0 CHECK (built_in IN (0, 1)),
    label_pt_br TEXT,
    label_en_us TEXT,
    label_es_es TEXT,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
) STRICT;

-- One allocation per fiscal year, source, currency and description. There is no executed_minor
-- column: execution is stored as dated budget_execution rows (A08).
CREATE TABLE budget_entry (
    id              INTEGER PRIMARY KEY,
    fiscal_year     INTEGER NOT NULL,                                  -- A08
    source_id       INTEGER NOT NULL REFERENCES funding_source (id) ON DELETE RESTRICT,
    -- ISO 4217 code shape (D15): three upper-case letters.
    currency        TEXT NOT NULL CHECK (length(currency) = 3 AND currency GLOB '[A-Z][A-Z][A-Z]'),
    allocated_minor INTEGER CHECK (allocated_minor IS NULL OR allocated_minor >= 0),  -- D27
    description     TEXT NOT NULL DEFAULT '',                          -- an empty description is ''
    notes           TEXT,
    UNIQUE (fiscal_year, source_id, currency, description)             -- import natural key (T8.4)
) STRICT;

-- A08: execution is dated, so it can be read as of any date. The UNIQUE constraint below also
-- serves lookups by (entry_id, executed_on), so there is no separate index.
CREATE TABLE budget_execution (
    id           INTEGER PRIMARY KEY,
    entry_id     INTEGER NOT NULL REFERENCES budget_entry (id) ON DELETE CASCADE,
    executed_on  TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),           -- D27
    note         TEXT,
    UNIQUE (entry_id, executed_on, amount_minor)                       -- import natural key (T8.4)
) STRICT;

-- Built-in funding sources (L80, D16). Their names come from labels.py, so the label columns stay NULL.
INSERT INTO funding_source (code, built_in, active) VALUES ('DIRSA', 1, 1);
INSERT INTO funding_source (code, built_in, active) VALUES ('OPCW_TRUST_FUND', 1, 1);
