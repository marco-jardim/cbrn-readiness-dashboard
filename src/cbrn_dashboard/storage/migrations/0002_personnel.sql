-- 0002_personnel.sql: personnel tables (PLAN.md section 5.2, task T2.1, D17, D24, A04, A09, A10).
-- All tables are STRICT with integer primary keys (section 5.1). There are no free-text notes
-- columns on staff_member, ppe_certification or training_record (D17).
--
-- training_course is NOT seeded: the course list starts empty and the unit defines its own
-- courses (A09).

-- A person is identified by an internal code, never by a national ID or a service number (D17).
CREATE TABLE staff_member (
    id           INTEGER PRIMARY KEY,
    identifier   TEXT NOT NULL UNIQUE,      -- internal code, never a national ID (D17)
    label        TEXT,                      -- optional short label
    category     TEXT,                      -- configurable list (Q4)
    active_from  TEXT NOT NULL,             -- one active interval; a returning person is a new record (A14)
    active_until TEXT
) STRICT;

-- Personal protective equipment (PPE) certification (L74).
CREATE TABLE ppe_certification (
    id                INTEGER PRIMARY KEY,
    staff_id          INTEGER NOT NULL REFERENCES staff_member (id) ON DELETE CASCADE,
    ppe_level         TEXT NOT NULL CHECK (ppe_level IN ('A', 'B', 'C')),   -- L74
    issued_on         TEXT NOT NULL,
    valid_until       TEXT NOT NULL CHECK (valid_until >= issued_on),       -- A04
    no_renewal_from   TEXT,                 -- D24: NULL = renewal expected; the flag applies from this date
    no_renewal_reason TEXT CHECK (no_renewal_reason IN ('left_unit', 'role_change', 'other')),
    reference         TEXT,                 -- hint: no names, health or contact data
    UNIQUE (staff_id, ppe_level, issued_on) -- import natural key (T8.4)
) STRICT;

CREATE INDEX ppe_certification_staff_idx ON ppe_certification (staff_id);

-- User-defined course list (D16); code and the three label columns follow section 5.1.
CREATE TABLE training_course (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    label_pt_br TEXT,
    label_en_us TEXT,
    label_es_es TEXT,
    active      INTEGER NOT NULL DEFAULT 1
) STRICT;

-- A completed course of one staff member (A09).
CREATE TABLE training_record (
    id           INTEGER PRIMARY KEY,
    staff_id     INTEGER NOT NULL REFERENCES staff_member (id) ON DELETE CASCADE,
    course_id    INTEGER NOT NULL REFERENCES training_course (id) ON DELETE RESTRICT,
    completed_on TEXT NOT NULL,
    hours        REAL,
    UNIQUE (staff_id, course_id, completed_on)  -- import natural key (T8.4)
) STRICT;

CREATE INDEX training_record_course_idx ON training_record (course_id);

CREATE TABLE academic_degree (
    id       INTEGER PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES staff_member (id) ON DELETE CASCADE,
    level    TEXT NOT NULL CHECK (level IN ('specialisation', 'master', 'doctorate')),  -- L74
    status   TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'in_progress')),  -- A10
    year     INTEGER,
    field    TEXT
) STRICT;

-- Import natural key (T8.4); NULLs compare as distinct in UNIQUE, hence COALESCE. The index also
-- serves lookups by staff_id, because staff_id is its leading column.
CREATE UNIQUE INDEX academic_degree_key
    ON academic_degree (staff_id, level, COALESCE(field, ''), COALESCE(year, 0));
