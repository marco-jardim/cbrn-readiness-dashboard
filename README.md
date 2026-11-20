# CBRN Readiness Dashboard

An offline Windows desktop application for recording and monitoring a hospital's chemical-defence (CBRN) readiness indicators:

- staff with a PPE qualification per level (practical qualification in donning and doffing the protective ensemble), its validity, training and academic degrees;
- status and maintenance of beds, bays, negative-pressure and filtration equipment, and decontamination tents;
- the history of training courses and exercises, with participants, countries and aggregated evaluation results;
- annual budget execution per funding source;
- stock of CBRN antidotes, decontaminants and other consumables by lot (in preparation for 1.1.0): 17 built-in item types plus your own, dated movements (receipts, issues, disposals, losses, adjustments) with a balance that never goes negative, expiry dates, a minimum stock per type, a page "Antídotos e descontaminantes" with an expiry schedule, and a Dashboard shortcut to it;
- alerts for expiring PPE qualifications, pending maintenance, expired or expiring stock lots, low stock and indicators outside their targets.

The interface is in Brazilian Portuguese (default), English and Spanish.

## Status

The version in the source is **1.1.0**, in preparation and not published yet (no tag `v1.1.0`; it adds the stock by lot and the antidotes and decontaminants page, and the tag, CI run, manual test and publication are still pending; see the [CHANGELOG.md](CHANGELOG.md)). The latest published release is 1.0.2. **Version 1.0.2 was published on GitHub on 2026-11-14** as the tag `v1.0.2`: see the [release page](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.0.2) and the [releases page](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases). The previous release, version 1.0.1, was published on 2026-11-13 as the tag `v1.0.1` ([release page](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.0.1)); version 1.0.0 was tagged and built, but its draft release was never published and was withdrawn. The owner published 1.0.2 before the manual test on a clean Windows profile, which is **still pending** ([manual smoke test](docs/smoke-test.pt-BR.md), [manual test script for the committee](docs/manual-test-script.pt-BR.md)); its result will be recorded in the [CHANGELOG.md](CHANGELOG.md). On the downloaded assets, every SHA-256 matched `SHA256SUMS.txt`, `gh attestation verify` passed for the installer and the zip, and the installer passed the silent install, self-test and silent uninstall smoke test. The executable is unsigned, and the indicators are not institutionally validated: several placeholder values are still flagged and the terminology review is pending (see the changelog). The implementation plan, with requirements, architecture, data model and tasks, is in [PLAN.md](PLAN.md).

Downloads (on the [release page of 1.0.2](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.0.2)): from version 1.0.2 on, the release workflow builds a per-user **installer** (`cbrn-readiness-dashboard-<version>-win-x64-setup.exe`, for example `cbrn-readiness-dashboard-1.1.0-win-x64-setup.exe` once 1.1.0 is published; made with Inno Setup; the recommended download; no administrator rights needed; uninstalling keeps your data) and the **portable zip** (`cbrn-readiness-dashboard-<version>-win-x64.zip`, for IT teams and portable mode), with `SHA256SUMS.txt` covering both. The workflow installs the installer silently, runs the self-test of the installed program and uninstalls it before it creates the release. Version 1.0.1 has the zip only. The installer is unsigned too; see the [install guides](docs/install.en-US.md).

What exists in the repository:

- the application itself: personnel, infrastructure, exercises and budget modules, stock by lot with the antidotes and decontaminants page (new in 1.1.0, not published yet), the indicator dashboard, alerts, PDF reports (the anonymised report carries stock counts only), CSV export and import, readiness snapshots, encrypted backups and restore, and the interface in three languages;
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
- [Manual test guide](docs/guia-teste-manual.pt-BR.md) (Portuguese): how to run the manual tests on a clean Windows profile without administrator rights.
- [Questionnaire for the CBRN defence committee](docs/questionario-comite.pt-BR.md) (Portuguese): the open questions of the plan, in plain language; answers are kept outside the repository.
- [Code signing policy](CODE-SIGNING-POLICY.md): which file the project would sign, by whom, who approves each release, and how to check the signature.

## Code signing policy

The executable is unsigned today. This project is preparing to use free code signing for open-source projects; the full policy is in [CODE-SIGNING-POLICY.md](CODE-SIGNING-POLICY.md) (Code signing policy).

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- **Committers and reviewers:** [marco-jardim](https://github.com/marco-jardim)
- **Approvers:** [marco-jardim](https://github.com/marco-jardim)

**Privacy policy:** This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.

## Background

The application implements, as a preliminary and not yet validated tool, the readiness dashboard proposed as "PTT 2" in Appendix A of a doctoral thesis in Aerospace Sciences (UNIFA/PPGCA) on a Brazilian Air Force hospital's engagement with the OPCW.

## What it is not

- **Not connected:** no network access, no server, no telemetry. Data stays in a local file on the user's machine.
- **Not a store of real data:** this public repository holds code and clearly fictitious demo data only.
- **Not clinical:** it holds management data only. It contains no clinical or procedural content, and no text from the WHO guide or from internal hospital documents.
- **Not official:** it has not been institutionally validated or endorsed.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
