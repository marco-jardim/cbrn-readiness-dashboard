# Changelog

All notable changes to the CBRN Readiness Dashboard are recorded here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims at
[Semantic Versioning](https://semver.org/). Versions below 1.0.0 are preliminary and are published
as GitHub pre-releases.

This file records only the **status** of each open question (open / answered and applied locally /
answered and implemented in task Tn), never the content of an answer. See
[CONTRIBUTING.md](CONTRIBUTING.md) and section 12 of [PLAN.md](PLAN.md).

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

- The five modules of the requirements: personnel (people with an internal code, certificates per
  PPE level, training courses, degrees), infrastructure (beds, bays, negative-pressure and
  filtration equipment, decontamination tents and user-defined types, with status history and
  maintenance), exercises (editions, countries, results per user-defined metric), budget (allocated
  amount and dated execution per funding source and currency) and the change log. Records can be
  added, edited, deactivated and deleted.
- The indicators of `docs/indicators.md`, evaluated for any as-of date from the records as known
  today and with the current configuration. Indicator targets are entered in Settings; none exist
  by default, so every indicator reads "No target" until the committee enters them.
- The alerts (certificate expiry, maintenance, indicators outside their targets), the dashboard
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
The About dialog and the in-app help are not part of this entry.

### Placeholders still flagged in `domain/config.py`

These are the code-level flags of section 3.5 of the plan, as returned by
`flagged_placeholder_ids()`; a test compares this list with the code. The settings page
shows a "Placeholder - to be confirmed" badge for them until an operator confirms or changes the
value on that installation; that per-installation state does not change the flag in code.

Generic defaults (the flag may be cleared in code only when the project owner judges the value not
sensitive):

- `P01` - warning window before a certificate expires
- `P02` - warning window before maintenance is due
- `P04` - automatic snapshots
- `P05` - minimum backup passphrase length
- `P06` - number of automatic daily local backups kept
- `P07` - wording of the preliminary-version notice
- `P08` - pro-rating of the budget execution target
- `P09` - backup reminder period
- `A02` - PPE levels counted independently
- `A04` - certificate validity period per level
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
- Q18: open
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
- The branch protection of the repository is not configured from the repository itself.
- The manual smoke test has not been run, and the built zip has not been tried on a clean Windows
  machine without administrator rights.
- The indicators are not institutionally validated, and no target exists until the committee
  enters one.
