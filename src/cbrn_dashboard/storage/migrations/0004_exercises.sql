-- 0004_exercises.sql: exercise editions, participating countries and evaluation results
-- (PLAN.md section 5.2, A07, A13, D20). All tables are STRICT (section 5.1).
--
-- evaluation_metric is NOT seeded (A07): the metrics are defined by the operator.
-- Participants are only counted, never identified (D20): there is no personal data here.

-- One edition of an exercise, for example one CBRAMED or EXBRAMED run.
CREATE TABLE exercise_edition (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL CHECK (kind IN ('CBRAMED', 'EXBRAMED', 'OTHER')),  -- L78, A13
    title        TEXT,
    start_on     TEXT NOT NULL,
    end_on       TEXT NOT NULL CHECK (end_on >= start_on),
    participants INTEGER CHECK (participants >= 0),                 -- L78, D20: NULL = not known
    notes        TEXT
) STRICT;

-- Countries that took part in an edition. The country code is ISO 3166-1 alpha-2 in upper case
-- (D20). The service validates it against the country list.
CREATE TABLE exercise_country (
    edition_id   INTEGER NOT NULL REFERENCES exercise_edition (id) ON DELETE CASCADE,
    country_code TEXT NOT NULL
                 CHECK (length(country_code) = 2 AND country_code GLOB '[A-Z][A-Z]'),
    PRIMARY KEY (edition_id, country_code)
) STRICT;

-- A metric used to evaluate editions (A07). label_pt_br is required by the service (D16).
CREATE TABLE evaluation_metric (
    id               INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    label_pt_br      TEXT,
    label_en_us      TEXT,
    label_es_es      TEXT,
    unit             TEXT,
    scale_min        REAL,
    scale_max        REAL,
    higher_is_better INTEGER NOT NULL DEFAULT 1 CHECK (higher_is_better IN (0, 1)),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    CHECK (scale_min IS NULL OR scale_max IS NULL OR scale_max >= scale_min)
) STRICT;

-- The value of one metric in one edition. A metric that has results cannot be deleted.
CREATE TABLE evaluation_result (
    edition_id  INTEGER NOT NULL REFERENCES exercise_edition (id) ON DELETE CASCADE,
    metric_id   INTEGER NOT NULL REFERENCES evaluation_metric (id) ON DELETE RESTRICT,
    value       REAL NOT NULL,
    respondents INTEGER CHECK (respondents IS NULL OR respondents >= 0),
    note        TEXT,
    PRIMARY KEY (edition_id, metric_id)
) STRICT;

-- Supports the RESTRICT check and "all results of one metric" lookups.
CREATE INDEX evaluation_result_metric_idx ON evaluation_result (metric_id);
