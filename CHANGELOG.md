# Changelog

All notable changes to the CBRN Readiness Dashboard are recorded here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims at
[Semantic Versioning](https://semver.org/). Versions below 1.0.0 are preliminary and are published
as GitHub pre-releases.

This file records only the **status** of each open question (open / answered and applied locally /
answered and implemented in task Tn), never the content of an answer. See
[CONTRIBUTING.md](CONTRIBUTING.md) and section 12 of [PLAN.md](PLAN.md).

## [1.0.1] - unreleased

**Version 1.0.0 was withdrawn.** The tag `v1.0.0` was created and the release workflow built it,
but its draft release was never published and was discarded. Version 1.0.1 replaces it; no
`1.0.0` file should be used.

**Status of this entry: prepared in the repository, not published.** The version is set to 1.0.1
in `src/cbrn_dashboard/__init__.py`, but no tag `v1.0.1` exists and no release has been created.
The release workflow (`.github/workflows/release.yml`) has never run for 1.0.1. A person still has
to run the full default and packaging test suites, tag `v1.0.1`, start the executable on a clean
Windows profile without administrator rights, run the manual smoke test
([docs/smoke-test.pt-BR.md](docs/smoke-test.pt-BR.md)), which has not been executed yet, run the
manual test script for the committee
([docs/manual-test-script.pt-BR.md](docs/manual-test-script.pt-BR.md)), which has not been executed
yet either, and publish the draft release that the workflow creates. This entry must be given a
date when that happens. No `0.1.0` release was published either: the entry below it is kept as the
record of what was prepared first.

**Preliminary version - indicators not institutionally validated.** The placeholders listed below
are still flagged in code, and the terminology review is pending.

### Changed since 0.1.0

The work of phases 8 to 10 of the plan, on top of the first preliminary version:

- Readiness snapshots (manual, monthly, with a report and retroactive), with the list on the Reports
  page, the withdrawal of a snapshot with a reason, and the validation export that uses them.
- PDF reports, internal and anonymised, with the suppression of small personnel counts in the
  anonymised one. The anonymised report is for internal use: the application never sends anything,
  and any external release is decided by the chain of command.
- CSV export, CSV import (a file with any error imports nothing) with import templates, and the
  Reports and Settings pages.
- The complete demo dataset (`--demo`), with its walkthrough in `docs/demo-walkthrough.md`.
- The in-app help and the About dialog.
- The accessibility pass over the interface.
- The built-in funding sources are DIRSA and COMAER (Comando da Aeronáutica).
- The wording "PPE qualification" (habilitação de EPI in Portuguese) in the interface and the
  documents, in place of "certificate".
- The reference documents: install guides in three languages, `docs/architecture.md`,
  `docs/indicators.md`, `docs/data-protection.md`, `docs/import-templates.md` and the manual test
  script for the committee (`docs/manual-test-script.pt-BR.md`).
- Qt third-party notices now shipped in full: `licenses\QT-THIRD-PARTY-NOTICES.txt` holds the
  notice and licence text of every component documented in the Qt source release of the bundled
  version, and the build fails when that file is not for the bundled Qt version.

### Changed since the 1.0.0 tag

- The bundle no longer ships the Universal CRT (`ucrtbase.dll` and the `api-ms-win-*` files),
  because Windows 10 and 11 always use their own copy.
- `licenses\MSVC-RUNTIME.md` lists every Visual C++ runtime file in any letter case (the
  `shiboken6` copies included) and states that these are Microsoft's files, not covered by the GPL,
  redistributed unmodified under Microsoft's terms (Q21, answered and implemented in task T9.2).
- The branch protection of `main` is configured on the hosting site (Q24: answered and applied
  locally).
- The source archives of Qt 6.12.0 and PySide6 6.12.0 are attached to the GitHub release next to
  the binary (Q20: answered and applied locally).
- The terminology review sheet tooling: `scripts/terminology_sheet.py` and
  `docs/revisao-terminologia.pt-BR.md`.
- The committee questionnaire, `docs/questionario-comite.pt-BR.md`.
- The manual-test guide, `docs/guia-teste-manual.pt-BR.md`.

### Placeholders still flagged in `domain/config.py`

These are the code-level flags of section 3.5 of the plan, as returned by
`flagged_placeholder_ids()`; a test compares this list with the code. No flag was cleared and no
default was changed for this version. The settings page shows a "Placeholder - to be confirmed"
badge for them until an operator confirms or changes the value on that installation; that
per-installation state does not change the flag in code.

Generic defaults (the flag may be cleared in code only when the project owner judges the value not
sensitive):

- `P01` - warning window before a PPE qualification expires
- `P02` - warning window before maintenance is due
- `P04` - automatic snapshots
- `P05` - minimum backup passphrase length
- `P06` - number of automatic daily local backups kept
- `P07` - wording of the preliminary-version notice
- `P08` - pro-rating of the budget execution target
- `P09` - backup reminder period
- `A02` - PPE levels counted independently
- `A04` - PPE qualification validity period per level
- `A05` - degraded assets count as unavailable
- `A06` - maintenance intervals
- `A07` - evaluation metrics
- `A08` - default currency
- `A09` - course list
- `A10` - degree status
- `A11` - small-count threshold of the anonymised report

Local-only values (never given a code default, flag never cleared in code, confirmed per
installation in Settings only):

- `P03` - indicator targets (local-only)
- `P10` - handling notice of the internal report (local-only)
- `D18` - institution and unit names (local-only)

### Assumptions without a setting

The assumptions A01, A03, A12, A13 and A14 carry no flag and are listed only through the open
question each depends on:

- A01 depends on Q5
- A03 depends on Q2
- A12 depends on Q12
- A13 depends on Q7
- A14 depends on Q4 and Q5

### Open questions

Status of each question of section 12 of the plan at the time of this entry. This repository
records no answer to any of them.

- Q1: open
- Q2: open
- Q3: open
- Q4: open
- Q5: open
- Q6: open
- Q7: open
- Q8: open
- Q9: open
- Q10: open
- Q11: open
- Q12: open
- Q13: open
- Q14: open
- Q15: open
- Q16: open
- Q17: open
- Q18: answered and applied locally
- Q19: open
- Q20: answered and applied locally
- Q21: answered and implemented in task T9.2
- Q22: answered and implemented in task T9.2
- Q23: open
- Q24: answered and applied locally

Q19 (formal classification), Q4, Q11 and Q13 gate the entry of real data. Until they are answered,
use only demo data. "Sensitive" is a working label of this project, not a classification.

### Translations (Q14)

The terminology review (Q14) by the committee is pending. The pt-BR and es-ES catalogues are drafts
and their messages are still marked `unfinished`; the en-US catalogue is the source language and
has none marked. The count was made over the `.ts` files in `src/cbrn_dashboard/i18n` (one
message, one `type="unfinished"` translation); a test compares it with the files.

- Messages still marked unfinished: 2056 (1028 in the pt-BR catalogues and 1028 in the es-ES
  catalogues), pending terminology review (Q14)

### Known limits

- The executable and the files beside it are unsigned. Windows SmartScreen, Smart App Control,
  AppLocker or WDAC may warn about or block them (see the install guides).
- The release workflow ran for the tag `v1.0.0`: it produced the zip, the checksums, the per-file
  manifest, the build-provenance attestation and a draft release, which was never published and
  was withdrawn. It will run again for the tag `v1.0.1`; that run has not happened yet.
- The Visual C++ runtime files are redistributed under Microsoft's terms (see
  `licenses\MSVC-RUNTIME.md`); the full Visual Studio licence text was not reviewed by counsel.
- The warning about writing reports or CSV exports to removable media is never shown, because the
  application does not detect removable drives.
- A read-only database on a network (UNC) path was never tried on a real network share.
- The branch protection of `main` is a setting of the hosting site (configured); it cannot be
  checked from the repository's files.
- The manual smoke test has not been run, the manual test script for the committee has not been
  run either, and the built zip has not been tried on a clean Windows machine without
  administrator rights.
- The indicators are not institutionally validated, and no target exists until the committee
  enters one.

## [0.1.0] - unreleased

**Status of this entry: prepared in the repository, not published.** The version is set to 0.1.0
in `src/cbrn_dashboard/__init__.py`, but no tag `v0.1.0` exists and no release has been created.
The release workflow (`.github/workflows/release.yml`) has never run. A person still has to tag
`v0.1.0`, run the manual smoke test ([docs/smoke-test.pt-BR.md](docs/smoke-test.pt-BR.md)), which
has not been executed yet, and publish the draft pre-release that the workflow creates. This entry
must be given a date when that happens.

**Preliminary version - indicators not institutionally validated.**

### Added

The first preliminary version, the MVP of the plan (phases 0 to 7, readiness snapshots, the licence
bundle, the release pipeline, the first-run notes and this release task):

- The five modules of the requirements: personnel (people with an internal code, PPE qualifications
  per level, training courses, degrees), infrastructure (beds, bays, negative-pressure and
  filtration equipment, decontamination tents and user-defined types, with status history and
  maintenance), exercises (editions, countries, results per user-defined metric), budget (allocated
  amount and dated execution per funding source and currency) and the change log. Records can be
  added, edited, deactivated and deleted.
- The indicators of `docs/indicators.md`, evaluated for any as-of date from the records as known
  today and with the current configuration. Indicator targets are entered in Settings; none exist
  by default, so every indicator reads "No target" until the committee enters them.
- The alerts (PPE qualification expiry, maintenance, indicators outside their targets), the dashboard
  with tiles, charts and table views, and the start-up summary.
- Readiness snapshots (manual, monthly and retroactive), which are the only record of what was
  known and configured at the time. They are withdrawn, never deleted.
- The interface in Brazilian Portuguese (default), English and Spanish, with live switching.
- Local storage in the user profile, read-only handling, location warnings and the first-run
  data-protection notice.
- Automatic local backups, encrypted manual backups (`.cbrnbak`) and restore.
- The demo mode (`--demo`) with a separate database of fictitious data.
- The Windows one-folder build with a self-test, the bundled third-party licence texts, the
  first-run notes in three languages, a portable-mode example, and the release workflow that
  produces the zip, `SHA256SUMS.txt`, the per-file manifest `SHA256-FILES.txt`, a provenance
  attestation and a draft pre-release.

Also already in the source tree, although the plan assigns them to version 1.0: PDF reports
(internal and anonymised), CSV export and import, the validation export, the Reports and Settings
pages, the install guides in three languages, `docs/architecture.md`, `docs/indicators.md`,
`docs/data-protection.md`, `docs/import-templates.md` and `docs/demo-walkthrough.md`. They were
implemented in the same run as the MVP and are not separately scoped or reviewed as a release.
The About dialog and the in-app help are also part of this entry.

Also in this entry:

- The built-in funding sources are DIRSA and COMAER (requirement R24, migration 0008). The OPCW
  Trust Fund is no longer built in: it is removed when no budget entry uses it, and otherwise kept
  as an inactive user-defined source so no recorded amount is lost.
- The PPE qualification wording of the interface and the documents.
- The anonymised report is for internal use.

### Placeholders still flagged in `domain/config.py`

These are the code-level flags of section 3.5 of the plan, as returned by
`flagged_placeholder_ids()`; a test compares this list with the code. The settings page
shows a "Placeholder - to be confirmed" badge for them until an operator confirms or changes the
value on that installation; that per-installation state does not change the flag in code.

Generic defaults (the flag may be cleared in code only when the project owner judges the value not
sensitive):

- `P01` - warning window before a PPE qualification expires
- `P02` - warning window before maintenance is due
- `P04` - automatic snapshots
- `P05` - minimum backup passphrase length
- `P06` - number of automatic daily local backups kept
- `P07` - wording of the preliminary-version notice
- `P08` - pro-rating of the budget execution target
- `P09` - backup reminder period
- `A02` - PPE levels counted independently
- `A04` - PPE qualification validity period per level
- `A05` - degraded assets count as unavailable
- `A06` - maintenance intervals
- `A07` - evaluation metrics
- `A08` - default currency
- `A09` - course list
- `A10` - degree status
- `A11` - small-count threshold of the anonymised report

Local-only values (never given a code default, flag never cleared in code, confirmed per
installation in Settings only):

- `P03` - indicator targets (local-only)
- `P10` - handling notice of the internal report (local-only)
- `D18` - institution and unit names (local-only)

### Assumptions without a setting

The assumptions A01, A03, A12, A13 and A14 carry no flag and are listed only through the open
question each depends on:

- A01 depends on Q5
- A03 depends on Q2
- A12 depends on Q12
- A13 depends on Q7
- A14 depends on Q4 and Q5

### Open questions

Status of each question of section 12 of the plan at the time of this entry. This repository
records no answer to any of them.

- Q1: open
- Q2: open
- Q3: open
- Q4: open
- Q5: open
- Q6: open
- Q7: open
- Q8: open
- Q9: open
- Q10: open
- Q11: open
- Q12: open
- Q13: open
- Q14: open
- Q15: open
- Q16: open
- Q17: open
- Q18: answered and applied locally
- Q19: open

Q19 (formal classification), Q4, Q11 and Q13 gate the entry of real data. Until they are answered,
use only demo data. "Sensitive" is a working label of this project, not a classification.

### Translations (Q14)

The terminology review (Q14) by the committee is pending. The pt-BR and es-ES catalogues are drafts and
their messages are still marked `unfinished`; the en-US catalogue is the source language. No count
of pending messages is recorded in this entry.

### Known limits

- The executable and the files beside it are unsigned. Windows SmartScreen, Smart App Control,
  AppLocker or WDAC may warn about or block them (see the install guides).
- The release workflow has never run, so the zip, the checksums, the per-file manifest and the
  draft release have not been produced by it.
- The provenance attestation may need a public repository, or a GitHub plan that supports it for
  private repositories. This is to be confirmed.
- Qt's third-party attributions are a pointer only (`licenses\QT-THIRD-PARTY.md`): the PySide6
  wheels carry no SBOM or attribution files.
- The wording about the redistribution of the Microsoft Visual C++ runtime in the bundled licence
  notice (`licenses\MSVC-RUNTIME.md`, which points to Microsoft's published terms) has not been
  confirmed.
- A read-only database on a network (UNC) path was never tried on a real network share.
- The branch protection of `main` is a setting of the hosting site; it cannot be checked from
  the repository's files.
- The manual smoke test has not been run, and the built zip has not been tried on a clean Windows
  machine without administrator rights.
- The indicators are not institutionally validated, and no target exists until the committee
  enters one.
