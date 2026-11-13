# Data protection guide

This guide is for the people who install and operate the CBRN Readiness Dashboard. It says where the
data lives, which threats the design considers, which controls the application provides and which
duties stay with the institution and the operator. The application shows the main points in a
notice at its first start.

**Real data must not be entered yet.** Until the open questions on the formal classification of the
data (Q19), staff data (Q4), information security (Q11) and the deployment environment (Q13) are
answered, use only the fictitious demo data (`--demo`). The answers are not recorded in this
repository.

## Where the data lives

By default everything is stored in the profile of the Windows user who runs the program:

```
%LOCALAPPDATA%\cbrn-readiness-dashboard\
```

For example `C:\Users\<name>\AppData\Local\cbrn-readiness-dashboard\`. The folder holds:

| Item | Content |
|---|---|
| `cbrn-dashboard.sqlite3` | the database (the real data) |
| `prefs.json` | user-interface preferences (language, first-run notice flag) |
| `backups\` | automatic plain copies of the database (daily and before each upgrade) |
| `logs\` | the log (event codes only, never record contents) |
| `tmp\` | short-lived files; emptied at every start |
| `demo\` | the separate demo database and its own `backups\` |

The folder is chosen in this order; the first rule that applies wins:

1. the `--data-dir <folder>` option;
2. the `CBRN_DASHBOARD_DATA_DIR` environment variable;
3. portable mode: a `portable.ini` file next to `cbrn-dashboard.exe` puts the data in a `data\`
   folder beside it (copying that folder copies the data);
4. the pointer file `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`, written by the
   application when you choose another folder after the data folder turned out to be unusable;
   in portable mode it is used only when the portable folder is not writable and has no database;
5. the default folder above.

The data folder is shown in the status bar of the main window.

**A mandatory or non-persistent Windows profile** (a roaming profile, a virtual desktop that is
reset, a profile that is deleted at logoff) discards `%LOCALAPPDATA%` when the user logs off. The
database and its automatic backups are then lost. On such a computer use `--data-dir` with a local
folder that persists, and keep encrypted backups on separate media.

## Read-only mode and unusable folders

At start-up the application tests whether the data folder, and the database file itself, can be
written.

* If the folder or the database file cannot be written and a database exists, the database is
  opened read-only. A banner says so, every action that changes data is disabled, and **nothing is
  written to the data folder**: the log and the preferences stay in memory, no lock file is taken,
  and the automatic backup, the snapshots and the clean-up of `tmp\` are skipped. "Back up" still
  works, because it reads through an in-memory copy and writes only the file you choose. A database
  with an unfinished write (a hot journal) cannot be opened read-only; the application explains
  this instead.
* If the folder cannot be written and holds no database, the application explains the problem and
  offers to choose another folder. The choice is remembered in the pointer file in your user
  profile, never in the unusable folder.

## Threats considered

1. Loss or theft of the workstation or of backup media.
2. Accidental publication through the repository, issues, screenshots or test fixtures.
3. Copying a portable-mode folder that contains data.
4. Casual access by another local Windows user.
5. Data leaving through the network or cloud sync.
6. Data loss: corruption, a failed migration, a bad restore, a forgotten passphrase.

Out of scope: malware or an administrator on the running machine, and forensic recovery from SSDs.

## Controls

| Control | Threats |
|---|---|
| The application has no network code: no update check, no telemetry, no crash upload. | 5 |
| Data minimisation: staff are identified by an internal code with an optional label; there are no national ID numbers, birth dates, contact or health data and no free-text notes on personal records. A "pseudonymise person" action removes the identifier and free text while keeping the history. | 1, 2, 4 |
| The per-user profile location, with warnings when the data folder is on a network path (UNC or a mapped drive; SQLite locking is unreliable over file shares) or inside a OneDrive-synchronised folder (the data would leave the machine). The checks cover the common cases (environment variables, registry mount points, cloud-placeholder attributes) and cannot prove that a folder is not synchronised. | 4, 5 |
| Full-disk encryption of the workstation (see below). | 1 |
| Passphrase-encrypted manual backups (`.cbrnbak`): scrypt key derivation, Fernet encryption and a keyed checksum of the header. The passphrase has at least 12 characters, is never stored, and cannot be recovered if it is lost. A banner reminds you when the last encrypted backup is older than the configured number of days (30 by default) or when none was made. | 1, 6 |
| Automatic daily copies, a separate pool of copies made before each upgrade, and a safety copy before each restore, each checked before older copies are deleted. | 6 |
| Decrypted temporary files exist only inside `tmp\`, are deleted after use and are emptied at every start. | 1, 4 |
| A lock on the data folder allows one running instance at a time. | 6 |
| The demo database is separate (own file, own backups, a permanent banner); a restore refuses a backup whose demo flag differs from the open database. | 2 |
| Logs hold event codes, exception types and frames only. | 2 |
| Anonymised external reports (counts only, small counts suppressed). | 2, 5 |

## Full-disk encryption

The documentation requires that the workstation uses full-disk encryption (for example BitLocker),
as the institution's policy requires. The application **cannot verify** that it is on. It also does
**not protect files that you export or copy to removable media**: CSV and PDF exports, plain
automatic backups that you copy elsewhere, and the temporary files in `tmp\` are ordinary files,
protected only by Windows file permissions and by disk encryption. Encrypted backups (`.cbrnbak`)
are the only files designed to leave the machine.

## Backups

* Automatic copies in `backups\` are plain copies of the database. They are as sensitive as the
  database.
* Make encrypted backups regularly and keep them on separate media, not on the same disk.
* Test a restore from time to time. A lost passphrase means the backup cannot be opened.
* **Values already written to backups persist until those backups are deleted.** Changing or
  deleting a record, or pseudonymising a person, does not change older backups, and the change log
  keeps the old values of non-personal columns. Delete old backups according to the retention
  rules of the institution (the retention period is an open question, Q12).

## Classification

"Sensitive" is this project's working label for data that stays on the local machine. It is **not**
a classification under the access-to-information law (Lei 12.527/2011) or under military rules. The
project does not know whether any of the data is classified or access-restricted. As the plan reads
Lei 12.527/2011 art. 28 and Decreto 7.845/2012 art. 19, a classification is made by a formal
decision of the competent authority; this is not legal advice. If the data is classified, this
design (a plain SQLite database, plain automatic backups, commercial cryptography, an unsigned
binary from a public repository) is probably unsuitable, and real data must not be entered.

## Several people on one computer

The application is designed for one operator at a time. People can take turns on one machine only:

* with **one shared Windows account**; or
* with `--data-dir` pointing to a **local folder restricted to the committee**.

With separate Windows accounts each person gets a separate database in their own profile.

## LGPD note

The project assumes that the institution is the data controller. The software supports data
minimisation, operating-system access control and pseudonymisation of persons. An internal code is
pseudonymisation: the data stays personal data (LGPD art. 13, paragraph 4). The project's reading,
which is not legal advice, is that the national-defence exclusion of LGPD art. 4, III requires an
exclusive purpose and probably does not cover staff-management data. The legal assessment belongs
to the institution.
