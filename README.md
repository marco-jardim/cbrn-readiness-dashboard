# CBRN Readiness Dashboard

An offline Windows desktop application for recording and monitoring a hospital's chemical-defence (CBRN) readiness indicators:

- staff certified per PPE level, certificate validity, training and academic degrees;
- status and maintenance of beds, bays, negative-pressure and filtration equipment, and decontamination tents;
- the history of training courses and exercises, with participants, countries and aggregated evaluation results;
- annual budget execution per funding source;
- alerts for expiring certificates, pending maintenance and indicators outside their targets.

The interface is in Brazilian Portuguese (default), English and Spanish.

## Status

**Version 0.1.0 is prepared in this repository. No release has been published yet.** The version is set and the release material is written ([CHANGELOG.md](CHANGELOG.md), [manual smoke test](docs/smoke-test.pt-BR.md)), but nothing is tagged: a person must still tag `v0.1.0`, run the smoke test on a clean Windows profile and publish the draft pre-release that the release workflow creates. Published releases will appear on the [releases page](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases); until then there is no file to download. The executable will be unsigned, and the tool is preliminary and not institutionally validated. The implementation plan, with requirements, architecture, data model and tasks, is in [PLAN.md](PLAN.md).

What exists in the repository:

- the application itself: personnel, infrastructure, exercises and budget modules, the indicator dashboard, alerts, PDF reports, CSV export and import, readiness snapshots, encrypted backups and restore, and the interface in three languages;
- a demo mode (`--demo`) with a separate database of fictitious data;
- a self-test and the packaging and release scripts for the Windows build;
- the documentation below.

Documentation:

- Install guides: [English](docs/install.en-US.md), [Português](docs/install.pt-BR.md), [Español](docs/install.es-ES.md).
- [Demo walkthrough](docs/demo-walkthrough.md): what the demo database shows on each page.
- [Architecture](docs/architecture.md): layers, package map, migrations, translations and how to add a module.
- [Indicator reference](docs/indicators.md): every indicator, its definition, default target and placeholder status.
- [Data protection](docs/data-protection.md): what is stored, where, and how it is protected.
- [Import templates](docs/import-templates.md): the CSV layouts accepted by the import.

## Background

The application implements, as a preliminary and not yet validated tool, the readiness dashboard proposed as "PTT 2" in Appendix A of a doctoral thesis in Aerospace Sciences (UNIFA/PPGCA) on a Brazilian Air Force hospital's engagement with the OPCW.

## What it is not

- **Not connected:** no network access, no server, no telemetry. Data stays in a local file on the user's machine.
- **Not a store of real data:** this public repository holds code and clearly fictitious demo data only.
- **Not clinical:** it holds management data only. It contains no clinical or procedural content, and no text from the WHO guide or from internal hospital documents.
- **Not official:** it has not been institutionally validated or endorsed.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
