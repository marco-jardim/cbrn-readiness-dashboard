# Install guide (English)

This guide is for the people who install the CBRN Readiness Dashboard and for the IT teams that
allow it to run. It exists in three languages with the same structure:
[pt-BR](install.pt-BR.md), [en-US](install.en-US.md) and [es-ES](install.es-ES.md). The text of the
zip's first-run notes (`README-first-run.*.txt`) is shorter and says the same.

**Preliminary version — indicators not institutionally validated.** Do not enter real data yet: see
[data-protection.md](data-protection.md).

## 1. Status of this guide

The version in the source tree is `1.0.0`. It is **prepared** in the repository (changelog and
manual smoke-test script included), but nothing is tagged, so **no release has been published
yet and there is no file to download today**. The release workflow
(`.github/workflows/release.yml`) runs only when a tag `vX.Y.Z` is pushed, builds the bundle, and
creates a *draft* release (marked pre-release while the version is below 1.0.0). The workflow has
never run. A person publishes the draft after a manual smoke test
([smoke-test.pt-BR.md](smoke-test.pt-BR.md), in Portuguese), and until then this guide stays true:
there is no published release.

Everything below that talks about a download describes what that workflow and the scripts in
`scripts/` are written to produce. None of it has been tried on a published release.

To try the program today, run it from a source checkout (needs [uv](https://docs.astral.sh/uv/)):

```text
uv sync --locked --all-groups
uv run cbrn-dashboard --demo
```

## 2. Requirements

- Windows 10 (version 1809 or later) or Windows 11, 64-bit (x64).
- No administrator rights and no installer: the program is a folder that you extract.
- Python and Qt are inside the folder; nothing else has to be installed.
- A folder where Windows lets you run programs (see section 7 on locked-down machines).
- The workstation should use full-disk encryption (for example BitLocker). The program cannot
  check that.

## 3. Download

The release page of `https://github.com/marco-jardim/cbrn-readiness-dashboard` will carry three
files for a version:

| File | Content |
|---|---|
| `cbrn-readiness-dashboard-<version>-win-x64.zip` | the program |
| `SHA256SUMS.txt` | the SHA-256 checksum of the zip |
| `SHA256-FILES.txt` | the SHA-256 checksum of every file inside the zip's folder |

Download all three from the **same** release page. The zip holds one folder,
`cbrn-readiness-dashboard\`, with `cbrn-dashboard.exe`, the folder `_internal\`, the folder
`licenses\` (third-party licence texts), the three first-run notes and `portable.ini.example`.

## 4. Verify the download

### 4.1 Checksum with Get-FileHash

Open PowerShell in the folder with the files and run:

```powershell
Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256
```

Compare the `Hash` value with the line for the zip in `SHA256SUMS.txt`. They must be equal.

### 4.2 Provenance with gh attestation verify (optional)

If you have the [GitHub CLI](https://cli.github.com/), you can verify the build attestation:

```powershell
gh attestation verify .\cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard
```

This step needs network access **on your side**. The program itself stays offline: it has no
network code, no update check and no telemetry.

### 4.3 What the checks prove and do not prove

- `SHA256SUMS.txt` on the same release page proves transfer integrity (the file was not damaged on
  the way). It does not prove authenticity: anyone who could change the zip on that page could
  change the checksum file too.
- The attestation proves where and how the build ran. It does not prove that the program is safe.
- The executable is **unsigned** (code signing is a deferred decision).

## 5. Unblock and extract

1. Right-click the zip, choose *Properties*, tick *Unblock* if it is shown, and click *OK*. Do this
   **before** extracting: the extractor of Windows passes the Mark-of-the-Web on to the extracted
   files unless the zip was unblocked first. Other extractors behave differently.
2. Extract the **whole** zip to a folder where you are allowed to run programs. Do not start the
   program from inside the zip preview of Explorer: it fails there because `_internal\` is missing.
3. Start `cbrn-dashboard.exe` from the extracted folder.

## 6. First start and SmartScreen

Because the executable is unsigned, Microsoft Defender SmartScreen can show "Windows protected your
PC" the first time. Choose "More info" and then "Run anyway", unless your organisation forbids it;
in that case ask your IT team (section 7).

## 7. Locked-down machines (AppLocker, WDAC, Smart App Control)

For IT teams:

- **Extraction folder.** When AppLocker is enforced, its default rules allow programs only in the
  Windows folder, in Program Files and for administrators. Choose an extraction folder that your
  policy allows. The one-folder build is designed so that it never needs to run code from
  `%TEMP%`.
- **Verifying the files.** `SHA256-FILES.txt` of the same release lists the SHA-256 of every file
  in the folder, the `.pyd` and DLL files included (the values `Get-FileHash` prints); use it to
  verify each extracted file. `SHA256SUMS.txt` covers only the zip. Create your allow-listing
  rules from the verified folder with the policy tooling of your own organisation. Such rules are
  per file and per release, and must cover the `.pyd` and DLL files too.
- **Smart App Control** has no per-file bypass. On a machine where it is on, the unsigned program
  may simply not run.
- Only code signing would remove most of this friction. It is deferred until the deployment
  questions are answered.

## 8. Command-line options

The options are those of `cli.py`. They apply to `cbrn-dashboard.exe` and to
`uv run cbrn-dashboard` alike.

| Option | Meaning |
|---|---|
| `--data-dir PATH` | folder that holds the database and the other application data |
| `--lang pt-BR`, `--lang en-US` or `--lang es-ES` | interface language for this run only (not saved) |
| `--self-test` | run the built-in checks, write `selftest.json` to the data folder and exit |
| `--demo` | open the separate demo database with fictitious data, never the real one |
| `--version` | print the version and exit (see the note below the table) |

`cbrn-dashboard.exe` is a windowed program: it has no console. So `--version` prints nothing you can
rely on in a prompt of the frozen program. From a source checkout, `uv run cbrn-dashboard --version`
prints the version. The version is also stored in the version resource of the executable.

The default language is Brazilian Portuguese whatever the Windows language; it is changed in the
program and saved in `prefs.json` in the data folder.

## 9. Self-test and demo mode

```text
cbrn-dashboard.exe --self-test --data-dir C:\Temp\cbrn-selftest
```

The self-test never opens the real database. It works in a throwaway folder `tmp\selftest-*` under
the data folder and writes only `selftest.json` beside it. The windowed program has no console,
which is why the result is a file. The exit code is 0 when all checks pass and 1 otherwise.

Because the program is windowed, a prompt can return before the self-test has finished. Read
`selftest.json` (its `passed` field) only after the program has ended. A script that needs the exit
code must start the program in a way that waits for it, as the packaging tests do (they run it as
a child process, wait, and read the exit code and `selftest.json`).

```text
cbrn-dashboard.exe --demo
```

Demo mode opens `demo\demo.sqlite3` in the data folder, a separate file with its own backups, full
of fictitious records whose identifiers start with `DEMO`. A permanent banner says so. See
[demo-walkthrough.md](demo-walkthrough.md).

## 10. Data location and portable mode

### 10.1 Where the data lives

By default: `%LOCALAPPDATA%\cbrn-readiness-dashboard` (for example
`C:\Users\<name>\AppData\Local\cbrn-readiness-dashboard`). It holds `cbrn-dashboard.sqlite3` (the
database), `prefs.json`, `backups\`, `logs\`, `tmp\` and `demo\`. The full description, the threats
and the duties of the operator are in [data-protection.md](data-protection.md).

### 10.2 Choosing another folder

The data folder is chosen in this order; the first rule that applies wins:

1. the `--data-dir` option;
2. the environment variable `CBRN_DASHBOARD_DATA_DIR`;
3. portable mode (section 10.3);
4. the pointer file `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`, written by the program
   when you choose another folder after the data folder turned out to be unusable;
5. the default folder above.

### 10.3 Portable mode

Rename `portable.ini.example` to `portable.ini` and keep it next to `cbrn-dashboard.exe`. The data
then goes to the folder `data\` beside the program. The program only checks that `portable.ini`
exists; the keys in it are not read. `--data-dir` and `CBRN_DASHBOARD_DATA_DIR` take precedence.

**Warning:** copying the program folder copies the data too.

### 10.4 Read-only and network folders

If the data folder or the database file cannot be written and a database exists, the program opens
it read-only, shows a banner and disables every action that changes data. If the folder cannot be
written and holds no database, the program explains this and offers another folder.

The program warns when the data folder is on a network path (a UNC path or a mapped drive), because
SQLite file locking is unreliable on file shares, and when it is inside a OneDrive folder, because
the data would leave the machine. Do not use a network share for the data. Several people may take
turns on one machine only with one shared Windows account, or with `--data-dir` pointing to a local
folder restricted to the committee; separate Windows accounts get separate databases.

A mandatory or non-persistent Windows profile discards `%LOCALAPPDATA%` when the user logs off. On
such a computer use `--data-dir` with a local folder that persists.

## 11. Backups

The program keeps plain copies of the database in `backups\`: one at the first start of each day
(the newest 7 are kept, never fewer than 2) and one before each upgrade of the database (the last 3
are kept). Before a restore it also keeps a safety copy beside the database (the last 2 are kept).
These copies are as sensitive as the database.

Encrypted manual backups (`.cbrnbak`) are the only files designed to leave the machine, for
example on removable media. The passphrase has at least 12 characters, is never stored and cannot
be recovered: a lost passphrase means the backup cannot be opened. Keep encrypted backups on media
separate from the computer.

To make one, choose **File > Back up...** in the main window, choose where to save the file and
type the passphrase twice. To restore one, choose **File > Restore...**, choose the `.cbrnbak`
file, confirm that all current data will be replaced and type the passphrase. Restore is not
available in read-only mode; Back up is. **File > Open data folder** shows the local data folder.
No published version contains these entries yet (section 1).

## 12. Upgrades

Extract the new version to a **new** folder and start it; the data in the profile is untouched. On
the first start, if the new version has a database migration to apply, the program first makes a
backup of the database (the one before each upgrade of the database, section 11) and then migrates
it. If no migration is pending, it makes no such backup and migrates nothing. A database written by
a newer version is refused, so going back to an older version is blocked.

In portable mode the data is in `data\` beside the program, so a new program folder starts without
data unless you copy the old `data\` folder into it, or start the new program with `--data-dir`
pointing to the old `data\` folder.

## 13. Removal

Delete the program folder. The data stays in `%LOCALAPPDATA%\cbrn-readiness-dashboard` until you
remove that folder yourself; it holds the database, the backups and the log. In portable mode the
data is inside the program folder and is deleted with it. Copies of encrypted backups on other
media are not touched by either.

## 14. Known limits

- No release exists yet (section 1). The executable is unsigned.
- A read-only database on a UNC path (`\\server\share\...`) was never tried on a real network
  share. The way the program builds the read-only address for such a path is covered by a test with
  a made-up path only.
- The PySide6 wheels used for the bundle carry no SBOM and no third-party attribution files, so the
  bundle has only a pointer to Qt's list of licences (`licenses\QT-THIRD-PARTY.md`), not the
  attribution texts.
- Qt writes the creation date of a PDF report from the system clock; it cannot be set through the
  PDF writer, so two renderings of one report differ in that field.
- The pt-BR and es-ES translations are drafts and still marked `unfinished`; the committee has not
  reviewed the terminology.
- The indicators have no targets until the committee enters them, and are not institutionally
  validated.
