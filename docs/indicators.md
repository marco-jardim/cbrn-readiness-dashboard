# Indicator reference

Every indicator the application computes, the rule behind it, and every placeholder value of the
readiness configuration with the open question it waits for. The text is written by hand and
**checked against the code** by `tests/meta/test_docs.py`: the set of indicator codes, and for each
one its module, unit, direction, dimension keys, source and proposal flag, must equal the registry in
`src/cbrn_dashboard/domain/registry.py`; every placeholder of `src/cbrn_dashboard/domain/config.py`
must have a row in the placeholder table. A new indicator without an entry here fails that test.

**Preliminary version — indicators not institutionally validated.** The indicator list is a design
proposal that the committee has not confirmed (Q1). All examples in this repository are
fictitious; demo records start with `DEMO`.

## How an indicator is computed

- **As-of date.** An indicator is evaluated for a chosen date, past or present, from the dated
  records as known today and with the current configuration. Only a snapshot records what was
  known and configured at the time. Time comes from an injected clock, never from the rules.
- **Dimension.** An indicator may be split into several values by a dimension, for example the PPE
  level or the funding source. A dimension with several keys is encoded as sorted
  `key=value;key=value` text built from codes, for example `currency=BRL;source=DEMO-SRC`; an
  indicator without dimension uses the empty text. A target is stored per
  (indicator code, dimension) and never falls back to another dimension.
- **Pure rules.** The rules live in `domain/` as functions of the as-of date and plain records.
  Each rule exists once and is reused by the indicators, the lists and the alerts, so the numbers
  on the dashboard, in the lists and in the alerts cannot disagree.
- **Codes, not text.** The domain returns codes and numbers; the interface turns them into words.

### Statuses

| Status | Meaning |
|---|---|
| `OK`, `WARNING`, `CRITICAL` | a target exists and the value is on that side of it |
| `NO_TARGET` | no enabled target with at least one value: the default (P03) |
| `NO_DATA` | the value cannot be computed (checked first, even without a target) |

A target holds a warning value and a critical value; either may be missing. Both thresholds are
inclusive: a threshold is the last value of the worse band.

| Direction | `CRITICAL` when | `WARNING` when (and not critical) |
|---|---|---|
| `HIGHER_IS_BETTER` | value ≤ critical value | value ≤ warning value |
| `LOWER_IS_BETTER` | value ≥ critical value | value ≥ warning value |

For example, higher is better with warning 5 and critical 2: 6 is OK, 5 and 3 are WARNING, 2 and 0
are CRITICAL. A target is refused when its two values are in the wrong order for the direction.

**No composite readiness score is computed.** Its formula would be an invented domain fact (Q9).
The "reading" stored in a snapshot is the full set of indicator values and statuses.

**No default targets.** Targets (P03) are entered per installation in Settings and never become
code defaults. The demo database holds illustrative targets that exist only there.

## Indicators

Each entry lists: the owning module, the unit kind, the direction, the dimension keys, the source
(the requirement codes `R..` of PLAN.md section 3.1 and the assumptions `A..` of section 3.5,
exactly as the registry holds them), the appendix line of the requirement (`L..`; the appendix
itself is not in the repository, Q18), whether the indicator is a design proposal, and the default
target.

### `PERS_CERT_VALID`

- Module: `PERSONNEL`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `level`
- Source: `R14`
- Appendix line: L74
- Proposal: none
- Default target: none (P03)
- Definition: the number of active staff whose counting PPE qualification at the level is valid on
  the as-of date (`valid_until` on or after the date). The dimension `level` is `A`, `B` or `C`.
  A person counts once per level.

The *counting qualification* (assumption A03) is, for a person, a level and a date, the PPE
qualification with the latest `valid_until` among those that count for the level and were issued on
or before the date (ties: later `issued_on`, then higher id). A PPE qualification is a practical
qualification in donning and doffing the protective ensemble of a level, with a valid-until date;
the levels classify ensembles, not people. A qualification issued after the date never hides the
one that was valid on it. Levels are counted independently unless the hierarchy switch (A02) is on.
*Active* means the person's single active interval contains the date, both ends inclusive.

### `PERS_CERT_EXPIRING`

- Module: `PERSONNEL`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `level`
- Source: `R15, R25`
- Appendix line: L74, L82
- Proposal: none
- Default target: none (P03)
- Definition: the number of active staff whose counting qualification at the level is valid on the
  date, expires within the warning window (P01, 90 days by default, inclusive) and is not marked
  "no renewal" on the date. Dimension `level`: `A`, `B`, `C`.

### `PERS_RETRAINING_NEEDED`

- Module: `PERSONNEL`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `level`
- Source: `R15, R36`
- Appendix line: L74, L95
- Proposal: none
- Default target: none (P03)
- Definition: the number of active staff whose counting qualification at the level has expired or
  expires within the warning window (P01), and is not marked "no renewal" on the date. A person
  with no qualification at the level is not counted: there is nothing to renew. Dimension `level`:
  `A`, `B`, `C`.

### `PERS_DEGREE`

- Module: `PERSONNEL`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `level`, `status`
- Source: `R16`
- Appendix line: L74
- Proposal: none
- Default target: none (P03)
- Definition: the number of active staff with a degree at the degree level and status. Here
  `level` is the degree level (`specialisation`, `master`, `doctorate`), not the PPE level, and
  `status` is `completed` or `in_progress`. A person counts once per (level, status). A completed
  degree with a recorded year after the as-of year is not counted on that date; degrees without a
  year, and degrees in progress, always count.

### `PERS_TRAINING_12M`

- Module: `PERSONNEL`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: none
- Source: `R16, A09`
- Appendix line: L74
- Proposal: none
- Default target: none (P03)
- Definition: the number of training records of staff active on the date whose completion date lies
  in the 12 months before it (start exclusive, end inclusive). "Training" is the dated completion
  of a course from the editable course list (A09).

### `INFRA_AVAILABLE`

- Module: `INFRASTRUCTURE`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `type`
- Source: `R17-R19, A01, A05`
- Appendix line: L76
- Proposal: none
- Default target: none (P03)
- Definition: per asset type (the dimension `type` is the type code), the number of assets in
  service on the date whose status on the date is `operational`. The status is that of the latest
  status event dated on or before the date; with no such event it is `unknown`, which is not
  available and is reported as a data-quality issue. `degraded` counts as available only when the
  switch of A05 is on (off by default). "Available" means in service and working, not free at a
  given moment: no occupancy is tracked (A01). The total of assets in service is carried beside the
  value as context.

### `INFRA_MAINT_OVERDUE`

- Module: `INFRASTRUCTURE`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `type`
- Source: `R20, R26`
- Appendix line: L76, L82
- Proposal: none
- Default target: none (P03)
- Definition: per asset type, the number of assets in service whose maintenance due date is before
  the date. The due date follows A06, using only maintenance performed on or before the date:
  (1) the `next_due_on` of the latest maintenance that records one, which always wins; otherwise
  (2) an effective interval of 0 means "no scheduled maintenance" and there is no due date;
  otherwise (3) with a positive interval, the latest preventive maintenance (or the in-service
  date) plus the interval; otherwise (4) the schedule is unknown. The effective interval is the
  asset's own, else its type's default.

### `EX_LAST_PARTICIPANTS`

- Module: `EXERCISES`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `kind`
- Source: `R22`
- Appendix line: L78
- Proposal: none
- Default target: none (P03)
- Definition: the number of participants of the latest finished edition of the kind. An edition is
  finished for a date when its end date is on or before it; the latest is the one with the
  greatest end date (ties: greater start date, then greater code). The dimension `kind` is
  `CBRAMED`, `EXBRAMED` or `OTHER`; there is always one value per kind. The value is missing
  (`NO_DATA`) when there is no finished edition or no participant count was recorded.

### `EX_LAST_COUNTRIES`

- Module: `EXERCISES`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `kind`
- Source: `R22`
- Appendix line: L78
- Proposal: none
- Default target: none (P03)
- Definition: the number of countries represented in that same latest finished edition of the
  kind. An edition saved with no countries gives `NO_DATA`: "not entered" is not "zero countries".

### `EX_DAYS_SINCE_LAST`

- Module: `EXERCISES`
- Unit: `DAYS`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `kind`
- Source: `R05`
- Appendix line: L61
- Proposal: `Q1` — a design proposal, not stated in the appendix; it needs the answer to Q1.
- Default target: none (P03)
- Definition: the number of days from the end of the latest finished edition of the kind to the
  as-of date; `NO_DATA` when there is none.

### `BUD_EXEC_RATE`

- Module: `BUDGET`
- Unit: `RATIO`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `currency`, `source`
- Source: `R24`
- Appendix line: L80
- Proposal: none
- Default target: none (P03)
- Definition: for the fiscal year of the as-of date (the calendar year, A08), per funding source
  and currency, executed ÷ allocated. Executed is the sum of the execution rows of the year's
  entries dated on or before the date; allocated is the sum of the entered amounts. The value is
  missing (`NO_DATA`) when allocated is missing or zero. Amounts are whole minor units of an ISO
  4217 currency (BRL, USD, EUR) and amounts of different currencies are never added or converted.
  The dimension is encoded as `currency=BRL;source=<source code>`.

The rate is year-to-date, so its status compares it with the target multiplied by the elapsed
fraction of the year (day of the year ÷ days in the year, linear), when pro-rating is on (P08, on
by default). A target entered for this indicator is a year-end target: the stored value is never
changed, and the reading records the scaled thresholds it used. Without pro-rating a year-end target
would read `CRITICAL` every January.

### `STOCK_VALID_QTY`

- Module: `STOCK`
- Unit: `COUNT`
- Direction: `HIGHER_IS_BETTER`
- Dimension keys: `category`, `item`
- Source: `O01, O02, O04`
- Appendix line: none (owner request 2026-11-20)
- Proposal: none
- Default target: none (P03)
- Definition: per stock item type (the dimension `item` is the type code, `category` its category:
  `antidote`, `decontaminant`, `detector`, `ppe` or `other`), the quantity on hand on the date in
  the lots that are valid on the date. The quantity of a lot is the signed sum of its movements
  dated on or before the date; a lot is valid when it has no expiry date or its expiry date is not
  before the date, so a lot expiring on the date is still valid. Lots that are expiring soon count
  as valid. The quantity on hand of all lots, the quantity of the expired lots, the quantity of the
  expiring lots and, when one is set, the minimum of the type (P12) are carried beside the value as
  context. A value exists only for an active type that is in use on the date (it has a lot with a
  movement on or before the date) or has a minimum, and for an inactive type that still has stock
  on hand; a fresh database therefore has no stock value. The minimum is not a target: a target
  on this indicator is entered in Settings like any other and is the only thing that gives it a
  status.

### `STOCK_LOTS_EXPIRING`

- Module: `STOCK`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `category`
- Source: `O03, P11`
- Appendix line: none (owner request 2026-11-20)
- Proposal: none
- Default target: none (P03)
- Definition: per category that has a `STOCK_VALID_QTY` value, the number of lots with stock on
  hand whose expiry date falls from the date up to the date plus the warning window (P11, 90 days
  by default), both ends included.

### `STOCK_LOTS_EXPIRED`

- Module: `STOCK`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `category`
- Source: `O03`
- Appendix line: none (owner request 2026-11-20)
- Proposal: none
- Default target: none (P03)
- Definition: per category that has a `STOCK_VALID_QTY` value, the number of lots with stock on
  hand whose expiry date is before the date. A lot with nothing on hand is empty, never expired.

### `STOCK_TYPES_BELOW_MIN`

- Module: `STOCK`
- Unit: `COUNT`
- Direction: `LOWER_IS_BETTER`
- Dimension keys: `category`
- Source: `O04, P12`
- Appendix line: none (owner request 2026-11-20)
- Proposal: none
- Default target: none (P03)
- Definition: per category with at least one active type that has a minimum, the number of those
  active types whose valid quantity on the date is strictly below the minimum. A type with no
  minimum is never counted, and a minimum of 0 is never reached from below.

## Alerts that read the indicators

Alerts are computed when needed and never stored. They are sorted by severity, then by due date.
The alert kinds are codes; the interface builds the text.

| Kind | Severity | Trigger |
|---|---|---|
| `CERT_EXPIRED` | `CRITICAL` | an active person's counting qualification at a level has expired and is not marked "no renewal" |
| `CERT_EXPIRING` | `WARNING` | that qualification is valid and expires within the warning window (P01) |
| `MAINT_OVERDUE` | `CRITICAL` | an in-service asset's maintenance due date is before the date |
| `MAINT_DUE_SOON` | `WARNING` | its due date falls within the warning window (P02) |
| `MAINT_SCHEDULE_UNKNOWN` | `INFO` | an in-service asset has neither an interval nor a recorded next-due date (an interval of 0 means "no scheduled maintenance" and raises nothing) |
| `INDICATOR_WARNING` | `WARNING` | an indicator value crosses an enabled warning threshold |
| `INDICATOR_CRITICAL` | `CRITICAL` | an indicator value crosses an enabled critical threshold |
| `LOT_EXPIRED` | `CRITICAL` | a lot with stock on hand has an expiry date before the date (at most one alert per lot) |
| `LOT_EXPIRING` | `WARNING` | a lot with stock on hand expires within the warning window (P11), the last day included |
| `LOW_STOCK` | `CRITICAL` | an active item type with a minimum (P12) has a valid quantity strictly below it (no date) |

Indicator alerts need a target, so with the default of no targets they never appear.

## Placeholders and assumptions

Every value that needs confirmation is declared in `domain/config.py` with a code-level flag. The
flag is the release-level truth. There are two kinds:

- `local_only`: targets (P03), institution and unit names (D18) and the report handling notice
  (P10) and the minimum stock per item type (P12). They never get a code default, their flag is never cleared in code, and they are
  confirmed per installation in Settings only.
- `generic_default`: all the others. The flag may be cleared, and the default changed, only by a
  release commit when the project owner judges that the value is not sensitive.

Settings shows a "placeholder — to be confirmed" badge until the operator confirms or changes a
value. That per-installation state only hides the badge; it never changes the flag in code. The
column "Code flag" says `set` while the flag in the code is set.

| ID | Kind | Config fields | Default in code | Code flag | Question |
|---|---|---|---|---|---|
| P01 | `generic_default` | `cert_warning_days` | 90 days | set | Q2 |
| P02 | `generic_default` | `maintenance_warning_days` | 30 days | set | Q6 |
| P03 | `local_only` | none (targets have their own table) | no targets, so "no target" | set | Q1 |
| P04 | `generic_default` | `snapshot_monthly`, `snapshot_on_report` | on, on | set | Q9 |
| P05 | `generic_default` | `min_passphrase_length` | 12 characters (hard floor 12) | set | Q11 |
| P06 | `generic_default` | `daily_backups_kept` | 7 copies (hard floor 2) | set | none |
| P07 | `generic_default` | none (wording lives in the translations) | translated notice | set | Q15 |
| P08 | `generic_default` | `budget_prorate_target` | on (linear) | set | Q8 |
| P09 | `generic_default` | `backup_reminder_days` | 30 days | set | Q11 |
| P10 | `local_only` | `report_handling_notice` | empty | set | Q10 |
| A02 | `generic_default` | `ppe_hierarchy_enabled`, `ppe_hierarchy` | off, empty | set | Q2 |
| A04 | `generic_default` | `ppe_validity_months` | not set | set | Q2 |
| A05 | `generic_default` | `degraded_counts_as_available` | off | set | Q5 |
| A06 | `generic_default` | none (intervals live in the asset tables) | interval not set | set | Q6 |
| A07 | `generic_default` | none (metrics live in their table) | no metrics | set | Q7 |
| A08 | `generic_default` | `default_currency` | BRL | set | Q8 |
| A09 | `generic_default` | none (the course list is a table) | empty list | set | Q3 |
| A10 | `generic_default` | none (the status is per degree) | completed | set | Q3 |
| A11 | `generic_default` | `small_count_threshold` | 5 | set | Q10 |
| D18 | `local_only` | `institution_name`, `unit_name` | empty | set | Q17 |
| P11 | `generic_default` | `stock_expiry_warning_days` | 90 days | set | Q28 |
| P12 | `local_only` | none (the minimum lives in the stock item type table) | no minimum | set | Q26 |

The configuration also holds `operator_label` (D05), which is not a placeholder.

The assumptions without a setting carry no flag: A01 (available means in service and working, not
free), A03 (the counting qualification), A12 (one operator, or people taking turns on one machine),
A13 (the exercise kinds CBRAMED, EXBRAMED and other), A14 (a person or an asset has one active
interval; someone who returns is a new record), A15 (stock quantities are whole units of issue,
with no unit column) and A16 (the category of each built-in stock item type).

### Open questions behind the placeholders

This repository records no answers. The questions are listed in PLAN.md section 12; the subject of
each one that a placeholder waits for is:

| Question | Subject |
|---|---|
| Q1 | indicators and targets |
| Q2 | PPE qualifications and retraining |
| Q3 | training and degrees |
| Q5 | beds and bays |
| Q6 | equipment and maintenance |
| Q7 | exercises |
| Q8 | budget |
| Q9 | readiness reading and predictive validity |
| Q10 | reports |
| Q11 | information security |
| Q15 | preliminary notice |
| Q17 | report headers |
| Q26 | units of issue and minimum stock |
| Q28 | stock expiry rules |
