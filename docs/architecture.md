# Architecture

This document is written for the next team that maintains the CBRN Readiness Dashboard, for
example a partner institution. It describes what the source tree contains today. The reasons
behind the big decisions are in [PLAN.md](../PLAN.md) (section 4); the indicators are in
[indicators.md](indicators.md); data protection is in [data-protection.md](data-protection.md);
the CSV formats are in [import-templates.md](import-templates.md). `tests/meta/test_docs.py`
checks that the package list, the migration list, the page and settings registries, the start-up
hooks and the translation areas named here match the code.

**Preliminary version — indicators not institutionally validated.** All example data in the
repository is fictitious; demo identifiers start with `DEMO`.

## 1. What the program is

An offline Windows desktop program written in Python 3.12 with PySide6 (Qt Widgets) and the
standard-library `sqlite3`. It has one local operator, one SQLite database file and no network
code. The licence is GPL-3.0-or-later. The only runtime dependencies are PySide6 and
`cryptography` (see `pyproject.toml`).

## 2. Layers and import rules

```text
ui/        PySide6 widgets, table models, dialogs, label maps (Qt)
  | calls
services/  use cases: add a PPE qualification, evaluate indicators, back up ...   (no Qt)
  | uses                              | uses
domain/    pure rules (no Qt, no I/O)    storage/   sqlite3, migrations, backups, CSV   (no Qt)
reports/   model.py and anonymise.py (no Qt)  ->  pdf.py (Qt rendering only)
```

Domain functions return codes and numbers, never translated text. The interface turns codes into
words (section 11). Because of that most checks are plain pytest runs that need no widgets.

The rules are enforced by tests that parse every source file with the `ast` module and never run
the code (`tests/meta/_ast_rules.py`, used by `tests/meta/test_forbidden_apis.py`). A rule that
stops matching is itself caught, because every rule has snippets it must catch and snippets it
must leave alone.

| Rule | What it forbids |
|---|---|
| `LAYER-DOMAIN` | `domain/` importing `cbrn_dashboard.storage` or `cbrn_dashboard.services`, in absolute or relative form |
| `LAYER-QT` | PySide6 or shiboken6 inside `domain/`, `services/`, `storage/`, `reports/model.py` and `reports/anonymise.py` |
| `LAYER-SQL` | `sqlite3` inside `ui/`: the interface goes through `services/` |
| `NET` | network, event-loop, browser and multiprocessing modules anywhere in `src/` (section 6) |
| `HANDOFF` | hand-offs to the shell or to other programs (section 6) |
| `CLOCK` | reading the wall clock anywhere but `clock.py` (section 5) |
| `SYNTAX` | a file that does not parse, so a broken file never passes the scan silently |

One more guard, `tests/meta/test_ui_rules.py`: Qt's ready-made modal dialogs (`QMessageBox`,
`QFileDialog`, `QInputDialog` and the like) may be used only in `ui/shell/prompts.py`. Everything
else asks the `Prompts` interface, so tests can replace it with a fake and a windowed run without a
console never blocks on a dialog nobody can see. The application's own `QDialog` subclasses are
allowed.

The guard has known blind spots, written in the docstring of `_ast_rules.py`: shadowed names are
not tracked, and deliberate evasion such as `getattr(os, "system")` is out of scope. A false positive is
fixed by renaming, never by adding an exception.

## 3. Package map

Top-level packages of `src/cbrn_dashboard/`:

| Package | Role |
|---|---|
| `domain/` | pure rules and indicator definitions: `config.py` (readiness configuration and the placeholder registry), `dates.py`, `indicators.py` (framework), `registry.py` (composition of the indicator registry), `personnel.py`, `infrastructure.py`, `exercises.py`, `budget.py`, `alerts.py` |
| `storage/` | `db.py` (the single place that opens connections), `migrate.py` and `migrations/`, `repository.py` (writes with the change log), one repository per area, `settings_repo.py`, `targets_repo.py`, `snapshots_repo.py`, `app_meta.py`, `backup.py` (plain copies and rotation), `crypto_backup.py` (the `.cbrnbak` container), `csv_io.py` |
| `services/` | use cases over storage and domain: `personnel.py`, `infrastructure.py`, `exercises.py`, `budget.py`, `indicators.py`, `alerts.py`, `dashboard.py`, `config.py`, `snapshots.py`, `validation_export.py`, `backup.py`, `restore.py`, `export.py`, `importer.py`, `countries.py`, `errors.py` |
| `reports/` | `model.py` (report content as codes and numbers), `anonymise.py` (small-count suppression), `message_keys.py` (code-to-message-key map) and `labels.py` (texts in the language chosen for the report), `pdf.py` (Qt rendering) |
| `ui/` | one sub-package per area: `ui/shell/` (main window, registry, context, prompts, banners, charts, formatting, translators, first-run notice, instance lock, the in-app help viewer `help.py` and the About dialog `about.py`), `ui/personnel/`, `ui/infrastructure/`, `ui/exercises/`, `ui/budget/`, `ui/stock/`, `ui/dashboard/`, `ui/alerts/`, `ui/settings/`, `ui/backup/`, `ui/reports/` |
| `i18n/` | the languages, the area-to-source map and the Qt Linguist catalogues `<area>_<lang>.ts` |
| `resources/` | `app.ico`, `countries.json` and `THIRD_PARTY_DATA.md` |
| `help/` | the in-app help, one Markdown file per language (`pt_BR.md`, `en_US.md`, `es_ES.md`); package data, shown by `ui/shell/help.py` |
| `demo/` | the deterministic generators of the fictitious demo database |

Top-level modules of `src/cbrn_dashboard/`:

| Module | Role |
|---|---|
| `__init__.py` | the version, `__version__` |
| `__main__.py` | the entry point (`cbrn-dashboard` is a GUI script that calls it) |
| `app.py` | the start-up sequence and the start-up hooks (section 7) |
| `cli.py` | command-line parsing; Qt-free so that `--version` needs no display |
| `clock.py` | the only module allowed to read the wall clock (section 5) |
| `paths.py` | resolution of the data folder (section 8) |
| `prefs.py` | the preferences file `prefs.json` |
| `logging_setup.py` | logging of event codes and exception types, never of contents |
| `selftest.py` | the registry of checks run by `--self-test` |

Folders outside the package: `tests/` (subfolders `tests/domain/`, `tests/storage/`,
`tests/services/`, `tests/reports/`, `tests/ui/`, `tests/i18n/`, `tests/demo/`, `tests/scripts/`,
`tests/packaging/`, `tests/meta/`, plus `tests/fixtures/` with fictitious data only), `scripts/`
(`build_exe.py`, `collect_licenses.py`, `make_release_zip.py`, `fetch_source_archives.py`, `i18n.py`,
`terminology_sheet.py`, `gen_countries.py`, `gen_icon.py`), `packaging/` (first-run notes, `portable.ini.example`, third-party licence texts),
`docs/` and `.github/` (workflows, templates).

## 4. Data flow

```text
widget / page  ->  AppContext.services.<x>  ->  service  ->  repository (storage)  ->  SQLite file
                                                   |
                                                   +-->  domain rules (pure functions)
```

- A page never touches the database. It reaches the module services through `AppContext`
  (`ui/shell/context.py`), which holds the open connection, the clock, the data location, the
  prompts, the preferences, the translator manager, the module services, the mode flags (read-only,
  demo, suspect clock) and the global as-of date. `ui/` does not import `sqlite3`; the connection
  is typed through `storage.db.DatabaseConnection`.
- `build_services` creates the services over one connection, one clock and one operator-label
  callable. The `Services` dataclass has one attribute per service; every attribute is `None` while
  no database is open, so pages must be constructible without a database.
- Reading: a service loads dated records through repositories, builds plain domain records and
  calls domain functions with the as-of date as an argument. `IndicatorService.evaluate` evaluates
  every registered indicator for a date; nothing is cached.
- Writing: every write goes through the helpers `insert`, `update` and `delete` in
  `storage/repository.py`. Each runs in a transaction, so the data change and its `change_log` rows
  commit or roll back together. One log row is written per affected row, cascades included. Personal
  free-text columns are never copied into the log, and triggers forbid updating or deleting log rows.
- Services report problems as `ServiceError` with a stable code and the name of the offending
  field; the interface maps codes to texts. Messages never contain record contents.
- Alerts are computed when needed and never stored. Snapshots are the only stored record of what
  was known and configured at a past moment; they are never updated or deleted, only withdrawn by
  appending a row.
- `storage/db.py` is the only place that creates connections: `isolation_level=None` with explicit
  transactions, foreign keys on, `journal_mode=DELETE` (never WAL), `synchronous=FULL` and
  `secure_delete=ON`. Read-only connections use a `mode=ro` URI.

## 5. Where time comes from

Time enters the program through an injected `Clock` (`clock.py`) and nowhere else:

- `Clock.utc_now()` returns an aware UTC `datetime`; stored timestamps are always UTC.
- `Clock.local_date()` returns the local calendar date of the workstation ("today"). Day and month
  boundaries (the daily backup, the monthly snapshot, the default as-of date) use it.
- `SystemClock` is the real clock; `FixedClock` is the deterministic clock of the tests.

Domain functions never read a clock: every function that depends on "today" takes the as-of date as
an argument. The `CLOCK` rule of the guard flags calls and references to `today`, `now`, `utcnow`,
`time`, `time_ns`, `localtime`, `gmtime`, `ctime`, `asctime`, Qt's `currentDate` family and
one-argument `time.strftime` outside `clock.py`. The demo data is placed relative to the injected
clock's date.

At start-up a clock sanity check marks the session as suspect when the current UTC instant is
earlier than the newest `change_log` row or than the build timestamp. A suspect session shows a
banner and skips the automatic monthly snapshot. It still makes backups; what it skips is the
rotation of three pools, because a time that is too early in a file name could push newer, good
copies out: the daily pool (the daily backup itself still runs), the pre-migration pool (the
migration backup is made, the pool is not rotated) and the before-restore pool (the safety copy is
made, the pool is not rotated). The before-restore pool is also not rotated while the live database
fails its own integrity check, whatever the clock says. The manual encrypted backup has no pool and
no rotation.

One known limit: Qt writes the creation date of a PDF itself, from the system clock, and it cannot
be set through `QPdfWriter` (see `reports/pdf.py`).

## 6. What the program never does

- **Network.** There is no network code: no update check, no telemetry, no crash upload. The `NET`
  rule forbids `socket`, `socketserver`, `ssl`, `urllib`, `urllib3`, `http`, `ftplib`, `smtplib`,
  `xmlrpc`, `imaplib`, `poplib`, `asyncio`, `requests`, `httpx`, `webbrowser`, `multiprocessing` and
  the Qt network and web components (`QtNetwork*`, `QtWebSockets`, `QtHttpServer`, `QtWebEngine*`),
  including dynamic imports with a literal name. The build script also deletes the Qt network
  libraries from the bundle.
- **Process spawning and shell hand-offs.** The `HANDOFF` rule forbids `subprocess`, `ctypes`,
  `multiprocessing`, `QProcess`, `os.system`, `os.popen`, `os.spawn*` and `os.exec*` everywhere in
  `src/`. `os.startfile` and `QDesktopServices` are allowed only in `ui/shell/folders.py`, the one
  place meant to hand a folder to the shell.
- **The wall clock** outside `clock.py` (section 5).
- **Writing where the user did not choose.** The database, the logs, the preferences, the plain
  backups and the temporary files live in the data folder. The program writes outside it in three
  cases only: a file or folder the user chose for an encrypted backup, a PDF report, a CSV or a
  validation export; and the pointer file `location.json` in the user profile folder, which
  remembers a data folder chosen after an unusable one (`paths.py`). In read-only mode nothing is
  written to the data folder at all (section 8).
- **Logging contents.** Logs hold event codes, exception types and stack frames only, never record
  contents or exception messages. A crash dialog shows a code, never the message.

## 7. Start-up sequence

`app.start` does everything except entering the event loop, so that tests and the self-test can
create the real window. In order:

1. The command line is parsed and the data location resolved. `--self-test` short-circuits in
   `main`: it never opens the real database and takes no lock.
2. The mode is decided: a writable folder means read-write; a folder or database file that cannot
   be written, with an existing database, means read-only; an unwritable folder with no database is
   explained and the user is offered another folder (remembered in `location.json`).
3. The application, the translators and the preferences are set up: `--lang` for this run only,
   else the saved language, else Brazilian Portuguese.
4. Logging is configured in memory and the crash hook is wired to a translated dialog.
5. In read-write mode the exclusive instance lock is taken **before** the database is opened and
   before the log file is opened; a second instance explains itself and exits with code 1.
6. The database is opened: the demo database for `--demo`, a read-only connection in read-only
   mode, otherwise the real database, migrated. A refused database ends with exit code 1. The
   demo database stores the day it was created (`app_meta`); a read-write `--demo` start on another
   day asks once, through the prompts, whether to create the demo data again for today. Yes
   replaces only the demo database file; no keeps it. In read-only mode nothing is asked.
7. The clock sanity check runs.
8. `AppContext` and the main window are built.
9. The registered start-up hooks run once, in order.

Whether a database is a demo database comes from `app_meta.is_demo` of the open database, never
from the command line.

The start-up hooks (`STARTUP_HOOKS` in `app.py`), one entry each:

| Hook | Read-only | Demo | Needs trusted clock |
|---|---|---|---|
| `tmp-cleanup` | no | yes | no |
| `daily-backup` | no | no | no |
| `monthly-snapshot` | no | no | yes |
| `backup-reminder` | yes | no | no |
| `first-run-notice` | yes | no | no |

A hook that raises is logged (type and frames only) and does not stop the others.

## 8. The data folder

`paths.resolve_data_location` picks the folder; the first rule that applies wins:

1. the `--data-dir` option;
2. the environment variable `CBRN_DASHBOARD_DATA_DIR`;
3. portable mode: `portable.ini` beside a frozen executable puts the data in `.\data\` beside it;
4. the pointer file `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`;
5. the default `%LOCALAPPDATA%\cbrn-readiness-dashboard\`.

Because portable mode ranks above the pointer file, the pointer is honoured in portable mode only
when the portable folder is unusable. The resolver reads only an injected environment, creates the
folder if it is missing, tests writability by creating and deleting a temporary file and never
falls back to another folder silently. Warnings (network path, OneDrive) are codes that the
interface translates.

Layout of a data folder:

| Item | Content |
|---|---|
| `cbrn-dashboard.sqlite3` | the database |
| `prefs.json` | preferences (language, first-run flag) |
| `backups\` | plain copies: daily, and before each migration |
| `logs\` | the log |
| `tmp\` | short-lived files, including decrypted temporary copies; emptied at start-up |
| `demo\` | the separate demo database `demo.sqlite3` and its own `backups\` |
| `selftest.json` | written only by `--self-test` |

In read-only mode the database is opened with a read-only connection and every edit action is
disabled; the log and preferences stay in memory, and the lock, the daily backup, the snapshots and
the clean-up of `tmp\` are skipped.

## 9. Storage

### Migrations

The schema is a sequence of numbered SQL files in `storage/migrations/`, loaded with
`importlib.resources` so that they also work in the frozen executable:

| File | Content |
|---|---|
| `0001_core.sql` | `app_meta`, `setting` and the append-only `change_log` |
| `0002_personnel.sql` | personnel tables |
| `0003_infrastructure.sql` | infrastructure tables |
| `0004_exercises.sql` | exercise tables |
| `0005_budget.sql` | budget tables |
| `0006_indicator_targets.sql` | indicator targets |
| `0007_snapshots.sql` | readiness snapshots |
| `0008_budget_sources_r24.sql` | built-in funding sources of the revised R24: COMAER and DIRSA; the OPCW Trust Fund source is no longer built in |
| `0009_stock.sql` | stock by lot (types, lots, dated movements) and the 17 built-in stock types |

The rules (from `storage/migrate.py` and `storage/migrations/README.md`):

- A file is named `NNNN_name.sql`. The files must be contiguous from 0001; the runner refuses to
  run on a gap, a duplicate or a badly named file, and refuses a database whose `user_version` is
  higher than the newest migration.
- Each migration runs in one explicit transaction (`BEGIN IMMEDIATE` ... `COMMIT`, with
  `PRAGMA user_version` set in the same transaction). The runner never uses `executescript()`,
  because Python's `sqlite3` commits a pending transaction before it runs a script.
- A migration may not start a statement with `BEGIN`, `COMMIT`, `END`, `ROLLBACK`, `SAVEPOINT`,
  `RELEASE`, `VACUUM`, `ATTACH`, `DETACH` or `PRAGMA`; the runner owns those.
- A migration that rebuilds tables carries the header line `-- migrate: table-rebuild`; only such
  a migration may use `DROP TABLE`. For it the runner turns foreign keys off before the
  transaction and runs `PRAGMA foreign_key_check` before the commit.
- A non-empty database is backed up before the first migration runs.
- Schema and seed migrations write no `change_log` rows (the log is append-only and records user
  writes); the pre-migration backup keeps the earlier state. Migration 0008, which changes seed
  rows of `funding_source`, is an example.
- **A migration is never edited after it has shipped in a tagged release.** Nothing is tagged yet,
  so developer and demo databases are disposable until a release is published. Change the schema
  with a new migration, numbered one more than the highest number on the main branch when it is
  merged. The numbers 0002 to 0007 were reserved per module only until v0.1.0.
- Tables are `STRICT`, and every write to a data table goes through the repository helpers.

### Backups and restore

`storage/backup.py` makes every copy with SQLite's online backup API, under a temporary name that is
renamed when the copy is complete. There are three kinds, each with its own pool that no other
kind rotates:

| Kind | Name | Kept | Folder |
|---|---|---|---|
| daily | `daily-<YYYYMMDDTHHMMSSZ>-v<NNNN>.sqlite3` | the newest 7 (P06, never fewer than 2) | `backups\` |
| pre-migration | `pre-migration-<YYYYMMDDTHHMMSSZ>-v<NNNN>.sqlite3` | 3 | `backups\` |
| before restore | `<db file name>.before-restore-<YYYYMMDDTHHMMSSZ>` | 2 | beside the database |

A new copy must pass `PRAGMA quick_check` before any older copy is deleted, and the newest verified
copy is never deleted. A demo database uses `demo\backups\`.

`storage/crypto_backup.py` defines the manual encrypted backup, `.cbrnbak`: a header (magic
`CBRNBAK1`, format version, scrypt parameters, salt, app version, schema version), a header HMAC,
a Fernet token holding the database bytes and a trailing unkeyed SHA-256. The key is derived with
scrypt (n = 2^17, r = 8, p = 1) into 64 bytes, 32 for Fernet and 32 for the header HMAC. The reader
checks, in order: magic and trailer (`CORRUPT_BACKUP`), format version (`BACKUP_TOO_NEW`), scrypt
parameters against an allow-list before any derivation (`CORRUPT_BACKUP`), the header HMAC
(`WRONG_PASSPHRASE`) and the Fernet token (`CORRUPT_BACKUP`). The passphrase is never stored.

`services/restore.py` COPIES a backup into the live database with SQLite's online backup API. It
never renames or swaps database files and is not described as atomic: if the copy fails, the live
database is put back from the safety copy taken first. In short: the file is decrypted into
`<data>\tmp\` only; `PRAGMA integrity_check`; a backup whose `app_meta.is_demo` differs from the
open database is refused; the restored database's own `user_version` decides (newer is refused,
older is migrated with the pre-migration backup off); the live database must be quiescent (no other
connection, no open transaction, no journal file); a safety copy is made; the temporary database is
copied in; the result is checked; a `restore` row is written to `change_log`; and the temporary
files are always deleted. Every failure before the copy leaves the live database untouched.

The File menu of the main window calls these services: "Back up...", "Restore..." and "Open data
folder" (`ui/backup/actions.py`, wired in `ui/shell/main_window.py`). Restore is disabled in
read-only mode; Back up stays available. "Open data folder" goes through `ui/shell/folders.py`,
which accepts an existing local folder only.

The Help menu opens the in-app help (`ui/shell/help.py`, F1 at the topic of the page shown) and the
About dialog (`ui/shell/about.py`). Both are ordinary `QDialog`s that open without blocking and are
built on the first request. The About dialog shows the version, the GPL-3.0-or-later notice, the
source URL as plain text, the preliminary notice and one line per entry of `licenses\index.json`,
which the bundle ships beside the executable; running from source there is no such index and the
dialog says so. Neither dialog makes a network connection or opens a link.

## 10. Registries of the shell

`ui/shell/registry.py` holds three tuples. A module registers itself by adding one line to the tuple
that concerns it; titles are callables, so translated text is produced when it is needed and follows
a language switch. A duplicate key is rejected.

- **Pages** (`PAGES`, ordered by `order`): `dashboard` (5), `personnel` (10), `infrastructure` (20),
  `exercises` (30), `budget` (40), `alerts` (50), `reports` (60) and `settings` (90).
- **Settings sections** (`SETTINGS_SECTIONS`): `settings.general`, `settings.alerts`,
  `settings.targets`, `personnel.rules`, `infrastructure.types`, `exercises.metrics`,
  `budget.sources`, `backup.settings`, `reports.settings` and `snapshots.settings`. Each belongs
  to one of the settings groups:
  `general`, `alerts`, `targets`, `personnel`, `infrastructure`, `exercises`, `budget`, `backup`,
  `reports` and `snapshots`. A section with another group is rejected.
- **Dialogs** (`DIALOGS`): every dialog is registered with a factory that fills it with fictitious
  data, so that tests can open and walk each one.

Page, section and dialog factories must work when a service is `None` and must not prompt, open a
dialog or touch the database when they are constructed.

Other start-up registries: `STARTUP_HOOKS` in `app.py` (section 7), `GENERATORS` in
`demo/__init__.py` (one generator per module, plus the cross-module generators for illustrative
targets and retroactive snapshots, which exist only in the demo database) and the checks of
`selftest.py` (`@register("name")`).

## 11. Translations

Languages: Brazilian Portuguese (the default on first start, whatever the Windows language),
English and Spanish (Spain), written `pt_BR`, `en_US` and `es_ES` in file names and `pt-BR`,
`en-US`, `es-ES` on the command line.

- **Source strings are English**, written as `QCoreApplication.translate("Context", "text")` with
  a string-literal context, because `pyside6-lupdate` extracts only literals. Domain and services
  return codes; each UI area's `labels.py` maps codes to translated strings.
- **One catalogue per area and language**, `<area>_<lang>.ts` in `src/cbrn_dashboard/i18n/`. The
  areas, and the source folders they cover, are the dictionary `AREAS` in `i18n/__init__.py`:
  `shell`, `personnel`, `infrastructure`, `exercises`, `budget`, `stock` (the shared stock UI,
  `ui/stock/`, context `Stock`), `alerts`, `dashboard`, `settings`, `backup`, `reports` (the
  Qt-free report package and its PDF renderer) and `reports_ui` (the reports page, `ui/reports/`).
  One catalogue per area lets people work in parallel without editing the same file.
- **Workflow.** After you add or change a string, run `python scripts/i18n.py update` (it runs
  `lupdate` with `-locations none`, so the files do not churn). Fill in the pt-BR and es-ES
  translations; `en_US` is a real catalogue too. `python scripts/i18n.py compile` runs `lrelease`
  and writes the `.qm` files, which are never committed (they are git-ignored); the tests compile
  to a temporary folder. Running from source without compiled files shows the English strings.
- **Draft status.** The pt-BR and es-ES translations are drafts and keep Qt Linguist's
  `type="unfinished"` until the committee reviews the terminology (Q14). `lrelease` ships
  unfinished messages.
- **Terminology review sheet.** `python scripts/terminology_sheet.py export --out sheet.csv`
  writes one CSV (UTF-8 with a byte order mark, separator `;`) with a row per message of the
  pt-BR and es-ES catalogues: a stable `id` (`m` plus the first 12 hex digits of the SHA-256 of
  `area|context|source|comment`), `area`, `context`, `english`, `comment`, `note` (the
  translator note), `estado` (`pendente` while a translation is unfinished), the current
  translations (`pt_BR_atual`, `es_ES_atual`; the two forms of a plural message are joined with
  ` | `), the empty columns `pt_BR_revisado` and `es_ES_revisado` that the committee fills in, and
  `observacoes`. `python scripts/terminology_sheet.py import --csv sheet.csv [--mark-finished]`
  writes every non-empty `*_revisado` cell back into the matching `<translation>` element,
  in place (the rest of the `.ts` file stays byte-identical). A cell is skipped, and reported with
  its row id, when its placeholders (`%1`, `%L1`, `%n`) differ from the English source, when a
  plural message does not have exactly two forms, or when the `id` is unknown or the `area`,
  `context` or `english` column was edited. `--mark-finished` also removes `type="unfinished"`
  from the translations that were reviewed. Run `python scripts/i18n.py update` afterwards. The
  instructions for the committee are in
  [revisao-terminologia.pt-BR.md](revisao-terminologia.pt-BR.md).
- **Tests** are in `tests/i18n/` (`test_catalogues.py`, `test_catalogues_in_sync.py`,
  `test_translate_contexts.py`) and in `tests/ui/test_no_hardcoded_strings.py` (the pseudo-locale
  walk). PLAN.md section 6 lists what the checks are meant to cover.
- **Live switching.** The translator manager swaps the translators and the default locale; Qt sends
  a language-change event and each widget re-applies its texts in `retranslate()`.
- **Reports** use their own translators for the language chosen in the report, and never swap
  the application's translators.
- **The in-app help** is not a catalogue: it is one Markdown file per language in `help/`, with
  the same topics in every language. Each topic is a `##` or `###` heading followed by the marker
  line `<!-- topic: <id> -->`; the id of a page topic is the registry key of the page, so a page
  without a help topic fails a test. The files hold no link and no image. The viewer chooses the
  file of the current language and follows a language switch.
- Dates, numbers and money are formatted for display with the locale; exports always use a
  locale-independent format ([import-templates.md](import-templates.md)).

## 12. How to add a module

Suppose a new area, "x". Follow the order below; each step is one small, reviewable change.

1. **Domain.** Write `domain/x.py`: pure functions of the as-of date and plain records, plus
   `indicator_definitions()` and `indicator_values(...)`. Add a member to the `Module` enum in
   `domain/indicators.py`, and one import and one line to `PROVIDERS` in `domain/registry.py`. The
   registry rejects a duplicate code.
2. **Document the indicators.** Add an entry per code to [indicators.md](indicators.md) in the
   format of the existing entries. `tests/meta/test_docs.py` fails until the entry matches the
   registry.
3. **Migration.** Add `storage/migrations/NNNN_x.sql`, numbered one more than the highest on the
   main branch, with `STRICT` tables. Never edit an older migration.
4. **Repository.** Add `storage/x_repo.py` that writes through `insert`, `update` and `delete` of
   `storage/repository.py`, so that every change is logged.
5. **Service.** Add `services/x.py`. Add it to `Services` and `build_services` in
   `ui/shell/context.py`, and make `IndicatorService` collect its indicator values.
6. **Interface.** Add `ui/x/` with `page.py`, `dialogs.py`, `models.py` and `labels.py`, and one
   line each in `PAGES`, `SETTINGS_SECTIONS` and `DIALOGS` of `ui/shell/registry.py`. A settings
   group must be one of `SETTINGS_GROUPS`. Use the `Prompts` interface for every message box and
   file picker.
7. **Translations.** Add the area to `AREAS` in `i18n/__init__.py`, run
   `python scripts/i18n.py update`, translate, and make sure every enum member has a label.
8. **Demo data.** Add a generator to `demo/` and one line to `GENERATORS`; every identifier starts
   with `DEMO`.
9. **Self-test and alerts.** Optionally add a `@register` check to `selftest.py`. A new alert kind
   extends `AlertKind` and `SEVERITY_OF` in `domain/alerts.py` and needs labels and a row in
   [indicators.md](indicators.md).
10. **Tests and docs.** Add tests under the matching `tests/` folder and name the new package in
    this document; the package list is checked.

If the module adds a placeholder (a default that needs confirmation), declare it in
`PLACEHOLDERS` in `domain/config.py` with its kind and question, and add its row to the table in
[indicators.md](indicators.md). Values that identify an institution or set a readiness target are
`local_only`: they never get a code default.

## 13. Tests and checks

`uv run pytest` runs the default suite: the unit tests, ruff (`check` and `format`), mypy, the
guards of section 2 and the translation tests. The markers are `ui` (needs a `QApplication`, run on
Qt's offscreen platform), `packaging` (builds or inspects the bundle; deselected by default,
`uv run pytest -m packaging`) and `slow`. Qt warnings fail a test unless a message matches one of
the regular expressions listed in `qt_log_ignore` in `pyproject.toml` (the entries there are
anchored patterns, so escape any parenthesis or dot that must match literally). Test data is
fictitious.

## 14. Packaging and release

- `scripts/build_exe.py` builds the one-folder bundle with PyInstaller (`--onedir --windowed
  --noupx`), removes unwanted Qt libraries and the Universal CRT files (`ucrtbase.dll`,
  `api-ms-win-*.dll`: Windows 10 and 11 always use their own copy) and writes the third-party
  licence folder with `scripts/collect_licenses.py`. The Visual C++ runtime files stay in the
  bundle; `licenses\MSVC-RUNTIME.md` lists every one found, case-insensitively, and says they are
  Microsoft's files, not covered by the GPL, redistributed unmodified under Microsoft's terms.
  That folder also carries the third-party notices of Qt in full
  (`QT-THIRD-PARTY-NOTICES.txt`). A maintainer generates them with
  `scripts/fetch_qt_attributions.py` from the `qt_attribution.json` files of the Qt source
  repositories (`qtbase`, `qtsvg`, `qtcharts`, `qtimageformats`, `qtvirtualkeyboard`) at the tag of
  the bundled Qt version, and commits them under `packaging/licenses/qt-attributions/` together
  with a list of every URL read and its SHA-256. The collector copies the file and fails when its
  `Qt version:` header is not the bundled one, so a PySide6 upgrade needs a refresh. The build and
  the application never use the network for this.
- `scripts/make_release_zip.py` writes the reproducible zip, `SHA256SUMS.txt` and
  `SHA256-FILES.txt` and fills the release-notes template. With `--installer` it also puts the
  setup file into `SHA256SUMS.txt` and the "Installer" section into the notes. With
  `--source-archives-dir` it also verifies the Qt and PySide6 source archives (below), lists them
  in `SHA256SUMS.txt` (this command is the only writer of that file) and adds the "Source code of
  Qt and PySide6 (LGPL-3.0)" section to the notes.
- `scripts/fetch_source_archives.py` downloads the source archives of the bundled Qt and PySide6
  (LGPL-3.0 sources of the libraries in the bundle) from `download.qt.io`, on every release and
  without a manual step. The pinned list is `packaging/source-archives.json` (name, version, URL,
  size, SHA-256 of each archive). Each archive is streamed to a temporary file while its SHA-256
  is computed, checked against the pinned size and hash and then renamed atomically; a network
  error is retried up to three times, a mismatch fails the release with both values printed. A
  test compares the pinned version and URLs with the installed PySide6 and with the URL formats of
  `make_release_zip.py`, so upgrading PySide6 without updating the pins fails CI. The archives are
  unmodified copies of Qt's files: they are attached to the release but not attested.
- `scripts/build_installer.py` builds the per-user Windows installer with Inno Setup 6 from the
  tested bundle folder (`packaging/installer/cbrn-dashboard.iss`; `cbrn-readiness-dashboard-<version>-win-x64-setup.exe`).
  The installer needs no administrator rights (`PrivilegesRequired=lowest`; the setup dialog also
  offers an all-users install), installs under `%LOCALAPPDATA%\Programs`, has the three interface
  languages and never creates `portable.ini`. It has no `[UninstallDelete]` section, so the
  uninstaller never touches `%LOCALAPPDATA%\cbrn-readiness-dashboard`. The workflow runs
  `scripts/smoke_installer.ps1` on it on every release: silent install, the frozen `--self-test` of
  the installed program, silent uninstall, and a check that the data folder survived. The same
  smoke test runs in the packaging tests (`tests/packaging/test_installer.py`, so on every push to
  `main` in CI), where a missing compiler is a failure on GitHub Actions. Inno Setup 6 is
  preinstalled on the `windows-2025` image; nothing is downloaded. The installer is built from the
  folder the `package` job downloaded, after the optional signing step, so it is not signed (see
  [CODE-SIGNING-POLICY.md](../CODE-SIGNING-POLICY.md)). Inno Setup's own licence (permissive; the
  file `license.txt` in its install folder) applies to the setup stub only. It is not part of the
  bundle, so it is not in the bundle's `licenses\` folder; the release notes and the changelog
  name it.
- The release workflow runs on a version tag in four jobs. The read-only `build` job runs the tests
  and the packaging tests and uploads the bundle folder those tests built. The optional `sign` job
  runs only when the repository variable `SIGNPATH_ORGANIZATION_ID` is not empty: it sends that
  folder to SignPath (free code signing for open-source projects, SignPath Foundation), waits for
  the manual approval, checks the signature of `cbrn-dashboard.exe` and uploads the signed folder.
  Only `cbrn-dashboard.exe` is signed (`.signpath/artifact-configurations/release.xml`). The
  read-only `package` job zips the signed folder when `sign` ran and the tested folder otherwise,
  builds and smoke-tests the installer from the same folder, downloads and verifies the pinned Qt
  and PySide6 source archives (before the checksum step, into the same `release/` folder), writes
  the checksum files and the release notes (`release-body --signed` only after signing). The
  artefact is uploaded without compression (`compression-level: 0`; the `.xz` archives, about 460
  MB, are compressed already).
  The `release` job, the only one with write permissions, attests the build provenance of the zip
  and of the installer (not of the source archives) and creates a **draft** release with the zip,
  the installer, the two source archives and the checksum files. It installs nothing and runs no
  project code. Signing needs the repository variables `SIGNPATH_ORGANIZATION_ID`,
  `SIGNPATH_PROJECT_SLUG` and `SIGNPATH_SIGNING_POLICY_SLUG` (optionally
  `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`) and the secret `SIGNPATH_API_TOKEN`; it is not active
  until the project is accepted by SignPath. See [CODE-SIGNING-POLICY.md](../CODE-SIGNING-POLICY.md).
- The version in the source is `1.1.0` (in preparation, not published), single-sourced in
  `__init__.py` (hatch reads it, and `uv.lock` records none). The last published release is 1.0.2,
  on GitHub on 2026-11-14 as the
  tag `v1.0.2` (installer, zip and the Qt and PySide6 sources), before the manual test
  (`docs/smoke-test.pt-BR.md`, `docs/manual-test-script.pt-BR.md`), which is still pending; see
  `CHANGELOG.md`. (1.0.1, published on 2026-11-13, has the zip only; the draft of 1.0.0 was never
  published and was withdrawn.)
  See the [install guide](install.en-US.md).

## 15. Known limits and unfinished parts

- A read-only database on a UNC path was never tried on a real network share. The read-only
  address is built with an empty authority, and only that construction is tested, with a made-up
  path.
- Qt writes the creation date of a PDF from the system clock (section 5).
- The pt-BR and es-ES translations are drafts (`unfinished`, section 11).
- The executable is unsigned; the effects are described in the install guides. Signing through
  SignPath is prepared in the release workflow but not active.
