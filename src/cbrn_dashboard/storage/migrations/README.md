# Database migrations

This folder holds the numbered SQL migrations of the database (PLAN.md D06, section 5). The
runner is `storage/migrate.py`. The migration files are the source of truth for the schema; the
SQL sketch in the plan is only illustrative.

## Rules

- A migration is a file named `NNNN_name.sql`: four digits, an underscore, lower-case letters,
  digits or underscores (`0002_personnel.sql`). A `.sql` file with any other name makes the runner
  refuse to run.
- The files are loaded with `importlib.resources` (this folder is a Python package), so they also
  work inside the frozen executable.
- Each migration runs in **one explicit transaction**: `BEGIN IMMEDIATE`, every statement through
  `execute()`, `PRAGMA user_version = N` in the same transaction, `COMMIT`. Any error ends in
  `ROLLBACK`; migrations that were already committed in the same run stay applied. The runner
  never uses `executescript()`, because Python's `sqlite3` commits a pending transaction before
  it runs a script. It splits a file into statements with `sqlite3.complete_statement`, so
  `CREATE TRIGGER ... BEGIN ...; END;` bodies and semicolons inside string literals are fine. A
  file must end with a complete statement.
- Tables are `STRICT`, and every write to a data table goes through the repository helpers (D05).
- `PRAGMA foreign_keys` does nothing inside a transaction. A migration that rebuilds tables
  (create the new table, copy, drop the old one, rename) must carry the header comment line
  `-- migrate: table-rebuild` in its leading comment block, before the first statement. For such a
  migration the runner turns foreign keys off before `BEGIN`, runs `PRAGMA foreign_key_check`
  before `COMMIT` (any row it returns rolls the migration back) and turns foreign keys back on
  afterwards, also after a failure.
- The app makes a backup of a non-empty database before it migrates, and it refuses to open a
  database whose `user_version` is higher than the newest migration.
- **A migration is never edited after it has shipped in a tagged release.** Change the schema
  with a new migration instead.
- `0001_core.sql` creates `app_meta`, `setting` and the append-only `change_log`. It does not
  seed `app_meta`: the service that creates the database writes `is_demo` and `created_with`.

## Reserved numbers (valid only until v0.1.0)

So that modules developed in parallel do not collide, these numbers are reserved per module
**only until v0.1.0**:

| Number | Module                |
| ------ | --------------------- |
| 0002   | personnel             |
| 0003   | infrastructure        |
| 0004   | exercises             |
| 0005   | budget                |
| 0006   | indicator targets     |
| 0007   | snapshots             |

After v0.1.0 the reservations no longer apply: **every later migration is numbered max+1 at merge
time**, that is, one more than the highest number in the main branch when it is merged.

## Contiguity

The files must be contiguous from 0001. The runner refuses to run (`MigrationSequenceError`,
code `MIGRATION_SEQUENCE`, nothing executed) when there is a gap, a duplicate number or the
first file is not 0001. This includes a database whose `user_version` is higher than the number
of a missing file.

Because the runner does not tolerate holes, reserved numbers are **merged in ascending order**: a
module whose predecessor (for example 0002 for 0003) is not merged yet waits, or rebases once it
is.

## Development and demo databases

Developer databases and demo databases are disposable before v0.1.0. When a migration is changed
or renumbered during that time, delete the database file and let the app create it again.
