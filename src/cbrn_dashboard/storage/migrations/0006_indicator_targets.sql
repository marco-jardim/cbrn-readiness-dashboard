-- 0006_indicator_targets.sql: warning and critical values per indicator and dimension
-- (PLAN.md section 5.2, task T6.1, D14, P03).
-- The table is STRICT and is created EMPTY on purpose: no readiness standard is invented (P03).
-- Real targets are entered in Settings and never become code defaults, so an indicator without a
-- row here reads "No target" (D14).
--
-- indicator_code refers to the code registry (domain/registry.py), not to a table, so there is no
-- foreign key. The dimension is the sorted key=value text of section 5.4 ('' when the indicator
-- has no dimension). Whether a code is registered, whether the dimension fits the indicator and
-- whether warning and critical are in the right order for its direction are service rules
-- (services/indicators.py), not database constraints. A NULL threshold means "not set".

CREATE TABLE indicator_target (
    indicator_code TEXT NOT NULL,
    dimension      TEXT NOT NULL DEFAULT '',
    warning_value  REAL,
    critical_value REAL,
    enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    PRIMARY KEY (indicator_code, dimension)
) STRICT;
