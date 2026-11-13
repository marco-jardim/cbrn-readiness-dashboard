# Demo walkthrough

The demo mode opens a separate database full of fictitious data, so every page can be tried
without touching real records. Nothing in it is real: the people, units, editions and amounts are
generated from a fixed seed and are placed relative to the day the demo database is created. The
situations described below are those of that creation day. The data is not regenerated when the
demo is opened again, so it ages with the calendar: a PPE qualification that "expires in 30 days" expires
a day closer each day, and an alert that is a warning today becomes critical later. When you open
an existing demo database on another day, the application offers to create the demo data again for
today (see "Start the demo").

Names in `code font` that start with DEMO are records of the demo dataset. A test checks that each
of them exists, so this page cannot drift from the data.

## Start the demo

From a source checkout, run the application with the `--demo` option:

```text
uv run cbrn-dashboard --demo
```

Add `--data-dir <folder>` to choose the data folder and `--lang en-US` (or `pt-BR`, `es-ES`) to
choose the language for one run. The first start creates and fills the demo database and stores the
day it was created next to the demo flag. Later starts open it again without generating anything a
second time.

When a later start happens on another day than the creation day, the application asks once whether
to create the demo data again for today. Answer yes to replace the demo database with a new one
dated today (any change you made to the demo data is lost; the real database is never touched), or
no to keep it exactly as it is. In read-only mode nothing is asked and nothing is written.

A permanent banner at the top of the window says that the data is fictitious. It is driven by the
database, not by the command-line option: any database marked as a demo database shows it.

## How the demo is kept apart from real data

- The demo database is its own file, `demo/demo.sqlite3` inside the data folder, with its own
  backup folder `demo/backups/`. The real database is never created, opened or changed in demo
  mode.
- Every generated identifier, label and description starts with DEMO.
- The database carries a demo flag; the banner, and the DEMO- prefix on exported CSV file names,
  follow that flag.
- The indicator targets and the snapshots described below exist only in the demo database. They
  are illustrations, not readiness standards; a real database starts with no targets and no
  snapshots until the committee enters them.

## Personnel

The Personnel page shows the 24 fictitious people of the demo database. Six are fixed cases:

- `DEMO-P001` holds level A and level B PPE qualifications that stay valid for a long time, and has a
  completed specialisation and a completed master degree.
- `DEMO-P002` has a level A PPE qualification that expires in 30 days, inside the warning window.
- `DEMO-P003` has a level A PPE qualification that expired 45 days ago.
- `DEMO-P004` has a valid level A PPE qualification that is marked "no renewal" from 10 days ago, so it
  raises no expiry alert.
- `DEMO-P005` was deactivated 60 days ago and is not counted in the indicators.
- `DEMO-P006` has a renewal chain at level B: an old expired PPE qualification and a newer valid one,
  which counts once.

The courses are `DEMO-C1`, `DEMO-C2` and `DEMO-C3`. Training dates lie both inside and outside the
last 12 months.

## Infrastructure

The Infrastructure page shows the 20 fictitious assets of the demo database, of the four built-in
types and of the user-defined type `DEMO-TYPE`. Nine are fixed cases:

- `DEMO-A001` (bed): maintenance was due 20 days ago, so it is overdue.
- `DEMO-A002` (bay): degraded since 15 days ago, with maintenance due in 10 days.
- `DEMO-A003` (negative-pressure filtration): out of service since 10 days ago, with no interval
  and no recorded next due date, so its maintenance schedule is unknown.
- `DEMO-A004` (decontamination tent): an interval of 0 means no scheduled maintenance; no alert.
- `DEMO-A005`, `DEMO-A006` and `DEMO-A007`: next due dates worked out from the asset's own
  interval, from the default interval of `DEMO-TYPE`, and from the in-service date.
- `DEMO-A008`: retired 30 days ago; its history stays but it is out of the indicators.
- `DEMO-A009`: enters service in 20 days.

## Exercises

The Exercises page shows nine fictitious editions, `DEMO-EX-01` to `DEMO-EX-09`, of the three
kinds (CBRAMED, EXBRAMED and other), with participant counts, countries and results for the two
metrics `DEMO-M1` (higher is better) and `DEMO-M2` (lower is better).

- `DEMO-EX-06` is the latest ended EXBRAMED edition and has no participant count, so its
  participants indicator reads "No data".
- `DEMO-EX-09` starts in the future, so it has no results and is ignored by the "latest edition"
  indicators.

## Budget

The Budget page shows entries for the current fiscal year and the three before it, for the two
built-in funding sources and the user-defined source `DEMO-SRC-A`. Each entry has several dated
execution rows; in the current year one row is dated after today and does not count yet. The one
exception is a demo database created on 31 December: a row must stay inside its fiscal year, so no
row can be dated after that day. The COMAER source (Air Force Command) has entries in BRL and in USD, which are never
added together.

- `DEMO - pending allocation` is a USD entry of `DEMO-SRC-A` with execution rows but no allocated
  amount, so its execution rate reads "No data".
- The other entries are `DEMO - DIRSA annual allocation`, `DEMO - COMAER allocation`,
  `DEMO - COMAER foreign purchases`, `DEMO - equipment` and `DEMO - training`.

## Dashboard

The Dashboard shows one tile per indicator reading, the number of alerts per severity and the
charts. The demo database holds illustrative targets for some readings, so that every status can
be seen. Every other reading has no target and reads "No target" (the application never invents
a standard).

| Indicator | Dimension | Status |
|---|---|---|
| `PERS_CERT_VALID` | level A | OK |
| `PERS_CERT_VALID` | level B | Warning |
| `PERS_CERT_VALID` | level C | Critical |
| `PERS_CERT_EXPIRING` | level A | Warning |
| `PERS_RETRAINING_NEEDED` | level B | OK |
| `PERS_TRAINING_12M` | none | OK |
| `INFRA_AVAILABLE` | bed | OK |
| `INFRA_AVAILABLE` | decon_tent | Warning |
| `INFRA_MAINT_OVERDUE` | bed | Critical |
| `INFRA_MAINT_OVERDUE` | decon_tent | OK |
| `EX_LAST_PARTICIPANTS` | CBRAMED | OK |
| `EX_LAST_PARTICIPANTS` | OTHER | Warning |
| `EX_DAYS_SINCE_LAST` | CBRAMED | OK |
| `EX_DAYS_SINCE_LAST` | OTHER | Critical |
| `BUD_EXEC_RATE` | BRL, DIRSA | Critical |
| `BUD_EXEC_RATE` | USD, COMAER | OK |

Two readings read "No data" whatever the targets: `EX_LAST_PARTICIPANTS` for EXBRAMED (see
`DEMO-EX-06`) and `BUD_EXEC_RATE` for USD and `DEMO-SRC-A`. Readings such as `PERS_DEGREE` have
no target and read "No target".

The targets are written when the demo database is created. They are computed from the generated
data of the creation day; they are not standards of any kind. They are not recomputed later, so
the statuses above are those of the creation day and change as the dates age.

One status depends on the creation day. The budget target is a year-end value that the application
multiplies by the elapsed part of the year (day of the year divided by the days in the year), and
the demo never stores a year-end ratio above 100 percent. The DIRSA group has executed between 4
and 12 percent of its allocation, so it can only read Critical once the elapsed part of the year is
above that share. In a demo database created from 13 February on, the table is exact. In one
created before 13 February (on 1 January the elapsed part is 0.3 percent), `BUD_EXEC_RATE` for
BRL and DIRSA reads OK instead of Critical. Every other row, and each of the five statuses on the
dashboard, is the same on every creation day.

## Alerts

The Alerts page lists alerts sorted by severity and then by due date, with the columns Severity,
Module, Subject, Due date and Message. It can be filtered by module and by severity, and the
"Open record" button opens the record of the selected alert. On the creation day the demo data
produces every kind, and each severity:

| Kind | Severity | Example |
|---|---|---|
| `CERT_EXPIRED` | critical | `DEMO-P003`, level A |
| `CERT_EXPIRING` | warning | `DEMO-P002`, level A |
| `MAINT_OVERDUE` | critical | `DEMO-A001` |
| `MAINT_DUE_SOON` | warning | `DEMO-A002` |
| `MAINT_SCHEDULE_UNKNOWN` | info | `DEMO-A003` |
| `INDICATOR_CRITICAL` | critical | `PERS_CERT_VALID`, level C |
| `INDICATOR_WARNING` | warning | `PERS_CERT_VALID`, level B |

The random filler people and assets can add more alerts of the same kinds. `DEMO-P004` raises no
alert although its PPE qualification is marked "no renewal", and `DEMO-A004` raises none because it has
no scheduled maintenance.

## Snapshots

The demo database holds one retroactive snapshot for each edition that has already started
(`DEMO-EX-01` to `DEMO-EX-08`), recorded for the day before the edition began. Each stores every
indicator's value and status and the targets in force. They are marked retroactive because they
were taken after the day they describe. `DEMO-EX-09` starts in the future and has none. No monthly
snapshot is taken in demo mode.

The validation export of the demo database uses these snapshots when a retroactive reading is
requested: every started edition then gets the readings of its own snapshot, while `DEMO-EX-09`
carries the reason code `NO_PRIOR_SNAPSHOT`. Its file names start with DEMO-.

## Reports

The Reports page has four parts. The report and the exports write only to a file or folder you
choose; importing and recording or withdrawing a snapshot change the demo database.

- PDF report: "Create report..." opens a dialog to create the PDF report of the as-of date, either
  internal or anonymised, and to choose the file.
- Data export: "Export CSV files..." asks for a folder, warns that the files contain internal data
  and writes the CSV files. "Validation export..." opens a dialog that asks for a folder and writes
  the validation export described under Snapshots. In the demo database the file names start with
  DEMO-.
- Data import: "Import CSV file..." opens a wizard. A file is checked first, and a file with any
  error imports nothing. The wizard asks for the kind of data and, before writing, how many rows
  will be imported. Importing writes into the demo database only.
- Readiness snapshots: the list of snapshots (eight retroactive ones in the demo database), a box
  "Show withdrawn snapshots", "Record snapshot" for the as-of date and "Withdraw snapshot..." for
  the selected one. Withdrawing asks for a reason; the snapshot stays stored.

In read-only mode the report and the exports stay available; importing, recording and withdrawing
are disabled.

## Settings

The Settings page has one tab per group of settings; each tab holds one box per section.

- General: language, operator label, institution name and unit name.
- Alerts: how many days ahead PPE qualifications and maintenance are warned about.
- Targets: the table of indicator targets. In the demo database it lists the illustrative targets
  of the Dashboard section. A target can be added, edited, switched on or off, or deleted. The
  budget execution rate is entered as a year-end value; the note on the page says that it is scaled
  over the fiscal year when the indicator is evaluated.
- The sections of the modules (personnel rules and courses, infrastructure types, exercise metrics,
  funding sources), the backup settings, the settings of reports and anonymisation, and the
  snapshot settings.

A setting that is still a placeholder shows a "Placeholder - to be confirmed" badge with a Confirm
button. Changes made in the demo database stay in it; they are lost if the demo data is created
again.

## The File menu

- "Back up..." chooses the file for an encrypted backup (the suggested name starts with DEMO- in the
  demo database and ends in .cbrnbak), warns when the place is a network drive, a cloud-synchronised
  folder or the data folder itself, asks for the passphrase twice and writes the file. It also works
  in read-only mode.
- "Restore..." chooses a backup file, asks you to confirm that ALL the data now in the application
  is replaced (a safety copy of the current data is kept first) and asks for the passphrase. It is
  disabled in read-only mode. In demo mode it works on the demo database.
- "Open data folder" opens the data folder in the file manager.
- "Quit" closes the application.
