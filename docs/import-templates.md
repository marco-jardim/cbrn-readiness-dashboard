# CSV files: export format and column codes

The application writes the data of its modules (personnel, infrastructure, exercises, budget) as
CSV files, one file per entity. The same files, with the same column codes, are the templates for
the CSV import.

**The files contain internal data**: staff qualifications, the status and maintenance of
infrastructure, and budget figures. They stay on the user's machine unless the operator moves them.
Treat them like the database itself: do not leave them on shared, network, cloud-synchronised or
removable folders unless that is intended.

All examples in this document are fictitious (`DEMO-...` values).

## File format

The format does not depend on the language or regional settings of the computer.

| Item | Rule |
|---|---|
| Encoding | UTF-8 with a byte order mark (BOM). A file without the BOM is read as UTF-8 as well. |
| Delimiter | Semicolon (`;`). |
| Quoting | A field is enclosed in double quotes (`"`) when it contains `;`, a double quote or a line break; a double quote inside is written twice (`""`). |
| Line endings | `\r\n` after every record (RFC 4180). Line breaks inside a quoted field are kept as written. |
| Header | The first row holds the column codes listed below, in that order. |
| Dates | ISO 8601: `YYYY-MM-DD`, for example `2026-03-05`. |
| Numbers | `.` is the decimal point; no thousands separator; integers are plain digits. |
| Real numbers | Written with the shortest text that reads back as the same number. Values from `0.0001` up to (not including) `1e16` are written in plain form; smaller and larger values use the scientific form (`1e-05`, `1e+22`). Both forms are read. |
| Booleans | `0` or `1`. |
| Empty cell | NULL (no value). A required text column (see "Required") reads an empty cell as the empty text. |
| Money | Written in major units with the decimal places of the currency, for example `1234.56` for 123456 minor units of BRL. The currency is in its own `currency` column of the same row. Converted exactly, never through a floating-point number. |
| Codes | Identifiers, tags and codes are text: leading zeros are kept (`007`). |
| Row order | Rows are sorted by their natural key, so two exports of the same data are identical. |
| File names | `<entity>.csv`. When the database is a demo database, every name is prefixed with `DEMO-`. |
| References | A row refers to its parent by natural key (for example `staff_identifier`), never by an internal id. Internal ids are not exported. |

### Formula guard

A spreadsheet may run a text cell as a formula when it starts with `=`, `+`, `-`, `@`, a tab or a
carriage return. On export, every text or code cell that starts with one of these characters is
prefixed with a single quote (`'`). A cell that genuinely starts with `'` is prefixed as well, so
the guard can always be reversed: when a text cell starts with `'` and the next character is one of
the characters above or another `'`, exactly one leading `'` is removed. Numbers, dates and money
are never guarded.

Examples (fictitious): `=1+1` is written as `'=1+1`; `'=x` is written as `''=x`; `'plain` is
written as `''plain`; `DEMO-note` is written unchanged.

### Import order

Entities that other entities refer to come first. The export lists them, and the import reads them,
in this order:

1. `training_course`, `asset_type`, `evaluation_metric`, `funding_source` (the lists);
2. `staff_member`;
3. `ppe_certification`, `training_record`, `academic_degree`;
4. `asset`;
5. `asset_status_event`, `maintenance_event`;
6. `exercise_edition`;
7. `exercise_country`, `evaluation_result`;
8. `budget_entry`;
9. `budget_execution`.

## Entities

Kinds: `TEXT` free text; `CODE` identifier, tag or code (always text); `INTEGER`; `REAL`; `DATE`;
`BOOL`; `MONEY` amount in major units (needs the `currency` column of the same row); `CURRENCY`
ISO 4217 code of three upper-case letters.

"Key" is `yes` for the columns of the natural key, which identifies a row. "Required" is `yes`
when the column cannot be empty.

### `training_course`

Courses the unit defines. Example row: `007;Curso DEMO sete;Demo course seven;;1`.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Course code, unique. |
| `label_pt_br` | TEXT | no | no | Name in Brazilian Portuguese. |
| `label_en_us` | TEXT | no | no | Name in US English. |
| `label_es_es` | TEXT | no | no | Name in Spanish. |
| `active` | BOOL | no | yes | 1 when new records may use the course. |

### `asset_type`

Types of infrastructure assets (four built-in types and the user-defined ones).

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Type code, unique. |
| `built_in` | BOOL | no | yes | 1 for a type that comes with the application. |
| `label_pt_br` | TEXT | no | no | Name in Brazilian Portuguese. |
| `label_en_us` | TEXT | no | no | Name in US English. |
| `label_es_es` | TEXT | no | no | Name in Spanish. |
| `default_maintenance_interval_days` | INTEGER | no | no | Days between scheduled maintenance; 0 means none; empty means not set. |
| `active` | BOOL | no | yes | 1 when new assets may use the type. |

### `evaluation_metric`

Metrics used to evaluate exercise editions.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Metric code, unique. |
| `label_pt_br` | TEXT | no | no | Name in Brazilian Portuguese. |
| `label_en_us` | TEXT | no | no | Name in US English. |
| `label_es_es` | TEXT | no | no | Name in Spanish. |
| `unit` | TEXT | no | no | Unit of the value, for example `pct`. |
| `scale_min` | REAL | no | no | Lowest allowed value of the scale. |
| `scale_max` | REAL | no | no | Highest allowed value of the scale. |
| `higher_is_better` | BOOL | no | yes | 1 when a higher value is better. |
| `active` | BOOL | no | yes | 1 when new results may use the metric. |

### `funding_source`

Where budget money comes from (two built-in sources and the user-defined ones).

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Source code, unique. |
| `built_in` | BOOL | no | yes | 1 for a source that comes with the application. |
| `label_pt_br` | TEXT | no | no | Name in Brazilian Portuguese. |
| `label_en_us` | TEXT | no | no | Name in US English. |
| `label_es_es` | TEXT | no | no | Name in Spanish. |
| `active` | BOOL | no | yes | 1 when new entries may use the source. |

### `staff_member`

People, identified by a local code, never by a national ID or a service number.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `identifier` | CODE | yes | yes | Local code of the person, for example `DEMO-00123`; unique. |
| `label` | TEXT | no | no | Optional short label. |
| `category` | TEXT | no | no | Category of the person. |
| `active_from` | DATE | no | yes | First day of the active interval. |
| `active_until` | DATE | no | no | Last day of the active interval; empty while active. |

### `ppe_certification`

PPE certificates of a person.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `staff_identifier` | CODE | yes | yes | `identifier` of the person (`staff_member`). |
| `ppe_level` | CODE | yes | yes | Level: `A`, `B` or `C`. |
| `issued_on` | DATE | yes | yes | Issue date. |
| `valid_until` | DATE | no | yes | Last day of validity; not before `issued_on`. |
| `no_renewal_from` | DATE | no | no | Date from which no renewal is expected; empty when renewal is expected. |
| `no_renewal_reason` | CODE | no | no | `left_unit`, `role_change` or `other`. |
| `reference` | TEXT | no | no | Short reference hint; no names, health or contact data. |

### `training_record`

Courses completed by a person.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `staff_identifier` | CODE | yes | yes | `identifier` of the person (`staff_member`). |
| `course_code` | CODE | yes | yes | `code` of the course (`training_course`). |
| `completed_on` | DATE | yes | yes | Completion date. |
| `hours` | REAL | no | no | Course hours. |

### `academic_degree`

Academic degrees of a person.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `staff_identifier` | CODE | yes | yes | `identifier` of the person (`staff_member`). |
| `level` | CODE | yes | yes | `specialisation`, `master` or `doctorate`. |
| `status` | CODE | no | yes | `completed` or `in_progress`. |
| `year` | INTEGER | yes | no | Year of the degree; empty when unknown. |
| `field` | TEXT | yes | no | Field of study; empty when unknown. |

### `asset`

Physical infrastructure assets.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `tag` | CODE | yes | yes | Asset tag, for example `DEMO-BED-001`; unique. |
| `type_code` | CODE | no | yes | `code` of the asset type (`asset_type`). |
| `description` | TEXT | no | no | Description; may contain line breaks. |
| `location` | TEXT | no | no | Where the asset is. |
| `in_service_from` | DATE | no | yes | First day in service. |
| `in_service_until` | DATE | no | no | Last day in service; empty while in service. |
| `maintenance_interval_days` | INTEGER | no | no | Days between scheduled maintenance; overrides the type default; 0 means none. |
| `notes` | TEXT | no | no | Free notes. |

### `asset_status_event`

Status history of an asset: one event per asset and day.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `asset_tag` | CODE | yes | yes | `tag` of the asset (`asset`). |
| `effective_on` | DATE | yes | yes | First day of the status. |
| `status` | CODE | no | yes | `operational`, `degraded` or `out_of_service`. |
| `note` | TEXT | no | no | Free note. |

### `maintenance_event`

Maintenance performed on an asset.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `asset_tag` | CODE | yes | yes | `tag` of the asset (`asset`). |
| `performed_on` | DATE | yes | yes | Date of the maintenance. |
| `kind` | CODE | yes | yes | `preventive`, `corrective` or `inspection`. |
| `next_due_on` | DATE | no | no | Date the next maintenance is due; not before `performed_on`. |
| `note` | TEXT | no | no | Free note. |

### `exercise_edition`

One edition of an exercise.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Edition code, for example `DEMO-ED-1`; unique. |
| `kind` | CODE | no | yes | `CBRAMED`, `EXBRAMED` or `OTHER`. |
| `title` | TEXT | no | no | Title. |
| `start_on` | DATE | no | yes | First day. |
| `end_on` | DATE | no | yes | Last day; not before `start_on`. |
| `participants` | INTEGER | no | no | Number of participants (counted, never identified); empty when unknown. |
| `notes` | TEXT | no | no | Free notes; may contain line breaks. |

### `exercise_country`

Countries that took part in an edition.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `edition_code` | CODE | yes | yes | `code` of the edition (`exercise_edition`). |
| `country_code` | CODE | yes | yes | ISO 3166-1 alpha-2 country code in upper case, for example `BR`. |

### `evaluation_result`

The value of one metric in one edition.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `edition_code` | CODE | yes | yes | `code` of the edition (`exercise_edition`). |
| `metric_code` | CODE | yes | yes | `code` of the metric (`evaluation_metric`). |
| `value` | REAL | no | yes | The value, inside the scale of the metric. |
| `respondents` | INTEGER | no | no | Number of respondents; empty when unknown. |
| `note` | TEXT | no | no | Free note. |

### `budget_entry`

One allocation per fiscal year, source, currency and description.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `fiscal_year` | INTEGER | yes | yes | Fiscal year (the calendar year). |
| `source_code` | CODE | yes | yes | `code` of the funding source (`funding_source`). |
| `currency` | CURRENCY | yes | yes | Currency: `BRL`, `USD` or `EUR`. |
| `description` | TEXT | yes | yes | Description; an empty description is the empty text. |
| `allocated` | MONEY | no | no | Allocated amount in major units; empty when not set. |
| `notes` | TEXT | no | no | Free notes. |

### `budget_execution`

One row per dated execution (spending) of a budget entry.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `fiscal_year` | INTEGER | yes | yes | Fiscal year of the entry (`budget_entry`). |
| `source_code` | CODE | yes | yes | Source code of the entry (`budget_entry`). |
| `currency` | CURRENCY | yes | yes | Currency of the entry; also the currency of `amount`. |
| `description` | TEXT | yes | yes | Description of the entry (empty text for an empty description). |
| `executed_on` | DATE | yes | yes | Date of the execution. |
| `amount` | MONEY | yes | yes | Executed amount in major units. |
| `note` | TEXT | no | no | Free note. |

## Import rules

**Placeholder: task T8.4 completes this section** (header-only templates, dry run, single
transaction, per-row errors, duplicates by natural key, `,` as an alternative delimiter, legacy
encodings rejected as `NOT_UTF8`). Until then, the export format above is the only specification.
