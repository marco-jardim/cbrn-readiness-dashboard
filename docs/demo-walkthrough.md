# Demo walkthrough

The demo mode opens a separate database full of fictitious data, so every page can be tried
without touching real records. Nothing in it is real: the people, units, editions and amounts are
generated from a fixed seed and are placed relative to today, so the same situations are visible
whatever day the demo is opened.

Names in `code font` that start with DEMO are records of the demo dataset. A test checks that each
of them exists, so this page cannot drift from the data.

## Start the demo

From a source checkout, run the application with the `--demo` option:

```text
uv run cbrn-dashboard --demo
```

Add `--data-dir <folder>` to choose the data folder and `--lang en-US` (or `pt-BR`, `es-ES`) to
choose the language for one run. The first start creates and fills the demo database; later starts
open it again without generating anything a second time.

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

- `DEMO-P001` holds level A and level B certificates that stay valid for a long time, and has a
  completed specialisation and a completed master degree.
- `DEMO-P002` has a level A certificate that expires in 30 days, inside the warning window.
- `DEMO-P003` has a level A certificate that expired 45 days ago.
- `DEMO-P004` has a valid level A certificate that is marked "no renewal" from 10 days ago, so it
  raises no expiry alert.
- `DEMO-P005` was deactivated 60 days ago and is not counted in the indicators.
- `DEMO-P006` has a renewal chain at level B: an old expired certificate and a newer valid one,
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
execution rows; in the current year one row is dated after today and does not count yet. The OPCW
trust fund has entries in BRL and in USD, which are never added together.

- `DEMO - pending allocation` is a USD entry of `DEMO-SRC-A` with execution rows but no allocated
  amount, so its execution rate reads "No data".
- The other entries are `DEMO - DIRSA annual allocation`, `DEMO - local counterpart`,
  `DEMO - trust fund contribution`, `DEMO - equipment` and `DEMO - training`.

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
| `BUD_EXEC_RATE` | USD, OPCW_TRUST_FUND | OK |

Two readings read "No data" whatever the targets: `EX_LAST_PARTICIPANTS` for EXBRAMED (see
`DEMO-EX-06`) and `BUD_EXEC_RATE` for USD and `DEMO-SRC-A`. Readings such as `PERS_DEGREE` have
no target and read "No target".

The targets are written when the demo database is created. They are computed from the generated
data so that the statuses above hold on any day; they are not standards of any kind.

## Alerts

The Alerts page lists alerts sorted by severity and then by due date, with the columns Severity,
Module, Subject, Due date and Message. It can be filtered by module and by severity, and the
"Open record" button opens the record of the selected alert. The demo data produces every kind,
and each severity:

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
alert although its certificate is marked "no renewal", and `DEMO-A004` raises none because it has
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
