# CBRN Readiness Dashboard

An offline Windows desktop application for recording and monitoring a hospital's chemical-defence (CBRN) readiness indicators:

- staff certified per PPE level, certificate validity, training and academic degrees;
- status and maintenance of beds, bays, negative-pressure and filtration equipment, and decontamination tents;
- the history of training courses and exercises, with participants, countries and aggregated evaluation results;
- annual budget execution per funding source;
- alerts for expiring certificates, pending maintenance and indicators outside their targets.

The interface is in Brazilian Portuguese (default), English and Spanish.

## Status

**Planning — no code yet.** The implementation plan, with requirements, architecture, data model and tasks, is in [PLAN.md](PLAN.md).

## Background

The application implements, as a preliminary and not yet validated tool, the readiness dashboard proposed as "PTT 2" in Appendix A of a doctoral thesis in Aerospace Sciences (UNIFA/PPGCA) on a Brazilian Air Force hospital's engagement with the OPCW.

## What it is not

- **Not connected:** no network access, no server, no telemetry. Data stays in a local file on the user's machine.
- **Not a store of real data:** this public repository holds code and clearly fictitious demo data only.
- **Not clinical:** it holds management data only. It contains no clinical or procedural content, and no text from the WHO guide or from internal hospital documents.
- **Not official:** it has not been institutionally validated or endorsed.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
