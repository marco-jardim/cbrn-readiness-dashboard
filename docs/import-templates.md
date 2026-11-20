# CSV files: export format and column codes

The application writes the data of its modules (personnel, infrastructure, exercises, budget,
stock) as CSV files, one file per entity. The same files, with the same column codes, are the
templates for the CSV import.

**The files contain internal data**: staff qualifications, the status and maintenance of
infrastructure, budget figures, and stock quantities and prices. They stay on the user's machine unless the operator moves them.
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

1. `training_course`, `asset_type`, `evaluation_metric`, `funding_source`, `stock_item_type` (the
   lists);
2. `staff_member`;
3. `ppe_certification`, `training_record`, `academic_degree`;
4. `asset`;
5. `asset_status_event`, `maintenance_event`;
6. `exercise_edition`;
7. `exercise_country`, `evaluation_result`;
8. `budget_entry`;
9. `budget_execution`;
10. `stock_lot`;
11. `stock_movement`.

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

### `stock_item_type`

What is kept in stock (17 built-in types and the user-defined ones). A built-in type has empty
labels: its name comes from the application. A user-defined type needs a Brazilian Portuguese
label.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `code` | CODE | yes | yes | Type code, unique: letters, digits, dot, hyphen and underscore, starting with a letter or a digit. |
| `built_in` | BOOL | no | yes | 1 for a type that comes with the application. |
| `category` | CODE | no | yes | `antidote`, `decontaminant`, `detector`, `ppe` or `other`. |
| `label_pt_br` | TEXT | no | no | Name in Brazilian Portuguese; required for a user-defined type. |
| `label_en_us` | TEXT | no | no | Name in US English. |
| `label_es_es` | TEXT | no | no | Name in Spanish. |
| `minimum_quantity` | INTEGER | no | no | Minimum stock in units, 0 to 1000000000; empty means not set. |
| `active` | BOOL | no | yes | 1 when new lots may use the type. |

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

PPE qualifications of a person.

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

### `stock_lot`

One lot of one item type. The quantity of a lot is never a column: it is the sum of its movements
(`stock_movement`).

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `type_code` | CODE | yes | yes | `code` of the item type (`stock_item_type`). |
| `lot_code` | CODE | yes | yes | Lot code, up to 64 characters; unique inside the type. |
| `expires_on` | DATE | no | no | Last day of validity; empty means no expiry date. Required for antidote and decontaminant types. |
| `unit_price` | MONEY | no | no | Price of one unit in major units; empty when not set. |
| `currency` | CURRENCY | no | no | Currency of `unit_price`; needed when `unit_price` is filled, ignored when it is empty. |
| `notes` | TEXT | no | no | Free notes. |

### `stock_movement`

One dated movement of a lot. The quantity is always positive; the kind gives the direction.

| Column | Kind | Key | Required | Meaning |
|---|---|---|---|---|
| `type_code` | CODE | yes | yes | `code` of the item type of the lot (`stock_item_type`). |
| `lot_code` | CODE | yes | yes | `lot_code` of the lot (`stock_lot`). |
| `moved_on` | DATE | yes | yes | Date of the movement; not after today. |
| `kind` | CODE | yes | yes | `receipt`, `adjustment_in` (these add to the stock), `issue`, `disposal`, `loss` or `adjustment_out` (these remove from it). |
| `quantity` | INTEGER | yes | yes | Units, a whole number from 1 to 1000000. |
| `reference` | TEXT | yes | yes | Short reference (delivery note, order); an empty reference is the empty text. |
| `note` | TEXT | no | no | Free note; required for `adjustment_in` and `adjustment_out`. |

## Import rules

The import (task T8.4) reads the same files the export writes. It serves the retroactive records
(2022-2025): the committee fills in the header-only templates, or edits an export, and imports the
files one entity at a time in the import order above. Import only ADDS rows: an existing row is
never changed or merged.

### Templates

A template is a file with the header row only, in the export format (BOM, `;`, CRLF). It is named
`<entity>-template.csv` (for example `staff_member-template.csv`). The Reports page has a "Write
templates..." action that writes the templates of all entities into a folder you choose (it asks
before replacing existing files); the header of every template is exactly the column list in the
tables above.

### Encoding

The file must be UTF-8, with or without a byte order mark. Any other encoding is refused as a
whole with `NOT_UTF8`; nothing is imported. Typical case: a spreadsheet saved as "CSV" in the
legacy Windows encoding, where accented letters break. To fix it, save the file again as
"CSV UTF-8 (comma delimited)" (Excel) or choose the character set "Unicode (UTF-8)" (LibreOffice
Calc, in the text export dialog).

### Separator and header

* The separator is `;` or `,`. It is detected from the header row: the one under which the cells
  are column codes. Quoting is the same as in the export (`"`, doubled inside); line breaks inside
  a quoted field are allowed.
* The header row must hold exactly the column codes of the entity, in any order, written exactly
  (lower case). A code that is not a column is `UNKNOWN_COLUMN` (the error names it), a column that
  is absent is `MISSING_COLUMN`, a column written twice is `DUPLICATE_COLUMN`. With a header error
  no row is read.
* An empty file, or a file with the header row only, is valid and holds zero rows.
* Completely blank lines are skipped. A row with more or fewer fields than the header is
  `WRONG_FIELD_COUNT`. A quote that is never closed, or text after a closing quote, is
  `MALFORMED_CSV`; the rows before it are still checked.

### Cells

| Kind | Rule | Error code |
|---|---|---|
| `TEXT` | Kept exactly as written, spaces included (the module trims it when it stores it). | none |
| `CODE` | Always read as text, so `00123` stays `00123`; spaces around it are removed. | none |
| `INTEGER` | Digits with an optional leading `-`; no decimal point and no thousands separator. | `INVALID_NUMBER` |
| `REAL` | `.` as the decimal point, no thousands separator, optional exponent (`1e-05`). | `INVALID_NUMBER` |
| `DATE` | Strict `YYYY-MM-DD` and a real calendar day. | `INVALID_DATE` |
| `BOOL` | `0` or `1`. | `INVALID_BOOL` |
| `CURRENCY` | Three upper-case letters of an accepted currency (`BRL`, `USD`, `EUR`). | `INVALID_CURRENCY` |
| `MONEY` | Major units with `.`, at most the decimal places of the currency of the same row (two for the three currencies), converted exactly. | `INVALID_AMOUNT`, `INVALID_CURRENCY` |

An empty cell is NULL. NULL in a required column is `REQUIRED`; the exception is a required `TEXT`
column, which reads an empty cell as the empty text (the `description` of a budget entry). Spaces
around the value of any kind except `TEXT` are ignored.

The formula guard is reversed: when a `TEXT` or `CODE` cell starts with `'` and the next
character is `=`, `+`, `-`, `@`, a tab, a carriage return or another `'`, exactly one leading `'`
is removed. So `'=1+1` is imported as `=1+1` and `''quoted` as `'quoted`; `'plain` is kept as it
is.

### References, natural keys and duplicates

A row refers to its parents by natural key: `staff_identifier`, `course_code`, `asset_tag`,
`type_code`, `edition_code`, `metric_code`, `source_code`, and for an execution row the budget
entry (`fiscal_year`, `source_code`, `currency`, `description`). The parent must exist when the
row is read: it is already in the database or was imported by an earlier file, which is why the
import order matters. A parent that does not exist is `UNKNOWN_REFERENCE` on the column that
refers to it (for an execution row whose budget entry is missing, on `description`; on
`source_code` when the source itself is unknown).

The natural key of each entity is marked in the tables above. A row whose key already occurs in
the file is `DUPLICATE_IN_FILE` (reported on the later line); a row whose key already exists in
the database is `DUPLICATE_KEY`. Neither is merged or updated. A `training_course`, `asset_type`,
`evaluation_metric` or `funding_source` row is not created for a built-in code that already exists
(`DUPLICATE_KEY`); a row with `built_in` = 1 and any other code is `BUILT_IN_NOT_ALLOWED`. Import
the user-defined rows only.

Every other rule is the rule of the screens, because each row is written through the same module
service: for example `VALID_UNTIL_BEFORE_ISSUED`, `END_BEFORE_START`, `ACTIVE_UNTIL_BEFORE_FROM`,
`IDENTIFIER_LOOKS_LIKE_NATIONAL_ID`, `INVALID_PPE_LEVEL`, `UNKNOWN_COUNTRY`,
`VALUE_OUT_OF_SCALE`, `NEGATIVE_AMOUNT`, `COURSE_INACTIVE`, `TYPE_INACTIVE`, `METRIC_INACTIVE`,
`SOURCE_INACTIVE`. The code is reported with the line and the column of the field. A row that
uses an inactive course, type, metric or source is refused like on the screen; activate it first.

Some entities need a note:

* `asset` creates the asset only. The status history, including the first status on
  `in_service_from`, comes from `asset_status_event`; import that file next.
* `exercise_country` adds one country to an existing edition per row.
* `stock_item_type` follows the rule of the other lists: built-in types are never created or
  changed by an import (an existing built-in code is `DUPLICATE_KEY`, any other row with
  `built_in` = 1 is `BUILT_IN_NOT_ALLOWED`), so import the user-defined types only. A minimum
  stock that comes with a type is stored as it is and does not confirm the placeholder P12.
* `stock_lot` creates the lot only, with NO movement: the quantity of a lot comes from
  `stock_movement`, which you import next. Until then the lots have no stock and show as not yet
  received. The report of the file gives their number as the warning `LOT_WITHOUT_MOVEMENTS`
  (`lots_without_movements`); it is a warning, never an error, and a dry run gives the same count.
  The lot is validated like a lot entered on the screen (expiry date for antidotes and
  decontaminants, price and currency, `TYPE_INACTIVE` for an inactive type: a lot of an inactive
  type is refused, so activate the type first and deactivate it again after the import). A price
  without a currency is `INVALID_CURRENCY`; a currency without a price is ignored.
* `stock_movement` is written through the stock service, which keeps the balance of a lot from
  going below zero on any date and refuses a date after today. The order of the rows in the file
  does not matter: the movements of each lot are applied in the order of date, then inflows
  (`receipt`, `adjustment_in`) before outflows, then file line, and each one is checked against the
  movements the lot already has and the rows applied before it. `BALANCE_NEGATIVE` (column
  `quantity`) and `DATE_IN_FUTURE` (column `moved_on`) are reported on the line of the movement that
  causes them. An empty `reference` is allowed and is stored as the empty text; it is part of the
  natural key. An adjustment without a `note` is `NOTE_REQUIRED`.

### All or nothing and the dry run

* A file is imported as a whole or not at all. If any row has any problem, nothing of the file is
  written. The report lists EVERY problem, not the first one: the line (1-based, counting the
  header; for a record with line breaks inside quotes, the line where it starts), the column code
  (empty for a problem of the whole row) and the code. A problem of the whole file has line 0.
* The check is complete: format, cells, references, duplicates and the rules of the module.
* The dry run does the same work and writes nothing: its report is what the real import would
  report, with zero rows imported. Both need a database that can be written; on a read-only
  database they are refused with `READ_ONLY`.
* Each imported row is recorded in the change log with the action `import`, with the operator and
  the time of the import. The log row names the table and the row, never the contents: staff
  identifiers, labels, PPE qualification references and degree fields do not reach the log.

### Error codes

| Code | Meaning |
|---|---|
| `NOT_UTF8` | The file is not UTF-8; save it again as UTF-8 (line 0, whole file). |
| `MALFORMED_CSV` | Quoting is broken; reading stopped at that line. |
| `UNKNOWN_COLUMN` | The header has a column that is not in the table of the entity (the column is named). |
| `MISSING_COLUMN` | The header lacks a column of the entity (the column is named). |
| `DUPLICATE_COLUMN` | The header names a column twice (the column is named). |
| `WRONG_FIELD_COUNT` | The row has more or fewer fields than the header. |
| `REQUIRED` | A required column is empty. |
| `INVALID_NUMBER` | An `INTEGER` or `REAL` cell is not a plain number. |
| `INVALID_DATE` | A `DATE` cell is not a real `YYYY-MM-DD` date. |
| `INVALID_BOOL` | A `BOOL` cell is not `0` or `1`. |
| `INVALID_CURRENCY` | The currency is not an accepted code, or an amount has no valid currency in its row. |
| `INVALID_AMOUNT` | A `MONEY` cell is not a plain amount, has more decimals than the currency, or is too large. |
| `UNKNOWN_REFERENCE` | The parent named by the row does not exist. |
| `DUPLICATE_IN_FILE` | The natural key already occurred earlier in the same file. |
| `DUPLICATE_KEY` | The natural key already exists in the database. |
| `BUILT_IN_NOT_ALLOWED` | The row claims to be a built-in list entry that this version does not have. |
| `BALANCE_NEGATIVE` | A stock movement would leave the balance of its lot below zero on some date (column `quantity`). |
| `DATE_IN_FUTURE` | A stock movement is dated after today (column `moved_on`). |
| `LOT_WITHOUT_MOVEMENTS` | WARNING, not an error: the lots of a `stock_lot` file have no movement yet; the file is still valid and the count is in the report. |
| `FILE_UNREADABLE` | The file cannot be opened (reported as an exception, not as a row problem). |
| any rule code | The module refused the value, for example `VALID_UNTIL_BEFORE_ISSUED`; reported on the column of the field. |
