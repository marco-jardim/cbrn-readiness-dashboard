# CBRN Readiness Dashboard — Implementation Plan

| | |
|---|---|
| Repository | `marco-jardim/cbrn-readiness-dashboard` (public) |
| Licence | GPL-3.0-or-later |
| Plan status | Draft for review by the project owner and the hospital's CBRN defence committee. Implemented up to T10.5 for v1.0.x and up to T11.18 for version 1.1.0, which is published (T11.19, the release, is done except the manual test, still pending). Version 1.1.0 (stock by lot, antidotes and decontaminants; owner request of 2026-11-20) was published on GitHub on 2026-11-21 (tag `v1.1.0`, commit `6e192b7`; installer, zip and the Qt/PySide6 sources attached by CI; the signing job was skipped because SignPath is not configured; on the downloaded assets the hashes matched, `gh attestation verify` passed for the installer and the zip, and the installer passed the silent install, self-test and uninstall smoke test). The previous published release is v1.0.2 (per-user installer, optional SignPath signing, off; tag `v1.0.2`, commit `4d57a4f`), published on 2026-11-14, and before it v1.0.1 (tag `v1.0.1`, commit `1a02e2f`; v1.0.0 was withdrawn), published on 2026-11-13; all three were published before the manual test, because the SignPath Foundation open-source programme requires an already released project. Still open from section 13: the manual test on a clean Windows profile (item 10, `docs/manual-test-script.pt-BR.md`), the committee's terminology review (Q14, item 6) and the questions of section 12 that the committee has not answered. The manual test of 1.1.0 has not been executed (T11.19 pending for that step only). |
| Requirements source | Appendix A of the thesis, product "PTT 2" (appendix source lines 55–95, in Portuguese). `Lnn` = line *nn* of that source. The source is not in this repository (the thesis is unpublished), so the R01–R36 quotes and the `Lnn` references cannot be checked from the repository alone. They were checked against `postextual/apendice-a.tex` of the private thesis repository, commit `f8b1d65a76b53019573fb789c09d3d938dbffb59` (2026-11-13), SHA-256 `fbe30bc40ff6ab5ebace449dd3309e2dc2ff8f216d4ad9048c77a83b9c6661c1` (Q18). |
| Date | 2026-11-12 |

Contents: 1 Summary · 2 Scope and non-goals · 3 Requirements · 4 Architecture and stack decisions · 5 Data model · 6 Internationalisation · 7 Security and privacy · 8 Packaging and distribution · 9 Testing strategy · 10 Phases and tasks · 11 Risks and mitigations · 12 Open questions for the author · 13 Definition of done for version 1.0

---

## 1. Summary

The CBRN Readiness Dashboard is an offline Windows desktop application. The hospital's CBRN defence committee (CDQBRN) uses it to record, in one place, the readiness indicators that Appendix A lists for "PTT 2", and to monitor them continuously. The indicators are:
- staff with a PPE qualification per level, with its validity, training and academic degrees;
- beds, bays, negative-pressure and filtration equipment, and decontamination tents, with their status and maintenance;
- the history of the CBRAMED and EXBRAMED editions;
- annual budget execution per funding source;
- alerts derived from all of the above (L65, L74–L82).

What the solution looks like:
- Python 3.12 and PySide6 (Qt Widgets). Data is kept in a SQLite file in the user's Windows profile. There is no network code at all. The data is called "sensitive" in this plan as a working label; that is not a formal classification (§7.1, Q19).
- The interface is in pt-BR (default), en-US and es-ES, and the user can switch language while the app is running.
- PyInstaller builds a portable, unsigned executable that ships as a zip folder. No installer, no admin rights.
- Licensed GPL-3.0-or-later. The public repository holds code and clearly fictitious demo data only.

The appendix states intent, not specifications. It names the modules and what the indicators are about, but gives no formulas, targets, validity periods, users or report layouts. This plan therefore:
- implements exactly the subject matter the appendix names;
- makes every rule configurable;
- ships clearly marked placeholder defaults and no invented readiness targets;
- lists the decisions the committee must take (§12).

Two releases are planned:
- **MVP v0.1** (Phases 0–7, plus readiness snapshots (T8.1), the licence bundle, the release pipeline, the first-run notes and the release task T9.6). It contains all five modules with data entry, indicators evaluated for any as-of date from the records as known today and with the current configuration, alerts, the dashboard, readiness snapshots (the only record of what was known and configured at the time; withdrawn, never deleted), the trilingual UI, a change log, encrypted backup and restore, and the portable build. This is enough for the committee to review the indicators and placeholders with demo data first. Entering real data waits for the answers to Q19 (formal classification), Q4, Q11 and Q13 (§12); after that the committee can record readings from the start.
- **v1.0** (the rest of Phases 8–10). It adds PDF reports (internal, and aggregated/anonymised), CSV import and export for the 2022–2025 retroactive data, the export needed for the predictive-validity comparison (L87), the final build and the user documentation.

v1.0 is a preliminary tool that has not been validated by the institution. Homologation (L87) is an institutional step outside the software.

Labels used in this plan:
- **R**: explicit requirement from the appendix.
- **F**: fixed decision by the project owner.
- **I**: implicit requirement, a necessary consequence of R or F.
- **D**: design decision made in this plan.
- **A / P**: assumption or placeholder default that needs confirmation, linked to an open question **Q**.
- **O**: owner request outside Appendix A (dated, §3.1b).
- **T**: task (§10). **X**: deferred item (§10.4).

---

## 2. Scope and non-goals

### 2.1 In scope (v1.0)
- The five modules of L74–L82 and the dashboard (R01–R27).
- As-of-date evaluation of every indicator, readiness snapshots and the validation export (R04, R29, R31).
- PDF reports, both internal and aggregated/anonymised, plus CSV import and export (R11, R13, R29).
- Local storage, backups, the trilingual UI, the portable Windows build, and a public CI and release pipeline.

### 2.2 Non-goals
- PTT 1, the technical-operational manual (L3–L53). Also out: any clinical, triage, decontamination or antidote content (indications, doses, protocols). Recording the stock of antidotes and decontaminants as management data (types, lots, quantities, expiry dates, prices, movements) is in scope from v1.1 (O01-O04). The application stores management data only (D19).
- Any text from the WHO guide "Initial clinical management of chemical weapons" (CC BY-NC-SA) or from internal hospital documents (F06).
- Servers, web or mobile versions, several users editing at the same time, databases on network shares (D05).
- Integration with hospital, human-resources or financial systems; automatic data collection.
- Sending anything to anyone outside the app: the app produces files; people decide where they go.
- The statistical analysis of predictive validity. The app exports the data; the analysis happens elsewhere.
- Institutional homologation (R30), code signing (D10), installers, auto-update.
- Personal data of exercise participants (D20).
- macOS and Linux builds. The code may run there, but only Windows is built and tested.

### 2.3 Glossary
| Term | Meaning in this plan |
|---|---|
| CDQBRN | The hospital's CBRN defence committee: the primary user and the audience for management views (L69). |
| CTH | The hospital's hybrid treatment centre, whose beds, bays and equipment are tracked (L65, L76). |
| EPI / PPE levels A, B, C | Protection levels named in L74. The app records them; it does not define them. |
| PPE qualification (level A/B/C) | Practical qualification in donning and doffing the protective ensemble of that level, with a valid-until date. Levels classify ensembles (OSHA 29 CFR 1910.120 App. B), not people; no official per-person certification per level was found (research 2026-11-13). The thesis term "certificação por nível de EPI" maps to this record. |
| CBRAMED, EXBRAMED | The course and exercise series whose history the exercises module records (L78). |
| DIRSA | The Air Force health directorate. It is both a report recipient and a funding source (L65, L80). |
| OPAQ / OPCW | Organisation for the Prohibition of Chemical Weapons. Its Trust Fund receives the contribution of Brazil; it is not a funding source of the hospital. The thesis (L69) names its Technical Secretariat as a recipient of aggregated anonymised reports; the app's anonymised report is for internal use, and any external release is decided by the chain of command (owner decision 2026-11-13; see Q10, Q19). |
| COMAER | Comando da Aeronáutica (Air Force Command), a built-in funding source together with DIRSA (L80). |
| QBRN | Portuguese and Spanish for CBRN. |
| Today | The local calendar date on the workstation, defined in `clock.py`. Day and month boundaries (daily backup, monthly snapshot) use it; stored timestamps stay UTC. |
| As-of date | The date for which every indicator and alert is computed. Defaults to today (D13). |

---

## 3. Requirements

### 3.1 Explicit requirements from Appendix A (PTT 2) and traceability

The appendix defines **five modules**: personnel (L74), infrastructure (L76), exercises (L78), budget (L80) and alerts (L82). Phases are listed in §10; "—" means the item is not a software feature. The Phase column of this table is authoritative; the phase introductions in §10.3 list only the primary requirements of each phase. The appendix source is not in the repository, so the quotes and `Lnn` references below cannot be verified from the repository alone; the source version and hash are recorded in the header and in Q18.

| ID | Appendix statement (line) | Feature in this plan | Phase |
|---|---|---|---|
| R01 | "Painel de Indicadores de Prontidão Operacional e Capacitação QBRN do HFAG (*Dashboard* CDQBRN)" (L55) | The application itself; dashboard overview page | P0, P6 |
| R02 | "Produto tecnológico - sistema de informação e gestão" (L57) | Data-entry and management desktop app with a local database | P1–P5 |
| R03 | "sem um instrumento único de consolidação" (L61) | One local database for all modules; CSV import of existing records | P1–P5, P8 |
| R04 | "leitos, pessoal qualificado, investimento e evolução histórica do CTH" (L61) | History: as-of-date evaluation, status and maintenance history, snapshots | P1, P3, P8 |
| R05 | "verificada apenas episodicamente [...] e não por um mecanismo de acompanhamento contínuo" (L61) | Dashboard re-evaluated on every start; start-up alert summary; periodic snapshots | P6, P8 |
| R06 | "Centralizar e monitorar de forma contínua os indicadores de prontidão QBRN" (L65) | Indicator framework and dashboard | P1, P6 |
| R07 | "pessoal certificado por nível de EPI e validade da certificação" (L65) | Personnel module (PPE qualification per level, with validity) | P2 |
| R08 | "disponibilidade de leitos e equipamentos do CTH" (L65) | Infrastructure module | P3 |
| R09 | "histórico de exercícios realizados" (L65) | Exercises module | P4 |
| R10 | "execução orçamentária" (L65) | Budget module | P5 |
| R11 | "subsidiar decisões da CDQBRN/HFAG e a prestação de contas à DIRSA e à OPAQ" (L65) | Internal PDF report; CSV export | P8 |
| R12 | "Gestão da CDQBRN/HFAG; Diretoria de Saúde da Aeronáutica (DIRSA); Comando da Aeronáutica" (L69) | Audience of the dashboard and internal reports (not app accounts; see D05) | P6, P8 |
| R13 | "em relatórios agregados e anonimizados, o Secretariado Técnico da OPAQ" (L69) | Aggregated, anonymised report variant (internal use; external release outside the app) | P8 |
| R14 | "quantitativo de profissionais certificados por nível de EPI (A, B, C)" (L74) | Count of staff with a valid PPE qualification per level, as of a date | P2 |
| R15 | "validade das certificações e necessidade de reciclagem" (L74) | Expiry tracking; list of staff needing retraining | P2, P6 |
| R16 | "capacitação e titulação (especialização, mestrado, doutorado)" (L74) | Training records; academic degrees | P2 |
| R17 | "leitos e baias disponíveis no CTH" (L76) | Bed and bay register with operational status; availability counts | P3 |
| R18 | "status operacional dos equipamentos de pressão negativa e filtragem" (L76) | Equipment register with status history | P3 |
| R19 | "tendas de descontaminação" (L76) | Tent register with status | P3 |
| R20 | "data da última manutenção" (L76) | Maintenance log; last and next maintenance | P3 |
| R21 | "histórico do CBRAMED e do EXBRAMED" (L78) | Register of editions | P4 |
| R22 | "número de participantes e países representados" (L78) | Participant count and country list per edition | P4 |
| R23 | "resultados agregados de avaliação" (L78) | Aggregated evaluation results per edition (configurable metrics) | P4 |
| R24 | "execução financeira anual por fonte (Comando da Aeronáutica, DIRSA)" (L80; revised in thesis commit f8b1d65, 2026-11-13) | Annual budget entries per source; execution rate | P5 |
| R25 | "certificações a vencer" (L82) | PPE qualification expiry alerts | P6 |
| R26 | "manutenções pendentes" (L82) | Maintenance due and overdue alerts | P6 |
| R27 | "indicadores fora do padrão esperado de prontidão" (L82) | Configurable indicator targets; out-of-target alerts | P6 |
| R28 | "levantamento de requisitos junto à CDQBRN/HFAG, prototipação incremental" (L87) | Open questions (§12); configurable rules; incremental releases (MVP, then 1.0) | all |
| R29 | "testes com dados retroativos do período 2022-2025" (L87) | CSV import; indicators computed for past dates | P1, P8 |
| R30 | "culminando em homologação institucional" (L87) | Outside the software; v1.0 is handed over for institutional evaluation | — |
| R31 | "comparação entre a leitura de prontidão indicada pelo painel e o desempenho efetivamente observado no ciclo seguinte de EXBRAMED" (L87) | Readiness snapshots; validation export pairing the reading before each edition with that edition's results | P8 |
| R32 | "parceria com instituições de ensino da própria Aeronáutica" (L91) | Not a feature. Architecture notes and the contribution guide make handover to a partner team easier | P0, P10 |
| R33 | "respeitando os protocolos de segurança da informação aplicáveis a dados sensíveis" (L91) | Security and privacy controls (§7); the institutional protocol still has to be confirmed (Q11) | P0, P7, P8 |
| R34 | "prazo estimado de doze a dezoito meses" (L91) | Schedule context only (§10.5) | — |
| R35 | "maior capacidade de resposta a auditorias e inspeções da OPAQ" (L95) | Reports; append-only change log | P1, P8 |
| R36 | "decisão gerencial sobre reciclagem de pessoal, manutenção de equipamentos e planejamento orçamentário" (L95) | Retraining list, maintenance-due list, budget execution view | P2, P3, P5, P6 |

### 3.1b Owner requests (not from Appendix A)

These requests come from the project owner, not from the appendix, so they carry no `Lnn` reference and no quote. They extend the plan from version 1.1 (Phase 11). They are management data only: no dose, indication or protocol field exists (§2.2, D19, D38).

| ID | Request (owner, 2026-11-20) | Feature | Phase |
|---|---|---|---|
| O01 | Stock by lot for 17 item types (quantity, lot, expiry date, unit price), on the Infraestrutura page next to the per-unit assets, with one "Tipo" filter over both | Stock lots; the "Estoque (lotes)" tab of Infraestrutura | P11 |
| O02 | Dated movements: the quantity on any as-of date is computed from the movements, with history and the change log | Stock movements; as-of views; change log | P11 |
| O03 | A page "Antídotos e descontaminantes" for the four antidote and decontaminant types: lots, movements, follow-up, an expiry schedule by month and an alerts panel; a shortcut and tiles on the dashboard | The antidotes page; dashboard shortcut and stock tiles | P11 |
| O04 | A configurable minimum per item type, empty by default (a placeholder); an indicator and an alert when the valid quantity is below it | Minimum stock per type; `STOCK_TYPES_BELOW_MIN`; `LOW_STOCK` | P11 |

### 3.2 Fixed decisions (project owner)
| ID | Decision |
|---|---|
| F01 | A Python desktop application for Windows, delivered as a portable executable. No installer, no admin rights. |
| F02 | Local database only, fully offline. No server, no telemetry, no network calls. |
| F03 | Interface in pt-BR (default), en-US and es-ES, switchable by the user. The appendix uses the same three languages for PTT 1's glossary (L40); for PTT 2 the languages are an owner decision, not an appendix requirement. |
| F04 | GPL-3.0-or-later, published in the public repository `marco-jardim/cbrn-readiness-dashboard`. |
| F05 | Real data (staff qualifications, infrastructure status, exercises, budget) is sensitive. It leaves the user's machine only through operator-initiated reports, exports and backups. The repository holds only code and clearly fictitious demo data. "Sensitive" is a working label, not a legal classification (§7.1, Q19). |
| F06 | No text from the WHO guide "Initial clinical management of chemical weapons" (its non-commercial clause is incompatible with the GPL) or from internal hospital documents, anywhere in the application or the repository. |

### 3.3 Implicit requirements
| ID | Requirement | Follows from |
|---|---|---|
| I01 | Data persists across sessions and application upgrades, via versioned schema migrations with an automatic backup first | R06, F02 |
| I02 | Backup and restore, because the local file is the only copy | F02 |
| I03 | Every indicator can be evaluated for any as-of date, past or present, from the dated records as known today and with the current configuration. Snapshots are the only record of what was known and configured at the time | R04, R29, R31 |
| I04 | Rules, warning windows and targets are configurable | R28 (requirements have not been gathered yet) |
| I05 | Input validation and data-quality warnings | R06 |
| I06 | A visible "preliminary, not validated" notice in the UI and in reports — withdrawn by D39 (T12.4, T12.13) | R30 |
| I07 | Demo data kept strictly separate from real data | F05 |

### 3.4 Design decisions register
| ID | Decision | Detail |
|---|---|---|
| D01 | PyInstaller one-folder build, distributed as a zip | §4.3 |
| D02 | Data stored in the user's profile by default; opt-in portable mode; read-only handling | §4.3 |
| D03 | At-rest protection: data minimisation, OS-level protection, encrypted backups. Encrypting the live database is deferred | §4.3, §7 |
| D04 | Automatic local backups, encrypted manual backups, CSV/PDF export, CSV import | §4.3 |
| D05 | One local operator, no accounts or roles, an append-only change log | §4.3 |
| D06 | Standard-library `sqlite3`, hand-written SQL, numbered SQL migrations keyed on `user_version` | §4.3 |
| D07 | Qt Linguist translation catalogues (`.ts`/`.qm`), English source strings, one catalogue per area | §4.3, §6 |
| D08 | Qt Charts, used through a thin adapter | §4.3 |
| D09 | PDF made with Qt's own PDF writer, plus CSV. XLSX deferred | §4.3 |
| D10 | GitHub Actions on Windows. Unsigned executable; SHA-256 checksums and build-provenance attestation | §4.3, §8 |
| D11 | Layers: a domain layer with no Qt or I/O, a Qt-free services layer, and the UI | §4.1 |
| D12 | Python 3.12 pinned | §4.2 |
| D13 | A global as-of date selector; every indicator is evaluated for the chosen date from the dated records as known today and with the current configuration (snapshots hold what was known and configured at the time) | §5.4 |
| D14 | Indicator statuses OK / Warning / Critical / No target / No data. No default targets | §5.4 |
| D15 | Money stored as whole minor units (cents) with an ISO 4217 currency code taken from an allow-list that also holds the decimal places (BRL, USD, EUR to start). No conversion; totals never mix currencies | §5 |
| D16 | Built-in list entries mirror the appendix wording. Users may add entries; only the pt-BR label is mandatory for them, and the other languages fall back as §6 describes | §5, §6 |
| D17 | Staff identified by an internal code. No national ID numbers, birth dates, contact or health data, and no free-text `notes` columns on personal records. A "pseudonymise person" action replaces the identifier and each degree `field` with random codes and clears the label and PPE qualification references, but keeps PPE qualifications and history | §5.1, §7 |
| D18 | Institution and unit names are set locally in Settings, never hard-coded | §7 |
| D19 | The application contains no clinical or procedural content | §2.2 |
| D20 | Exercise participants recorded only as counts; countries as ISO 3166-1 alpha-2 codes | §5 |
| D21 | Snapshots taken manually, monthly, and whenever a report is generated | §5.4 |
| D22 | Log files contain event codes, exception types and stack frames only, never record contents or exception messages | §7 |
| D23 | Status shown as text plus icon plus a colour-blind-safe colour, never colour alone | §10 (T6.5, T10.4) |
| D24 | A PPE qualification can be marked "no renewal" from a date (`no_renewal_from`), which stops expiry alerts for it from that date | §5.5 |
| D25 | Demo data lives in a separate database file with its own backups, every identifier starts with `DEMO`, and a permanent banner is shown. The banner, a PDF watermark and the `DEMO-` prefix on CSV file names are driven by `app_meta.is_demo`, not by the command-line flag | §7 |
| D26 | An asset with no status event on or before the as-of date has the status "unknown": not available, and flagged as a data-quality issue | T3.2 |
| D27 | Negative budget amounts are rejected; corrections are made by editing the entry, and every edit is recorded in `change_log` | T5.3 |
| D28 | `staff_member.category` is treated as personal free text while Q4 (whether to record a category, and from which coded list) is open: like `identifier` and `label`, its value never reaches `change_log` (only the fact that it changed), "pseudonymise person" clears it, and its input shows the free-text hint (QA finding P2-01). Stays in force after Q4 was answered (D39); any change that follows from the answer needs its own task | §5.1, T2.3, T2.4, Q4 |
| D29 | `EX_LAST_COUNTRIES`, empty country set: an edition saved with no countries is read as "countries not entered", not as zero countries, so the indicator is No data (D14) for that kind, as it is for participants not recorded. An edition that really had no foreign participation cannot be told apart from one whose countries were not filled in; an operator who wants to show a real zero (no foreign participation) should record the host country. The number of countries in the editions table still shows 0 for such an edition (QA finding P4-04) | §5.4, T4.3, T4.5 |
| D30 | A chart value that is not recorded (`None`) is not drawn as a value: its bar has no height, the legend entry of its series names the categories that are not recorded ("… (not recorded: …)"), the legend is shown whenever a value is missing, and reading the chart back gives `None` for those categories. Inside Qt the bar still holds 0, so the legend note is what tells a missing value from a recorded 0. Chart axis numbers follow the locale of the language in use (QA finding P6-05) | D08, T6.4, T6.5, T8.6 |
| D31 | When the data folder named by `--data-dir` or by `CBRN_DASHBOARD_DATA_DIR` is unusable (not writable and holding no database), the offer to choose another folder says the choice is for this session only, and the chosen folder is used for this session only: no `location.json` pointer is written. These two sources rank above the pointer (D02), so a pointer written then would be ignored by the next start with the same option and followed only by a later plain start, which would move the data silently. Other sources keep the T7.5 behaviour (QA finding P7-05) | D02, T7.5 |
| D32 | Stock is recorded by lot, separate from the per-unit assets. A lot has no operational status and no maintenance. An item that needs both stock and per-unit tracking is two records until Q25 is answered | O01, T11.3, Q25 |
| D33 | A stock movement has one of six kinds (receipt, issue, disposal, loss, adjustment in, adjustment out) and a positive quantity; the sign comes from the kind. The quantity of a lot on a date is the sum of its movements dated on or before that date. The end-of-day balance of a lot is never negative: every write and every import row is checked, backdated ones included. No movement is dated after today. An adjustment needs a note. The quantity itself is never stored | O02, T11.6, Q29 |
| D34 | A lot is valid on a date when its expiry date is empty or not before that date (`expires_on` ≥ *d*). Lot status order: not received, empty, expired, expiring, valid. An empty lot never raises an alert. The expiry date is required for the antidote and decontaminant categories. The status is shown as text plus icon plus colour (D23) | O03, T11.4, Q28 |
| D35 | The minimum stock is stored per item type, separate from the indicator targets. A type is below its minimum when the valid quantity is strictly less than the minimum; a type with no minimum is never below it. `LOW_STOCK` is critical. A target on `STOCK_VALID_QTY` stays possible | O04, P12, T11.4, Q26 |
| D36 | Stock is its own indicator module, `Module.STOCK`. Its dimension keys are `category` and `item`. The category of a type cannot change once a lot uses it. A value is produced only for a type that is in use on the date or has a minimum | O03, O04, T11.7 |
| D37 | The anonymised report omits per-type stock quantities, values and prices, and the stock chart; it keeps counts (lots expired, lots expiring, types below minimum, stock alerts). Those cells are marked `internal_only` in the report model. The internal report lists the expired and expiring lots with stock | T11.15, Q27, A11 |
| D38 | One stock panel is shared by the "Estoque (lotes)" tab and by the antidotes page. Stock is management data only: types, lots, quantities, expiry dates, prices and movements; there are no dose, indication or protocol fields, and lot codes and notes carry a hint that no clinical information belongs there (D19) | O01, O03, T11.9, T11.10, T11.11 |
| D39 | Owner, 2026-11-24 ("o app está concluído e aprovado, remova os avisos"). From 1.2.0 there is no preliminary-version notice (UI banner, PDF, About, first-run notes, release body, help), no warning against entering real data until Q19, Q4, Q11 and Q13 are answered, and no placeholder badge or Confirm action. Generic defaults become confirmed code defaults (placeholder flags cleared). The local-only values P03, P10, D18 and P12 keep empty code defaults, are set per installation in Settings, and are not shown as placeholders. P07 is withdrawn. Q15, Q19, Q4, Q11 and Q13 are answered; only their status is recorded, never the answer content. Kept: D25 (DEMO banner), the data-protection notice without the gate sentence, F05 and K04 (no real data in the repository). Supersedes I06 and the notice and badge requirements of T1.5, T1.9, T6.1, T7.5, T8.6, T9.3, T9.4, T10.2, T10.5 and T11.13; done tasks are not rewritten. It is not a claim of institutional homologation (R30). Answering Q11 and Q13 does not trigger X1, X5, X6 or X13 | I06, P07, K24, K25, T12.3–T12.14 |

New A, P and D identifiers are assigned at merge time (next free number). Design decisions go to this register and assumptions or placeholders to §3.5 (§10.1).

### 3.5 Assumptions and placeholder defaults
None of the items below is stated in the appendix. Each is an assumption (A) or a placeholder default (P) that needs confirmation, and each is linked to an open question (§12) except P06, which is purely technical.

Every placeholder is declared in `domain/config.py` with a `placeholder` flag. That code-level flag is the release-level truth. Placeholders are of two kinds:
- *Local-only values:* the indicator targets (P03), the institution and unit names (D18) and the internal report's handling notice. They never get a code default, their flag is never cleared in code, and they are confirmed per installation in Settings only.
- *Generic defaults:* all the others (warning windows, snapshot cadence, passphrase length, backup counts, pro-rating, reminder days, small-count threshold, disclaimer wording). The code flag may be cleared, and the default changed, only by a commit made when the project owner judges that the value is not sensitive. The commit and the changelog record only the status, never the committee's reasoning (§12).

Settings shows a "placeholder — to be confirmed" badge until the operator confirms or changes the value; this per-database "confirmed" state only hides the badge on that installation and never changes the flag in code. Release notes and the changelog list the code-level flags.

A-items without a setting (A01, A03, A12, A13, A14, A15, A16) are assumptions, not placeholders. They carry no flag and appear in the changelog only as open questions.

| ID | Assumption or placeholder | Default in v1 | Configurable in | Q |
|---|---|---|---|---|
| A01 | "Leitos e baias disponíveis" (L76) means units in service whose current status is operational, not how many are free at a given moment | — | — | Q5 |
| A02 | PPE levels A, B, C are counted independently: a level-A qualification does not also count as B or C | hierarchy off | Settings → Personnel | Q2 |
| A03 | **PPE qualification rule (stated once; §5.4, §5.5, T2.2 and T6.2 refer to it).** For a person, a level and a date *d*, the PPE qualification that counts is the one with the latest `valid_until` among those with `issued_on` ≤ *d* (ties: later `issued_on`, then higher id). It is valid when `valid_until` ≥ *d*. A qualification issued after *d* therefore never hides the one that was valid on *d*. "Necessidade de reciclagem" (L74) means that counting qualification has expired or expires within the warning window, and `no_renewal_from` (D24) is not set or is later than *d* | — | — | Q2 |
| A04 | Each PPE qualification records an explicit valid-until date. An optional validity period per level only pre-fills the form | period not set | Settings → Personnel | Q2 |
| A05 | Asset statuses are operational, degraded and out of service. Only "operational" counts as available | degraded counts as unavailable | Settings → Infrastructure | Q5 |
| A06 | Maintenance due date = the `next_due_on` of the latest maintenance on or before the as-of date that records one; records without it (typically corrective or inspection) never reset the schedule. Without any recorded next-due date: an effective interval of 0 means "no scheduled maintenance" (no due date and no `MAINT_SCHEDULE_UNKNOWN` alert); otherwise the latest preventive `performed_on` (or `in_service_from`) plus the interval; with no interval, "schedule unknown". A recorded `next_due_on` always wins over an interval of 0 | interval not set | per asset type, per asset | Q6 |
| A07 | Evaluation results (L78) are values of user-defined metrics (name, unit, scale) per edition | no metrics seeded | Settings → Exercises | Q7 |
| A08 | Budget = an allocated amount per fiscal year (taken as the calendar year), source and currency, plus dated execution rows (`budget_execution`); executed = the sum of the rows dated on or before the as-of date | currency BRL | Settings → Budget | Q8 |
| A09 | "Capacitação" (L74) = the dated completion of a course from an editable course list | empty list | Settings → Personnel | Q3 |
| A10 | Degrees (L74) carry a status: completed or in progress | completed | per record | Q3 |
| A11 | The anonymised report (L69) shows only aggregate counts. Personnel-derived counts from 0 to threshold − 1 (zeros included) are shown as "< threshold"; any total or sibling cell from which a suppressed value could be recomputed is suppressed too | threshold 5 | Settings → Reports | Q10 |
| A12 | One operator, or several people taking turns on one machine; nobody edits at the same time. Taking turns works only with one shared Windows account, or with `--data-dir` pointing to a local folder restricted to the committee; with separate Windows accounts each person gets a separate database | — | — | Q12 |
| A13 | The exercise register holds CBRAMED and EXBRAMED editions (L78), plus an "other" kind | — | — | Q7 |
| A14 | A person or an asset has one active or in-service interval; someone who returns, or equipment that comes back, is entered as a new record | — | — | Q4, Q5 |
| A15 | Stock quantities are whole units of issue per item type; there is no unit column and no fractional quantity (O01, D33) | — | — | Q26 |
| A16 | Each of the 17 built-in stock item types has a fixed category (antidote, decontaminant, detector, PPE or other); the category of a type cannot change once it has lots (D36) | — | — | Q25 |
| P01 | Warning window before a PPE qualification expires | 90 days | Settings | Q2 |
| P02 | Warning window before maintenance is due | 30 days | Settings | Q6 |
| P03 | Indicator targets (warning and critical values) | none, so the status shows "no target" | Settings → Targets | Q1 |
| P04 | Automatic snapshots (D21) | monthly (first start in a month) and on every report | Settings | Q9 |
| P05 | Minimum backup passphrase length. Settings cannot go below the hard floor of 12 characters | 12 characters | Settings | Q11 |
| P06 | Number of automatic daily local backups kept. Settings cannot go below the hard floor of 2 copies | 7 | Settings | — (technical) |
| P07 | Disclaimer wording (I06) — withdrawn by D39 (T12.4, T12.13) | "Preliminary version — indicators not institutionally validated." | translations | Q15 |
| P08 | Pro-rating of the `BUD_EXEC_RATE` target over the fiscal year (the target is multiplied by the elapsed fraction of the year, linear) | linear, on | Settings → Budget | Q8 |
| P09 | Reminder banner when the last encrypted backup is older than this many days | 30 days | Settings → Backup | Q11 |
| P10 | Handling notice printed on the internal report (local-only value: no code default, flag never cleared in code) | empty | Settings → Reports | Q10 |
| P11 | Warning window before a stock lot expires (D34): a lot is "expiring" when its expiry date is on or before the as-of date plus this many days | 90 days | Settings → Alerts | Q28 |
| P12 | Minimum stock per item type (D35; local-only value: no code default, no config field, flag never cleared in code; stored in `stock_item_type`) | empty (no minimum) | Settings → Infrastructure | Q26 |

---

## 4. Architecture and stack decisions

### 4.1 Layers (D11)
```
ui/        PySide6 widgets, table models, dialogs, translations (Qt)
  │ calls
services/  use cases: add a PPE qualification, evaluate indicators, back up... (no Qt)
  │ uses                          │ uses
domain/    pure rules (no Qt, no I/O)    storage/  sqlite3, migrations, backup, CSV (no Qt)
reports/   model.py + anonymise.py (no Qt)  ──►  pdf.py (Qt rendering only)
```
Rules, enforced by the guard test in T0.4:
- `domain/` imports nothing from `storage/`, `services/` or PySide6.
- `services/`, `storage/`, `reports/model.py` and `reports/anonymise.py` import no PySide6.
- `ui/` never touches `sqlite3` directly; it goes through `services/`.

Domain functions return codes and numbers, never translated text; the UI turns codes into words (§6). As a result, most acceptance checks are plain pytest runs that need no widgets. These layering rules are a design decision (D11); the appendix does not prescribe an architecture.

### 4.2 Stack (D12 and the owner's working assumptions)
Every working assumption — PySide6, SQLite, PyInstaller, uv, pytest, ruff — is **confirmed**; none is replaced. The additions are marked "added", each with its reason. Every licence was checked against GPL-3.0-or-later.

| Concern | Choice | Licence | Verdict | Reason |
|---|---|---|---|---|
| Runtime | CPython 3.12 x64, pinned in `.python-version`, `requires-python = ">=3.12"` | PSF-2.0 (GPL-compatible) | chosen (D12) | Wheels exist for PySide6, PyInstaller and `cryptography`. Security support runs to Oct 2028, whereas 3.10 reaches end of life in Oct 2026. 3.12 is already in its security-only phase, so python.org no longer publishes Windows installers for it; the interpreter comes from uv's managed builds. 3.13 and 3.14 are evaluated at each yearly review. |
| UI | PySide6 (Qt 6 Widgets), `>=6.8,<6.13` while Windows 10 is a target | PySide6 and shiboken6 declare `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; LGPL-3.0-only is chosen for the bindings and core Qt modules. GPL-3.0-only for the Qt Charts module | confirmed | Qt 6.12 is the last Qt release that supports Windows 10, hence the upper bound (K17). The official Qt binding. Native Windows look; translations, PDF output and charts are built in. LGPL-3.0 and GPL-3.0 are both compatible with GPL-3.0-or-later. Tkinter was rejected: no built-in charts, PDF or translation tooling. PyQt6 (GPL-3.0) would also be compatible, but it is not the official binding and has no LGPL option. |
| Storage | SQLite through the standard-library `sqlite3` | public domain | confirmed | One file, no administration, transactional, online backup API; nothing extra to bundle. |
| Packaging | PyInstaller `>=6.10`, one-folder (D01) | GPL-2.0-or-later with a bootloader exception | confirmed | Mature PySide6 support; the exception allows bundling code under any licence. Nuitka (Apache-2.0) needs a C compiler and long builds; cx_Freeze is less used with PySide6; Briefcase targets installers. |
| Environment | uv, with `uv.lock` committed | MIT / Apache-2.0 | confirmed | Locked dependencies with hashes; fetches the right Python version; fast in CI. Development tool only, not shipped. |
| Tests | pytest + **pytest-qt** + **pytest-cov** | MIT (all three) | pytest confirmed; plugins added | pytest-qt drives widgets in Qt's offscreen platform, so UI tests need no display; pytest-cov enforces coverage in CI. Test tools only, not shipped. |
| Lint / format | ruff (`check` and `format`) | MIT | confirmed | One fast tool for both lint and formatting; called from a pytest test so the single allowed check command covers it (T0.2). Not shipped. |
| Type checking | **mypy**, strict on `domain`, `services`, `storage` and the Qt-free parts of `reports` | MIT | added | Catches mistakes early in domain and storage code written by agents. Not shipped. |
| Cryptography | **`cryptography`** (Fernet) + the standard library's `hashlib.scrypt` | Apache-2.0 OR BSD-3-Clause | added (runtime) | Encrypted backups (D03, D04). The standard library has no authenticated encryption. Apache-2.0 is compatible with GPL-3.0. Its own dependencies (`cffi` MIT, `pycparser` BSD-3-Clause) are compatible too. |
| Reading PDFs in tests | **pypdf** | BSD-3-Clause | added (tests only) | Extracts text from generated reports so tests can check content; extraction from Qt-generated PDFs is unverified, so T8.6 starts with a spike (K18). Avoids the AGPL-licensed PyMuPDF. |
| Country names | CLDR data extracted with **Babel** at development time (`scripts/gen_countries.py`) | Unicode-3.0 for the data; BSD-3-Clause for Babel | added (tool only) | Country names in three languages for the exercises module (D20), with no runtime dependency. Only the generated JSON and the CLDR notice are shipped. |
| Charts | Qt Charts, through `ui/shell/charts.py` (D08) | GPL-3.0 | chosen | Already inside the PySide6 wheel. Deprecated since Qt 6.10; see the tradeoff in §4.3 (D08, K09). |
| Reports | Qt's own text-document and PDF-writer classes (D09) | as PySide6 | chosen | No extra dependency; see §4.3. |

The runtime dependencies are only PySide6 and `cryptography`, plus `cryptography`'s own dependencies. A dependency-licence allow-list test (T9.2) fails the build if anything outside MIT, MIT-0 (declared by `cffi`, a dependency of `cryptography`), BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0, LGPL-3.0 or GPL-3.0 enters the runtime environment. The test evaluates SPDX expressions: an `OR` expression passes when at least one alternative is allowed, and the chosen alternative is recorded in the licence index. For PySide6 and shiboken6 (`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`) the index records LGPL-3.0-only for Qt core and the bindings, and GPL-3.0-only for Qt Charts as a separate entry.

The project's source code is GPL-3.0-or-later. Because the binary bundle includes the GPL-3.0 Qt Charts library, the built executable as a whole is distributed under GPL-3.0. The Qt DLLs stay replaceable in the one-folder layout, and the full source and build scripts are public, which meets the LGPL's relinking expectation for the LGPL parts. The plan's reading of GPLv3 §6 and the LGPL is that linking the project's own source tag is not enough: each release body also links the exact Qt and PySide6 source release that matches the bundled version and carries a written offer for that source (T9.3), and `licenses\` includes the same pointer (T9.2).

### 4.3 Key decisions and tradeoffs

**D01 — Packaging: PyInstaller one-folder, distributed as `cbrn-readiness-dashboard-<version>-win-x64.zip`.**
- *Decision:* the user extracts the zip to any folder where they are allowed to run programs and starts `cbrn-dashboard.exe`. Build flags: `--onedir --windowed --noupx`. UPX compression is off because it raises antivirus scores. There is no installer and no need for admin rights (F01).
- *Tradeoff — start-up time:* a one-file build unpacks tens of megabytes of Python and Qt into `%TEMP%` on every start, which takes seconds. The one-folder build loads in place.
- *Tradeoff — antivirus:* unsigned self-extracting executables are a classic heuristic trigger for antivirus engines. A plain executable next to its DLLs is flagged less often.
- *Tradeoff — locked-down networks:* one-file fails wherever AppLocker, software-restriction or similar policies block running code from `%TEMP%`. One-folder only needs the extraction folder to be an allowed location.
- *Also:* one-folder keeps the Qt DLLs as separate, replaceable files, as the LGPL expects. The cost is handing over a folder instead of a single file.
- The same build script can produce a one-file variant (deferred item X5) if Q13 makes a single file mandatory.

**D02 — Where the data lives and what happens on a read-only location.**
- *Decision — resolution order:*
  1. the `--data-dir` option;
  2. the `CBRN_DASHBOARD_DATA_DIR` environment variable;
  3. portable mode: a `portable.ini` file next to the executable puts the data in `.\data\` beside it;
  4. a pointer file, `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`, written by T7.5 when the user chooses another folder;
  5. the default, `%LOCALAPPDATA%\cbrn-readiness-dashboard\`.

  The chosen folder holds the database `cbrn-dashboard.sqlite3` (called "the database" and `<db>` elsewhere in this plan), `prefs.json`, `backups\`, `logs\`, `tmp\` and the separate `demo\` database.
- *Read-only location:* at start-up the app tests writability by creating and deleting a temporary file, and also tests that the database file itself is writable, not only its folder. The read-only flag on a Windows folder does not stop file creation, so the flag alone proves nothing.
  - If the location is not writable and a database exists, the app opens it read-only (an SQLite read-only URI built with `Path.as_uri()`), shows a banner and disables every edit action.
  - In read-only mode, logs and preferences stay in memory, and the daily backup, snapshots, the `tmp\` clean-up and the instance lock (T1.9) are skipped. "Back up" still works: it reads through an in-memory copy (the backup API or `serialize()`) and writes nothing to the data folder. A database with a hot journal cannot be opened read-only; the app shows a translated explanation instead.
  - If it is not writable and no database exists, the app explains the problem in the current language and lets the user choose another folder.
  - It never writes anywhere else silently. The choice is remembered in the pointer file in the profile (step 4), not in the read-only folder. Because portable mode ranks above the pointer file, the pointer is honoured in portable mode only when the portable folder is unusable (not writable and holding no database).
  - Preferences that cannot be saved because the data folder is read-only are kept for the session only (§6).
- *Warnings:* the app warns when the folder is on a network path (UNC or a mapped network drive), because SQLite locking is unreliable over file shares. It also warns when the folder is inside a OneDrive-synced folder, because the data would leave the machine. OneDrive is detected from the environment-variable prefixes, from the OneDrive account mount points read (read-only) from the registry, and from the cloud-placeholder file attributes of the folder; the registry reader is injectable for tests.
- *Several people on one machine (A12):* taking turns works only with one shared Windows account, or with `--data-dir` pointing to a local folder restricted to the committee. With separate Windows accounts each person gets a separate database. The first-run notice says so.
- *Tradeoff:* the profile location is writable without admin rights, protected per Windows user, survives upgrades (a new version's folder simply replaces the old one) and is not covered by OneDrive's known-folder redirection. The cost is that the data does not travel with the program — for sensitive data that is a feature. Portable mode exists for when the data must travel, with the stated risk that copying the folder copies the data.

**D03 — Protection of data at rest.**
- *Decision for v1:*
  - data minimisation (D17);
  - the per-user profile location (D02);
  - a documented requirement, repeated in a first-run notice, that the workstation use full-disk encryption (for example BitLocker) as institutional policy requires;
  - passphrase-encrypted backups (D04);
  - `PRAGMA secure_delete=ON`;
  - anonymised external reports (A11).

  The app does **not** encrypt the live database itself in v1.
- *None:* costs nothing, but is not acceptable for staff data on a computer that can be lost (R33).
- *OS-level (full-disk encryption plus profile permissions):* no code, packaging or licence cost, and it covers the main threat, a lost or stolen device. It does not protect against other administrators or malware on a running machine, and the app cannot verify it without admin rights.
- *Encrypted database:* either SQLCipher through third-party Windows wheels, or an app-level encrypted file holding an in-memory SQLite database. It protects copies of the file. The costs:
  - a native dependency whose wheels lag behind new Python releases, or custom persistence code that can lose data in a crash;
  - plus passphrase management with no recovery if the passphrase is lost.

  SQLCipher Community Edition has a BSD-style licence, compatible with GPL-3.0, so licensing is not the obstacle; packaging and key management are.
- *Gate:* if Q11 says the database itself must be encrypted, this becomes deferred item X1. Every connection goes through one `open_database()` function (D06), so the change stays in one place.

**D04 — Backup, export and import.**
- *Automatic local backups:* plain copies in `<data>\backups\`, made with SQLite's online backup API so they are consistent even while the app is open. One is made before every schema migration and one at the first start of each day. The pools are separate:
  - pre-migration backups have their own pool (the last 3 are kept) and are never rotated out by daily backups;
  - the daily pool keeps the newest 7 (P06, never fewer than 2);
  - `.before-restore-*` safety copies are rotated too (the last 2 are kept);
  - each new copy passes `PRAGMA quick_check` before any older copy is deleted, and the newest copy that passed is never deleted.

  The demo database has its own `demo\backups\`.
- *Reminder:* a banner appears when the last encrypted backup is older than P09 days (default 30).
- *Manual encrypted backup:* a `.cbrnbak` file written wherever the user chooses, for example removable media.
  - *Key derivation:* scrypt with n = 2^17, r = 8, p = 1 and an explicit `maxmem`. The reader accepts only parameter sets from a short allow-list, so a crafted header cannot force a long derivation. 64 bytes are derived: 32 for the Fernet key and 32 for an HMAC-SHA256 over the header.
  - *Layout:* a header (magic `CBRNBAK1`, format version, scrypt parameters, salt, app version, schema version), the header HMAC, a Fernet token holding the database bytes, and at the end an unkeyed SHA-256 of everything before it.
  - *Check order and errors:* bad magic or a wrong trailing checksum → `CorruptBackupError`; unknown format version → `BackupTooNewError`; scrypt parameters outside the allow-list → `CorruptBackupError`, before any key derivation; header HMAC mismatch → `WrongPassphraseError`; a Fernet failure after that → `CorruptBackupError`.
  - *Schema version:* the one that drives migration is the restored database's own `user_version`; the copy in the header is informational.
  - *Passphrase:* entered twice, never stored. It must meet the minimum length (P05, never below 12) and a small strength rule: not on a short blocklist, and a minimum number of distinct characters.
- *Restore:*
  1. Decrypt into `<data>\tmp\`.
  2. Run `PRAGMA integrity_check`.
  3. Check that the backup's `app_meta.is_demo` equals the open database's; if not, refuse with an error code.
  4. Check that the schema version is not newer than the app, and migrate the copy if it is older (with the pre-migration backup turned off, so no plaintext leaves `tmp\`).
  5. Close every other connection and assert that no `-journal` file exists.
  6. Keep a safety copy of the current database, made by copying, before anything is written to it.
  7. Copy the validated temporary database into the live one with SQLite's backup API. There is no rename and no file swap, so this is not described as atomic.

  Any failure leaves the current database untouched; the tests exercise the failure cases against this mechanism (T7.3).
- *Export:* CSV per module in a locale-independent format (UTF-8 with BOM, `;` separator, ISO dates, `.` decimal point, stable English column codes), and PDF reports (D09). A text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with `'` on export, so spreadsheets do not run it as a formula; import strips that prefix. In demo mode every file name starts with `DEMO-`.
- *Import:* CSV templates for the retroactive 2022–2025 data (R29). Each file is validated and imported in a single transaction; a dry run shows the result first; errors are reported per row; duplicates by natural key are rejected; every import is recorded in `change_log`. A file that is not valid UTF-8 is rejected with an explicit error code that tells the user to save it as UTF-8. Codes are always read as text, so leading zeros are kept.
- *Tradeoff:* unlike a password-protected zip, an encrypted backup can only be opened by the app, or by a short documented Python recipe that uses the same `cryptography` library. Fernet is a reviewed scheme, whereas zip AES variants are inconsistently implemented. Facts about it: Fernet holds the whole file in memory (fine at this size) and exposes the creation time of the token. OWASP and the `cryptography` documentation prefer Argon2id for passwords; Q11 may require it, and a switch is deferred item X13. A single restore code path always validates and migrates.

**D05 — A single local operator: no accounts or roles in v1, but an append-only change log.**
- *Decision:* the Windows session is the access boundary. The operator may enter an optional label (a name or a role) in Settings; it is stamped on `change_log` rows and on reports.
- *Change log:* every insert, update, delete, import and restore writes a `change_log` row for each affected row in the same transaction, with before and after values as JSON; a delete also writes one `delete` row per cascaded child, and `entity_key` holds the natural key for tables without an integer id. For the personal free-text columns (§5.1) only the fact that the column changed is recorded, not its old or new value. Database triggers forbid updating or deleting `change_log` rows.
- *Tradeoff — accounts and roles:* app-level logins on top of an unencrypted SQLite file can be bypassed by opening the file in any SQLite tool. They would add friction and a password to forget, without real protection. Real multi-user use (A12, Q12) would need a shared database, which SQLite on network shares does not support safely, so it is a v2 architecture question (deferred item X2).
- *Tradeoff — audit trail:* the change log costs little when it is built into the repository layer from the start, and is expensive to add later. It supports audits and inspections (R35) and the reconstruction of history. It is not tamper-proof against someone with access to the file, and it keeps old values of the other columns; the "pseudonymise person" action (T2.3) removes the identifier and free text of a person while keeping history. Retention is Q12, and a redaction tool is deferred item X8.

**D06 — Data-access layer and migrations: standard-library `sqlite3` with plain SQL, and numbered SQL migration files.**
- *Decision — repositories:* one per module in `storage/`, running explicit SQL against `STRICT` tables with foreign keys on, inside explicit transactions (`isolation_level=None` with explicit `BEGIN`/`COMMIT`).
- *Connection settings:* rollback journal (`journal_mode=DELETE`, which leaves no extra WAL files beside the database), `synchronous=FULL` and `secure_delete=ON`. All connections, read-only ones included, are opened by `open_database()`.
- *Migrations:*
  - Numbered `.sql` files in `storage/migrations/`, loaded with `importlib.resources` so they also work inside the frozen executable.
  - Each runs inside a transaction (SQLite supports transactional schema changes), and the schema version is tracked in `PRAGMA user_version`.
  - The runner must **not** use `Connection.executescript()`, because Python's `sqlite3` commits a pending transaction first. It splits each file into statements (for example with `sqlite3.complete_statement`) and runs them with `execute()` inside one explicit `BEGIN IMMEDIATE … COMMIT`, setting `user_version` in the same transaction and issuing `ROLLBACK` on any error.
  - `PRAGMA foreign_keys` is a no-op inside a transaction. A table-rebuild migration is therefore flagged in its header comment; for it the runner turns foreign keys off before `BEGIN`, runs `PRAGMA foreign_key_check` before `COMMIT`, and turns them back on afterwards.
  - The app makes a backup before migrating and refuses to open a database newer than itself.
  - A migration is never edited after it has shipped in a tagged release.
  - Numbers 0002–0007 are reserved per module only until v0.1.0, so parallel work does not collide. Every later migration is numbered max+1 at merge time. The runner refuses to run when the available files are not contiguous from 0001 (including when `user_version` is higher than the number of a missing file); T1.3 tests this. Developer and demo databases are disposable before v0.1.0.
- *Tradeoff:* this means more hand-written SQL than SQLAlchemy plus Alembic (both MIT) would need. In return:
  - there are no extra runtime dependencies;
  - there is no ORM behaviour for coding agents to misuse;
  - there is nothing special to bundle with PyInstaller (Alembic's script directory would be);
  - the SQL is transparent for audit.

  The model is about 20 tables of small volume, well within what explicit SQL handles comfortably.

**D07 — Internationalisation mechanism: Qt Linguist `.ts` source catalogues compiled to `.qm`, with English source strings and one catalogue per area.** Full detail in §6.
- *Versus gettext:* both are mature.
  - Qt's system plugs straight into widgets and live language switching (the `LanguageChange` event), handles plural forms, and reuses Qt's own translations for standard dialogs. Its tools (`pyside6-lupdate`, `pyside6-lrelease`, Linguist) ship inside the PySide6 wheel, so it adds no dependency.
  - gettext would need Babel for extraction and compilation, and would still need Qt's own catalogues for the texts of standard dialogs.
- *Versus JSON catalogues:* they have no plural rules, no extraction tool and no translator editor, so all of that would have to be built.
- *Cost:* the domain and services layers must stay free of translations and return codes. D11 requires that anyway.
- *One catalogue per area:* lets agents working in parallel avoid merge conflicts in module catalogues. The `shell` catalogue is shared by several tasks and is one of the hot spots of §10.2.

**D08 — Charts: Qt Charts, used only through the adapter `ui/shell/charts.py`.**
- *Qt Charts:*
  - Licence: GPL-3.0, compatible with this project.
  - Bundle size: it is already inside the PySide6 wheel and adds only a few Qt DLLs.
  - It looks native, renders offscreen, and can draw into the same painter that writes PDFs (D09).
- *pyqtgraph:* MIT, but it needs numpy, which adds tens of megabytes, and it has a scientific rather than management look.
- *matplotlib:* a permissive PSF-style licence, but it needs numpy, Pillow and several other packages. It gives the largest bundle and the slowest start-up, although its static export is the best.
- *Risk:* Qt Charts is deprecated since Qt 6.10 and Qt is steering new charting work towards Qt Graphs. Qt Graphs is not a local adapter swap: its 2D graphs need Qt Quick/QML, which this plan excludes from the bundle, and it is also GPL-3.0. The adapter remains the single touch point for a later backend change (deferred item X9, risk K09). If Qt Charts emits a deprecation warning at runtime, it is added to `qt_log_ignore` by exact text (T6.4).
- Charts are secondary: every number shown in a chart also appears in a tile or a table, so a chart problem never hides data.

**D09 — Reports and export: PDF and CSV in v1; XLSX deferred.**
- *Decision:* PDF reports are built with Qt's own text-document and PDF-writer classes, with no extra dependency. There are two variants:
  - the internal report, for the committee, DIRSA and the Air Force Command (R11, R12);
  - the aggregated, anonymised report (R13, A11), for internal use; any external release is a decision of the chain of command.

  Both carry the preliminary-version notice (I06, P07). CSV serves data exchange and the retroactive import (R29, D04).
- The appendix calls for reports and accountability (L65, L69, L95) but does not mention spreadsheets. XLSX is therefore deferred item X3, pending Q10. `openpyxl` (MIT) would be compatible if it is needed.
- *Pagination:* `QTextDocument.print()` has no per-page footer, so T8.6 paginates manually with `QPainter` and draws the footer notice and page number on every page.
- *Tradeoff:* Qt's subset of HTML gives less layout control than ReportLab (BSD) or WeasyPrint. But it adds no dependency, uses the same fonts and chart rendering as the UI, and is enough for tables, key figures and embedded charts.

**D10 — CI on GitHub Actions; an unsigned executable.**
- *On every push and pull request:*
  - A job on a **pinned** Windows runner image (not `windows-latest`) runs `uv sync --locked --all-groups`, then the default pytest suite with Qt's offscreen platform. That suite includes ruff, mypy, the guard tests and the translation-completeness tests. Coverage is gated in CI.
  - A second job builds the one-folder executable with PyInstaller, runs the built executable's `--self-test`, and uploads the zipped folder as a short-lived workflow artefact.
- *On a version tag:* a release workflow rebuilds and retests, then produces:
  - the zip;
  - a `SHA256SUMS.txt` file;
  - a build-provenance attestation, made with GitHub's attestation action and verifiable with `gh attestation verify`.

  It then creates a **draft** GitHub release, marked pre-release while the version is below 1.0.0. A person publishes it after a manual smoke test.
- *Release jobs (QA findings P9-01, P9-03):* the release workflow builds once. A read-only `build` job runs the tests and the packaging tests, which build the bundle into `dist/`, then zips that tested bundle and uploads it as a workflow artefact; a separate `release` job, the only one with write permissions, downloads that artefact, attests the zip and creates the draft. There is no second build (T9.3).
- *Supply chain:* every action is pinned to a full commit SHA, workflow permissions are least-privilege, and Dependabot proposes updates.
- *Unsigned executable — consequences:* Windows SmartScreen shows "Windows protected your PC" the first time a downloaded copy runs. Smart App Control, or AppLocker/WDAC policies, may block it outright.
- *What the published checks prove:* `SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity. The attestation proves where and how the build ran, not that the program is safe.
- *Locked-down machines:*
  - When AppLocker is enforced, its default rules allow only Windows, Program Files and administrators, so the extraction folder must be a path that IT allows.
  - Hash rules are per file and per release. With DLL rules or WDAC they must cover the `.pyd` and DLL files too, so each release also publishes a per-file SHA-256 manifest of the bundle (T9.3).
  - Smart App Control has no per-file bypass.
  - Mark-of-the-Web is inherited by files extracted with Windows' own extractor unless the zip is unblocked first; other extractors behave differently.
- *Mitigations:* one-folder layout, no UPX, published checksums, per-file manifest and attestation, and allow-listing by file hash by the institution's IT team. The install guides in three languages (T10.3) arrive in v1.0; the MVP mitigation is the first-run notes in the zip (T9.4).
- *Tradeoff:* code signing removes most of this friction. But it needs a legal identity, a paid certificate or acceptance into an open-source signing programme, and careful secret handling in CI. That is not justified before the committee confirms how the app will be deployed (Q13); it is deferred item X6.

### 4.4 Repository layout
```
cbrn-readiness-dashboard/
├─ pyproject.toml  uv.lock  .python-version  README.md  PLAN.md  CHANGELOG.md  CONTRIBUTING.md  LICENSE  .gitignore
├─ .github/
│  ├─ workflows/ci.yml  workflows/release.yml
│  ├─ pull_request_template.md  ISSUE_TEMPLATE/bug_report.md
│  └─ dependabot.yml
├─ packaging/      portable.ini.example  README-first-run.{pt-BR,en-US,es-ES}.txt
├─ scripts/        i18n.py  build_exe.py  collect_licenses.py  make_release_zip.py  gen_countries.py
├─ docs/           architecture.md  data-protection.md  indicators.md  import-templates.md
│                  install.{pt-BR,en-US,es-ES}.md  manual-test-script.pt-BR.md  smoke-test.pt-BR.md
├─ src/cbrn_dashboard/
│  ├─ __init__.py (version)  __main__.py  app.py  cli.py  clock.py  paths.py  prefs.py
│  │  logging_setup.py  selftest.py   (app.py: start-up sequence and start-up hooks)
│  ├─ domain/      config.py  dates.py  indicators.py  registry.py
│  │               personnel.py  infrastructure.py  exercises.py  budget.py  alerts.py
│  │               stock.py   (v1.1.0, Phase 11)
│  ├─ storage/     db.py  migrate.py  repository.py  settings_repo.py  targets_repo.py
│  │               personnel_repo.py  infrastructure_repo.py  exercises_repo.py  budget_repo.py
│  │               stock_repo.py   (v1.1.0)
│  │               backup.py  crypto_backup.py  csv_io.py
│  │               migrations/  README.md (number reservations until v0.1.0)  0001_core.sql … 0009_stock.sql
│  ├─ services/    personnel.py  infrastructure.py  exercises.py  budget.py  stock.py (v1.1.0)
│  │               indicators.py  alerts.py  dashboard.py  snapshots.py  validation_export.py
│  │               backup.py  restore.py  export.py  importer.py
│  ├─ reports/     model.py  anonymise.py  message_keys.py  pdf.py
│  ├─ ui/
│  │  ├─ shell/    main_window.py  i18n.py  formatting.py  charts.py  prompts.py  registry.py (pages, settings sections, dialogs)
│  │  │            context.py  banners.py  first_run.py  about.py  help.py  folders.py
│  │  └─ personnel/  infrastructure/  exercises/  budget/  dashboard/  alerts/  settings/  backup/  reports/
│  │     stock/  (v1.1.0: the shared stock panel, dialogs, models, labels and the types section of Settings)
│  │     antidotes/  (v1.1.0: the "Antídotos e descontaminantes" page)
│  │               (each: page.py, dialogs.py, models.py, labels.py as needed)
│  ├─ i18n/        __init__.py (area → source-folder map, language list)
│  │               <area>_pt_BR.ts  <area>_en_US.ts  <area>_es_ES.ts   (.qm generated, not committed)
│  ├─ help/        pt_BR.md  en_US.md  es_ES.md
│  ├─ resources/   app.ico  countries.json  THIRD_PARTY_DATA.md
│  └─ demo/        __init__.py  personnel.py  infrastructure.py  exercises.py  budget.py  stock.py (v1.1.0)
└─ tests/
   ├─ conftest.py
   ├─ meta/  domain/  storage/  services/  ui/  i18n/  reports/  demo/  scripts/  packaging/
   └─ fixtures/    (fictitious data only, e.g. csv/)
```
Notes on the layout:
- The existing `.gitignore` already ignores `build/`, `dist/`, `lib/`, `var/`, `*.spec`, `*.mo` and `*.pot`. So no source folder may use those names, there is no committed PyInstaller spec file (`scripts/build_exe.py` passes every option), and gettext is not used (D07). Rather than a list of forbidden names, the hygiene test (T0.3) asserts that no file under `src`, `tests`, `docs`, `packaging` or `scripts` is ignored.
- The storage package is called `storage`, not `data`, so a root-anchored `/data/` ignore rule can protect a portable data folder created inside a working copy.
- T0.3 adds ignore rules for database, journal, backup, log, scratch and compiled-catalogue files.

---

## 5. Data model

### 5.1 Conventions
- `STRICT` tables, which need SQLite 3.37 or later; the version is checked at start-up (T1.2). Integer primary keys.
- Dates are text `YYYY-MM-DD`. Timestamps are UTC ISO 8601 text ending in `Z`. Booleans are `0`/`1`.
- Money is a whole number of minor units (cents) plus an ISO 4217 currency code (D15).
- Foreign keys are on. Child rows are deleted with their parent (`ON DELETE CASCADE`). List entries that other rows use cannot be deleted (`ON DELETE RESTRICT`); they are deactivated instead. Built-in list entries (D16) cannot be deleted at all.
- User-defined list entries (asset types, courses, evaluation metrics, funding sources) have three label columns, `label_pt_br`, `label_en_us` and `label_es_es` (§6). `label_pt_br` is required for non-built-in rows, enforced in the service; the other two may be empty and fall back as §6 describes (D16). Built-in rows leave all three empty.
- Natural keys used by the CSV import (T8.4) are backed by UNIQUE constraints or unique indexes, so duplicates are rejected by the database too.
- Every write goes through the repository helpers, which record one `change_log` row per affected row in the same transaction (D05). A delete also logs the cascaded children: the helper finds them through `PRAGMA foreign_key_list` before deleting and writes one `delete` row for each. `change_log.entity_key` holds the natural key as JSON for tables without an integer id (`exercise_country`, `evaluation_result`, `readiness_snapshot_value`, `indicator_target`, `setting`).
- Personal free-text columns — `staff_member.identifier`, `staff_member.label`, `ppe_certification.reference` and `academic_degree.field` — are never copied into `change_log`: for them it records only that the column changed, not the old or new value. This keeps the pseudonymisation action (T2.3) effective. The free-text fields that remain (`label`, `reference`, `field`) show a hint in the UI: no names, health or contact data; the identifier field hints "a local code, not a service number" (D17). The free-text `notes` columns of `staff_member`, `ppe_certification` and `training_record` do not exist.
- Codes of list entries (`training_course`, `asset_type`, `evaluation_metric`, `funding_source`, and from v1.1 `stock_item_type`) cannot change once a row uses them (service rule), because codes appear in dimensions, CSV keys and snapshots. The category of a `stock_item_type` is frozen in the same way (D36).
- Stock quantities are never stored: the quantity of a lot on a date is the signed sum of its `stock_movement` rows dated on or before that date (D33).
- A person or an asset has one active or in-service interval (A14); someone who returns is entered as a new record.
- Currencies come from an allow-list with their decimal places (BRL, USD and EUR to start), kept in `domain/budget.py`, so minor units are well defined (D15). Adding a currency is a commit.
- In the sketch below, comments cite the appendix line (L) or the plan code (D, A, P) that motivates a column or constraint. The DDL is illustrative; the migration files are the source of truth.

### 5.2 Schema sketch
```sql
-- 0001_core.sql
CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;       -- is_demo, created_with
CREATE TABLE setting  (key TEXT PRIMARY KEY, value_json TEXT NOT NULL) STRICT;  -- readiness config (P01..P09)
CREATE TABLE change_log (
  id INTEGER PRIMARY KEY,
  at_utc TEXT NOT NULL,                  -- ISO 8601 UTC
  operator TEXT NOT NULL DEFAULT '',     -- optional operator label (D05)
  entity TEXT NOT NULL, entity_id INTEGER,
  entity_key TEXT,                       -- natural key as JSON, for tables without an integer id
  action TEXT NOT NULL CHECK (action IN ('insert','update','delete','import','restore')),
  before_json TEXT, after_json TEXT
) STRICT;
-- triggers: RAISE(ABORT) on UPDATE or DELETE of change_log (append-only)

-- 0002_personnel.sql
CREATE TABLE staff_member (
  id INTEGER PRIMARY KEY,
  identifier TEXT NOT NULL UNIQUE,       -- internal code, never a national ID (D17)
  label TEXT,                            -- optional short label
  category TEXT,                         -- configurable list (Q4)
  active_from TEXT NOT NULL, active_until TEXT     -- one active interval; a returning person is a new record (A14)
) STRICT;
CREATE TABLE ppe_certification (
  id INTEGER PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
  ppe_level TEXT NOT NULL CHECK (ppe_level IN ('A','B','C')),        -- L74
  issued_on TEXT NOT NULL,
  valid_until TEXT NOT NULL CHECK (valid_until >= issued_on),        -- A04
  no_renewal_from TEXT,                                              -- D24: NULL = renewal expected; the flag applies from this date
  no_renewal_reason TEXT CHECK (no_renewal_reason IN ('left_unit','role_change','other')),
  reference TEXT,                                                    -- hint: no names, health or contact data
  UNIQUE (staff_id, ppe_level, issued_on)                            -- import natural key (T8.4)
) STRICT;
CREATE TABLE training_course (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT,
  active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE training_record (                                       -- A09
  id INTEGER PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL REFERENCES training_course(id) ON DELETE RESTRICT,
  completed_on TEXT NOT NULL, hours REAL,
  UNIQUE (staff_id, course_id, completed_on)                          -- import natural key (T8.4)
) STRICT;
CREATE TABLE academic_degree (
  id INTEGER PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('specialisation','master','doctorate')),       -- L74
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','in_progress')), -- A10
  year INTEGER, field TEXT
) STRICT;
-- import natural key (T8.4); NULLs compare as distinct in UNIQUE, hence COALESCE
CREATE UNIQUE INDEX academic_degree_key ON academic_degree (staff_id, level, COALESCE(field, ''), COALESCE(year, 0));

-- 0003_infrastructure.sql
CREATE TABLE asset_type (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  built_in INTEGER NOT NULL DEFAULT 0,   -- seeded: bed, bay, neg_pressure_filtration, decon_tent (L76)
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT,          -- label_pt_br required for non-built-in rows (service, D16)
  default_maintenance_interval_days INTEGER CHECK (default_maintenance_interval_days >= 0),  -- NULL = not set; 0 = no scheduled maintenance (A06)
  active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE asset (
  id INTEGER PRIMARY KEY,
  type_id INTEGER NOT NULL REFERENCES asset_type(id) ON DELETE RESTRICT,
  tag TEXT NOT NULL UNIQUE, description TEXT, location TEXT,
  in_service_from TEXT NOT NULL, in_service_until TEXT,
  maintenance_interval_days INTEGER CHECK (maintenance_interval_days >= 0),  -- overrides type default; 0 = no scheduled maintenance (A06)
  notes TEXT
) STRICT;
CREATE TABLE asset_status_event (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  effective_on TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('operational','degraded','out_of_service')),  -- A05
  note TEXT,
  UNIQUE (asset_id, effective_on)
) STRICT;
CREATE TABLE maintenance_event (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
  performed_on TEXT NOT NULL,                                         -- L76
  kind TEXT NOT NULL CHECK (kind IN ('preventive','corrective','inspection')),
  next_due_on TEXT, note TEXT,
  UNIQUE (asset_id, performed_on, kind)                               -- import natural key (T8.4)
) STRICT;

-- 0004_exercises.sql
CREATE TABLE exercise_edition (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('CBRAMED','EXBRAMED','OTHER')),  -- L78, A13
  title TEXT,
  start_on TEXT NOT NULL, end_on TEXT NOT NULL CHECK (end_on >= start_on),
  participants INTEGER CHECK (participants >= 0),                     -- L78, D20
  notes TEXT
) STRICT;
CREATE TABLE exercise_country (
  edition_id INTEGER NOT NULL REFERENCES exercise_edition(id) ON DELETE CASCADE,
  country_code TEXT NOT NULL CHECK (length(country_code) = 2),        -- ISO 3166-1 alpha-2
  PRIMARY KEY (edition_id, country_code)
) STRICT;
CREATE TABLE evaluation_metric (                                      -- A07
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT,
  unit TEXT, scale_min REAL, scale_max REAL,
  higher_is_better INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE evaluation_result (
  edition_id INTEGER NOT NULL REFERENCES exercise_edition(id) ON DELETE CASCADE,
  metric_id INTEGER NOT NULL REFERENCES evaluation_metric(id) ON DELETE RESTRICT,
  value REAL NOT NULL, respondents INTEGER, note TEXT,
  PRIMARY KEY (edition_id, metric_id)
) STRICT;

-- 0005_budget.sql
CREATE TABLE funding_source (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,   -- seeded: DIRSA, COMAER (0005 + 0008) (L80)
  built_in INTEGER NOT NULL DEFAULT 0,
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT, active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE budget_entry (
  id INTEGER PRIMARY KEY,
  fiscal_year INTEGER NOT NULL,                                       -- A08
  source_id INTEGER NOT NULL REFERENCES funding_source(id) ON DELETE RESTRICT,
  currency TEXT NOT NULL CHECK (length(currency) = 3),                -- ISO 4217 (D15)
  allocated_minor INTEGER,
  description TEXT NOT NULL DEFAULT '', notes TEXT,                   -- empty description is ''
  UNIQUE (fiscal_year, source_id, currency, description)              -- import natural key (T8.4)
) STRICT;
CREATE TABLE budget_execution (                                       -- A08: dated, so execution can be read as of any date
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES budget_entry(id) ON DELETE CASCADE,
  executed_on TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),            -- D27
  note TEXT,
  UNIQUE (entry_id, executed_on, amount_minor)                        -- import natural key (T8.4)
) STRICT;

-- 0006_indicator_targets.sql
CREATE TABLE indicator_target (
  indicator_code TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
  warning_value REAL, critical_value REAL,
  enabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (indicator_code, dimension)
) STRICT;

-- 0007_snapshots.sql
CREATE TABLE readiness_snapshot (
  id INTEGER PRIMARY KEY, taken_at_utc TEXT NOT NULL, as_of TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('manual','monthly','report','retroactive')),
                                         -- 'retroactive' whenever the local date of taken_at_utc is after as_of, whatever triggered the snapshot (service rule, T8.1)
  app_version TEXT NOT NULL, config_hash TEXT NOT NULL,
  config_json TEXT NOT NULL,             -- exactly the fields that were hashed (T8.1)
  note TEXT
) STRICT;
CREATE TABLE readiness_snapshot_value (
  snapshot_id INTEGER NOT NULL REFERENCES readiness_snapshot(id) ON DELETE RESTRICT,
  indicator_code TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
  value REAL, status TEXT NOT NULL, warning_value REAL, critical_value REAL,
  PRIMARY KEY (snapshot_id, indicator_code, dimension)
) STRICT;
CREATE TABLE snapshot_withdrawal (       -- append-only: a snapshot is withdrawn, never deleted
  id INTEGER PRIMARY KEY,
  snapshot_id INTEGER NOT NULL UNIQUE REFERENCES readiness_snapshot(id) ON DELETE RESTRICT,
  withdrawn_at_utc TEXT NOT NULL, reason TEXT NOT NULL, operator TEXT NOT NULL DEFAULT ''
) STRICT;
-- triggers: RAISE(ABORT) on UPDATE or DELETE of the two snapshot tables and of snapshot_withdrawal
-- (snapshots are evidence for R31; a withdrawn snapshot stays stored but is ignored by exports and lists)

-- 0009_stock.sql (Phase 11, v1.1.0; 0008 only adds the COMAER funding source)
CREATE TABLE stock_item_type (                                        -- O01, D16: 17 built-in rows seeded, upper-case codes
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  built_in INTEGER NOT NULL DEFAULT 0,
  category TEXT NOT NULL CHECK (category IN ('antidote','decontaminant','detector','ppe','other')),  -- A16
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT,
  minimum_quantity INTEGER CHECK (minimum_quantity IS NULL OR minimum_quantity >= 0),               -- O04, P12: NULL = not set
  active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE stock_lot (
  id INTEGER PRIMARY KEY,
  type_id INTEGER NOT NULL REFERENCES stock_item_type(id) ON DELETE RESTRICT,
  lot_code TEXT NOT NULL,                                             -- hint: no clinical information (D38)
  expires_on TEXT,                                                    -- D34: required for antidote and decontaminant (service)
  unit_price_minor INTEGER, currency TEXT,                            -- D15: both or neither
  notes TEXT,
  UNIQUE (type_id, lot_code)                                          -- import natural key (T11.14)
) STRICT;
CREATE TABLE stock_movement (
  id INTEGER PRIMARY KEY,
  lot_id INTEGER NOT NULL REFERENCES stock_lot(id) ON DELETE CASCADE,
  moved_on TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('receipt','issue','disposal','loss','adjustment_in','adjustment_out')),  -- D33
  quantity INTEGER NOT NULL CHECK (quantity > 0),                     -- the sign comes from the kind
  reference TEXT NOT NULL DEFAULT '', note TEXT,
  UNIQUE (lot_id, moved_on, kind, quantity, reference)                -- import natural key (T11.14)
) STRICT;
```
Migration numbers 0002–0007 are reserved in `storage/migrations/README.md` until v0.1.0, so modules developed in parallel do not collide. After v0.1.0 every new migration takes the next free number at merge time (D06).

Migrations 0002–0005 were edited in place after their first merge; no release is tagged yet, so D06 allows it, and databases made with the earlier files are disposable developer or demo databases. The edits add CHECK constraints that repeat service rules, so a wrong row cannot get in by another path: every date column must have the shape `YYYY-MM-DD` (a `GLOB` check; whether the date exists stays a service rule); `active_until` ≥ `active_from`, `in_service_until` ≥ `in_service_from` and `next_due_on` ≥ `performed_on`, beside the existing `valid_until` ≥ `issued_on` and `end_on` ≥ `start_on`; a `no_renewal_reason` needs a `no_renewal_from`; `training_course.active` is 0 or 1; `hours` is not negative; a degree `year` and a `fiscal_year` lie between 1900 and 2200. The sketch above does not show these checks (QA findings P2-06, P3-04, and the schema checks of the Phase 4 and Phase 5 QA).

### 5.3 Relations
- `staff_member` 1–n `ppe_certification`, `training_record`, `academic_degree`. `training_course` 1–n `training_record`.
- `asset_type` 1–n `asset`. `asset` 1–n `asset_status_event` and `maintenance_event`. An asset's status on a date is its latest status event on or before that date.
- `exercise_edition` 1–n `exercise_country` and `evaluation_result`. `evaluation_metric` 1–n `evaluation_result`.
- `funding_source` 1–n `budget_entry`. `budget_entry` 1–n `budget_execution`: the executed amount of an entry on a date is the sum of its rows dated on or before that date.
- `stock_item_type` 1–n `stock_lot`. `stock_lot` 1–n `stock_movement`: the quantity of a lot on a date is the signed sum of the movements dated on or before that date (D33). A type that has lots cannot be deleted; a built-in type is never deleted.
- `readiness_snapshot` 1–n `readiness_snapshot_value`, and 0–1 `snapshot_withdrawal`. Neither snapshot table can be deleted; a withdrawal row is the only way to take a snapshot out of use.
- `indicator_target` and `readiness_snapshot_value` refer to indicator codes from the code registry (`domain/registry.py`), not to tables.
- `change_log` refers to any table by entity name and row id (or by `entity_key` for tables without an integer id). It has no foreign key on purpose, so it outlives deleted rows. Cascaded children get their own `delete` rows (§5.1).

### 5.4 Proposed initial indicators (D13, D14)
Every indicator is computed for the as-of date, either the global selector or a snapshot date, from the dated records as known today and with the current configuration (D13). Only snapshots record what was known and configured at the time. An indicator can be split by a *dimension*, such as the PPE level or the funding source; targets are stored per (code, dimension). A dimension with several parts is encoded as sorted `key=value;key=value` text built from codes (for example `currency=BRL;source=DIRSA`, `level=A;status=completed`); the code of a list entry cannot change once it is used (§5.1).

Statuses:
- **OK**, **Warning** or **Critical** when a target exists;
- **No target** when none is configured — the default, so the app invents no readiness standard (P03);
- **No data** when the value cannot be computed.

| Code | Proposed definition | Unit | Dimension | Source | Default target |
|---|---|---|---|---|---|
| `PERS_CERT_VALID` | Active staff whose counting PPE qualification at the level (the rule stated once in A03) is valid on the as-of date | people | level A/B/C | R14 | none |
| `PERS_CERT_EXPIRING` | Active staff whose counting PPE qualification at the level (A03) is valid, expires within the warning window (P01), and is not marked "no renewal" on the as-of date (D24) | qualifications | level | R15, R25 | none |
| `PERS_RETRAINING_NEEDED` | Active staff needing retraining as defined in A03 | people | level | R15, R36 | none |
| `PERS_DEGREE` | Active staff with a degree at the level (completed; in-progress counted separately) | people | level, status | R16 | none |
| `PERS_TRAINING_12M` | Training records completed in the 12 months before the as-of date | records | — | R16, A09 | none |
| `INFRA_AVAILABLE` | A count of available units: units in service and operational. The total of units in service is shown beside it as context | units | asset type | R17–R19, A01, A05 | none |
| `INFRA_MAINT_OVERDUE` | Units in service whose maintenance due date is before the as-of date | units | asset type | R20, R26 | none |
| `EX_LAST_PARTICIPANTS` | Participants in the latest edition that ended on or before the as-of date | participants | kind | R22 | none |
| `EX_LAST_COUNTRIES` | Countries represented in that edition | countries | kind | R22 | none |
| `EX_DAYS_SINCE_LAST` | Days since the latest edition ended. *A design proposal (D), not stated in the appendix; needs Q1.* | days | kind | R05 | none |
| `BUD_EXEC_RATE` | Executed ÷ allocated for the as-of date's fiscal year, where executed is the sum of the `budget_execution` rows dated on or before the as-of date; No data when allocated is missing or zero. The rate is year-to-date, so its status compares it with the target multiplied by the elapsed fraction of the fiscal year (day of the year ÷ days in the year, linear pro-rating, P08); otherwise a year-end target would read Critical every January | ratio | source, currency (`currency=BRL;source=DIRSA`) | R24 | none |
| `STOCK_VALID_QTY` | Valid quantity of a stock item type on the as-of date: the on-hand quantity of its lots that are not expired (D34). The on-hand, expired and expiring quantities and the minimum (when set) are returned as context. A value exists only for a type that is in use on the date or has a minimum (D36) | units | category, item (`category=antidote;item=ANTIDOTE_CHEMICAL`) | O01, O02, O04 | none |
| `STOCK_LOTS_EXPIRING` | Lots with stock on hand that expire within the warning window (P11, 90 days), expiry date inclusive | lots | category | O03, P11 | none |
| `STOCK_LOTS_EXPIRED` | Lots with stock on hand whose expiry date is before the as-of date | lots | category | O03 | none |
| `STOCK_TYPES_BELOW_MIN` | Active item types of the category whose valid quantity is below their minimum (D35); produced only for a category with at least one active type that has a minimum (P12) | item types | category | O04, P12 | none |

A composite "readiness score" is **not** computed in v1. Its formula would be an invented domain fact (Q9, deferred item X4). The "panel reading" for R31 is the full vector of indicator values and statuses stored in a snapshot.

### 5.5 Alert kinds
Alerts are computed when needed, not stored. They are sorted by severity, then by due date. Info-level alerts are listed on the Alerts page but never trigger the start-up summary (T6.6).

| Kind | Trigger | Severity | Source |
|---|---|---|---|
| `CERT_EXPIRED` | An active person's counting PPE qualification at a level (A03) has expired and `no_renewal_from` is not set or is later than the as-of date (D24) | critical | R25, R15 |
| `CERT_EXPIRING` | That qualification is valid and expires within P01 | warning | R25 |
| `MAINT_OVERDUE` | An in-service asset's due date (A06) is before the as-of date | critical | R26 |
| `MAINT_DUE_SOON` | Its due date falls within P02 | warning | R26 |
| `MAINT_SCHEDULE_UNKNOWN` | An in-service asset has neither an interval nor a recorded next-due date. An interval of 0 with no recorded next-due date means "no scheduled maintenance" and raises no alert (A06) | info (data quality, D) | I05 |
| `INDICATOR_WARNING` / `INDICATOR_CRITICAL` | An indicator value crosses a configured, enabled target | warning / critical | R27 |
| `LOT_EXPIRED` | A lot has stock on hand and its expiry date is before the as-of date (D34) | critical | O03 |
| `LOT_EXPIRING` | A lot has stock on hand and expires within P11 | warning | O03, P11 |
| `LOW_STOCK` | An active item type has a minimum and its valid quantity is below it (D35) | critical | O04, P12 |

The three stock kinds are added by Phase 11 (v1.1.0). An empty lot never raises a lot alert, there is at most one lot alert per lot and one `LOW_STOCK` per type, and there is no info-level stock kind. The alert and subject kinds do not start with `STOCK_`, because `docs/indicators.md` reserves that prefix for indicator codes.

---

## 6. Internationalisation

- **Languages:** pt-BR is the default on first start, whatever the Windows locale (F03). en-US and es-ES are available. The user switches through a Language menu and in Settings; the choice is saved in `prefs.json` in the data folder. A `--lang` option overrides it for one run. If the data folder is read-only, preferences (the language included) cannot be saved and are kept for the session only.
- **Source strings:** written in English in the code. Use `QCoreApplication.translate("<Context>", "...")` with an explicit context per module. The context argument must be a string literal (no constant or variable), because `pyside6-lupdate` extracts only literals; a guard test in T0.6 fails on a non-literal context. The pitfall that motivates this is that with `self.tr()`, inherited methods may take the subclass's context and lose their translation; this is to be confirmed by a test in T0.6. Outcome of that test on PySide6 6.12.0: with a catalogue holding only the base class's context, `self.tr()` in an inherited method still returned the translation for an instance of a subclass, so the pitfall was not reproduced.
- **Catalogues:** one per area (`shell`, `personnel`, `infrastructure`, `exercises`, `budget`, `dashboard`, `alerts`, `settings`, `backup`, `reports`, and from v1.1 `stock` and `antidotes`), times three languages. They are `.ts` XML files in `src/cbrn_dashboard/i18n/`, and the map from area to source folders is in `i18n/__init__.py`. *Reason:* agents working in parallel do not edit the same module catalogue. The `shell` catalogue is the exception: several tasks touch it, so they merge one at a time (§10.2). `scripts/i18n.py update` runs `lupdate` with `-locations none`, so the `.ts` files do not churn.
  - `en_US` is a real catalogue too (identity translations plus English plural forms), so the completeness rule is the same for all three languages.
  - `.qm` files are compiled by `scripts/i18n.py compile`, by a session fixture in the tests and by the build. They are never committed (they go in `.gitignore`). `lrelease` is run so that unfinished messages are still shipped.
  - Running from source without compiled `.qm` files shows the English source strings and a warning banner; nothing is compiled silently.
- **Live switching:** the translator manager removes the old translators and installs the new ones — the app catalogues plus Qt's own `qtbase_*` translations where the wheel provides them — and sets the default `QLocale`. Qt then sends a `LanguageChange` event, and each widget's `retranslate()` re-applies its texts. Table models translate their headers on every `headerData` call. `QLocale.setDefault()` does not update existing widgets, so on a language change each locale-aware widget (date edits, number and amount inputs) gets `setLocale()` in its `retranslate()`.
- **Codes, not text, below the UI:** the domain and services layers return enum codes and parameters: alert kinds, validation error codes, statuses. Each UI area's `labels.py` maps codes to translated strings; a test makes sure every enum member has a label. Plural-aware messages use `%n`, for example "expires in %n day(s)".
- **Stock terms (v1.1.0):** the 17 built-in stock item types are named in the catalogues by their pt-BR wording exactly as the owner wrote it (title case, for example "Antídoto Químico" and "Maca Bolha (Cápsula de Isolamento para Transporte)"), with en-US and es-ES equivalents. The tab title "Aprazamento de vencimentos" and the title-case names are flagged for the terminology review (Q14).
- **User-defined list entries:** asset types, courses, metrics, funding sources and stock item types store three label columns, of which only `label_pt_br` is required (enforced in the service, D16). Display falls back from the current language to pt-BR, then en-US, then the code.
- **Dates and numbers:**
  - Dates are stored as ISO text and displayed with explicit four-digit-year patterns: pt-BR `dd/MM/yyyy`, es-ES `dd/MM/yyyy`, en-US `MM/dd/yyyy`. Date entry uses `QDateEdit` with a calendar pop-up.
  - Numbers, percentages and money are formatted and parsed with `QLocale`. The decimal separator is a comma for pt-BR and es-ES and a point for en-US. Currency symbols come from a small map (BRL→R$, EUR→€, USD→US$); other currencies show their ISO code.
  - Exports always use the locale-independent format (§4.3, D04).
  - The exact `QLocale` strings depend on the CLDR version inside the pinned Qt (for example, es-ES may not group four-digit numbers). Expectations are regenerated deliberately on a Qt upgrade.
- **Countries:** a `countries.json` file generated from CLDR (via Babel, development time only) holds names in all three languages, with the Unicode licence notice in `resources/THIRD_PARTY_DATA.md`.
- **Reports** are generated in a language chosen in the report dialog; the default is the current UI language. The report renderer loads its own `QTranslator` set for the chosen language, calls those translators directly and formats with an explicit `QLocale`; it never swaps the application's installed translators. Labels shared with the UI are reachable through a Qt-free code→message-key map (`reports/message_keys.py`), so `reports/` does not import `ui/`.
- **Tests that keep the three languages complete** (`tests/i18n/`, `tests/ui/`):
  1. All three catalogues of each area contain the same set of source messages.
  2. Every translation is non-empty and placeholder-complete, none is obsolete or "vanished", and plural forms are complete. pt-BR and es-ES messages keep Qt Linguist's `type="unfinished"` until the committee reviews them (Q14); `lrelease` is run so unfinished messages are still shipped.
  3. Placeholders match between source and translation (`%1`…`%9`, `%n`).
  4. **Sync check:** running `pyside6-lupdate` (with `-locations none`) on a temporary copy of each catalogue adds or removes no messages, so every string in the code has been extracted.
  5. `pyside6-lrelease` compiles every catalogue without warnings.
  6. **Pseudo-locale check:** a test-only catalogue wraps every translation as `⟦…⟧`. Every registered page and every dialog in the dialog registry (T1.9) is opened and every widget text, title, action, tooltip and header is walked; any visible non-data text without the markers fails the test. This catches hard-coded strings and missing `retranslate()`.
  7. Every enum member (alert kinds, statuses, error codes) has a non-empty label in all three languages.
  8. Formatting tests assert exact strings for fixed dates, numbers and amounts in each locale (non-breaking spaces written explicitly).
- **Human review:** translations written during development are drafts and stay marked unfinished (check 2). The committee reviews the terminology (Q14) before v1.0. Glossary terms are written from scratch, not taken from PTT 1 material or internal documents (F06).

---

## 7. Security and privacy

### 7.1 Data classification
- **Sensitive** (real data, local only): personnel records — qualifications of identifiable staff, which the plan treats as personal data under Brazil's LGPD — infrastructure status, budget figures and, from v1.1, stock data (lots, quantities, expiry dates, prices, movements; Q27, D37). "Sensitive" is this plan's working label for data that stays local. It is not a classification under the access-to-information law or military rules.
- **Public:** code, fictitious demo data, translations, documentation.
- **Formal classification is not known (Q19).** The plan does not know whether any of this data is classified or access-restricted under Lei 12.527/2011 (arts. 23–28) or under military rules. As the plan reads Lei 12.527/2011 art. 28 and Decreto 7.845/2012 art. 19, a classification is made by a formal decision of the competent authority; this is not legal advice. The statute text: Decreto 7.845/2012 requires, for classified information, cryptographic resources based on a State algorithm and isolated equipment (arts. 31, 39, 40). The plan's reading, not legal advice: if the data is classified, this design — plaintext SQLite, plaintext automatic backups, commercial cryptography, an unsigned binary from a public repository — is unsuitable, and real data must not be entered. Q19 gates the entry of real data.
- **Committee answers are not public.** The repository and the changelog record only the status of each question, never the content of an answer (T10.5, §7.3).

### 7.2 Threats considered
1. Loss or theft of the workstation or of backup media.
2. Accidental publication through the repository, issues, screenshots or test fixtures.
3. Copying a portable-mode folder that contains data.
4. Casual access by another local Windows user.
5. Data leaving through the network or cloud sync.
6. Data loss: corruption, a failed migration, a bad restore, a forgotten passphrase.

Out of scope: malware or an administrator on the running machine; forensic recovery from SSDs.

### 7.3 Controls
| Control | Threats | Where |
|---|---|---|
| No network code: a guard test forbids `socket`, `ssl`, `urllib`, `urllib3`, `http`, `requests`, `httpx`, `ftplib`, `smtplib`, `xmlrpc`, `imaplib`, `poplib`, `asyncio`, `webbrowser`, `PySide6.QtNetwork`, `PySide6.QtWebSockets` and `QtWebEngine*`, and hand-offs to the shell or to other programs (`subprocess`, `ctypes`, `os.startfile`, `QDesktopServices`), with the narrow exceptions of T0.4; Qt network and web libraries are excluded from the bundle; no update check, telemetry or crash upload. It covers sockets and Qt networking and relies on the hand-off guard for the shell; it cannot see what another program does with a file the user opens | 5 | T0.4, T0.9, T9.1 |
| Data minimisation: staff identified by an internal code with an optional label; no national ID numbers, birth dates, contact or health data and no free-text notes columns on personal records (D17); hints on the remaining free-text fields; a "pseudonymise person" action; exercise participants only as counts (D20) | 1, 2, 4 | T2.1, T2.3, T2.4, T4.1 |
| Per-user profile location; warnings for network paths and OneDrive (D02), which detect the common cases (environment prefixes, registry mount points, cloud-placeholder attributes) and cannot prove that a folder is not synced | 4, 5 | T0.5, T7.5 |
| Full-disk encryption required by documentation and shown in a first-run notice (D03). The app cannot verify it, and it does not protect files exported to removable media | 1 | T7.5, `docs/data-protection.md` |
| Encrypted backups: Fernet (AES-128-CBC with HMAC-SHA256) with a 64-byte key derived by scrypt (n=2^17, r=8, p=1, explicit `maxmem`; the reader accepts only parameter sets from an allow-list): 32 bytes for Fernet and 32 for an HMAC-SHA256 over the header; a trailing unkeyed SHA-256 detects corruption. The passphrase must meet P05 (at least 12 characters) and a small strength rule, and is never stored; a forgotten passphrase means the backup is unrecoverable, and the user is warned. Fernet holds the whole file in memory and exposes the creation time; Argon2id may replace scrypt if Q11 requires it (X13) | 1, 6 | T7.2 |
| Decrypted temporary files only inside `<data>\tmp\`, deleted after use; `tmp\` emptied at start-up. Migrating the temporary copy during restore runs with the pre-migration backup turned off. Temporary files are plain files: they are protected by profile permissions and full-disk encryption only | 1, 4 | T7.3 |
| Restore copies into the live database with SQLite's backup API after the safety copy, with a single-instance lock on the data folder; it refuses a backup whose demo flag differs from the open database | 6 | T1.9, T7.3 |
| `PRAGMA secure_delete=ON` (limited on SSDs by wear levelling). It does not reach values held in `change_log` or in backups | 1 | T1.2 |
| Anonymised report: counts only, no identifiers, notes or free text; from v1.1 no per-type stock quantities, values or prices and no stock chart (D37, Q27); personnel-derived counts from 0 to threshold − 1 shown as "< threshold", with secondary suppression of totals and sibling cells and charts built only from the suppressed model (A11); PDF metadata checked for operator and institution names. Differencing between successive reports remains a residual risk (Q10) | 2, 5 | T8.5, T8.6 |
| Exports and reports written by the operator: CSV and PDF output paths get the same network, cloud-sync and removable-media warnings as the data folder; CSV cells are protected against formula injection; the internal report carries a handling notice set locally in Settings (empty by default, like D18). The validation export is labelled as unsuppressed internal data | 1, 5 | T8.3, T8.7 |
| Append-only change log (keeps old values of non-personal columns; for personal free-text columns it records only that the column changed; one row per affected row, cascades included; retention is Q12) | audit | T1.4 |
| Logs hold event codes, exception types and frames only, never record contents or exception messages (D22) | 2 | T1.8 |
| Demo data separated: own file, own backups, `DEMO` prefix, banner driven by `app_meta.is_demo`, PDF watermark, `DEMO-` CSV names; restore refuses a demo/real mismatch (D25) | 2 | T1.7, T7.3, T8.3, T8.6 |
| Clock sanity check at start-up: if the current UTC instant is earlier than the newest `change_log.at_utc` or the build timestamp (UTC), a banner is shown and automatic snapshots and backup rotation are skipped for that session | 6 | T1.9 |
| Repository hygiene: `.gitignore` rules, a test over tracked files, contribution rules, a warning in the issue template. PLAN.md and the changelog record only the status of each open question, never the content of an answer; answers, thresholds, security rules, deployment constraints, retention rules and institution names live in a private document outside the repository, and real targets are entered in Settings and never become code defaults | 2 | T0.3, T10.5 |
| Content licensing: no clinical content (D19); no text from the WHO guide or internal documents; pull-request checklist | licence | T0.3 |
| Supply chain: `uv.lock` with hashes; GitHub Actions pinned by commit SHA; Dependabot; dependency-licence allow-list test; provenance attestation. `SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity; the attestation proves where and how the build ran, not that the program is safe | integrity | T0.8, T9.2, T9.3, T9.5 |
| LGPD note: the plan assumes the institution is the data controller. The software supports minimisation, OS-level access control and pseudonymisation; values already written to backups persist until those backups are deleted, which the data-protection guide explains. The legal assessment belongs to the institution (Q4, Q11, Q12). *The plan's reading, not legal advice:* the national-defence exclusion (LGPD art. 4, III) requires an exclusive purpose and probably does not cover staff-management data; an internal code is pseudonymisation, and the data stays personal (art. 13, §4) | — | `docs/data-protection.md` |

---

## 8. Packaging and distribution

- **Target:** Windows 10 (1809 or later) and Windows 11, x64. No admin rights, no installer, no registry writes. Qt 6.12 is the last Qt release that supports Windows 10, so the constraint is `PySide6>=6.8,<6.13` while Windows 10 is a target (K17).
- **Artefact:** `cbrn-readiness-dashboard-<version>-win-x64.zip` contains one folder, `cbrn-readiness-dashboard\`, holding:
  - `cbrn-dashboard.exe` and `_internal\` (Python, Qt, catalogues, resources);
  - `licenses\` (third-party licence texts);
  - `README-first-run.{pt-BR,en-US,es-ES}.txt`;
  - `portable.ini.example`.

  The release also carries `SHA256SUMS.txt`, a per-file SHA-256 manifest of the bundle and a build-provenance attestation. `SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity; the attestation proves where and how the build ran, not that the program is safe.
- **First run:** extract the whole zip first. Running the program from inside Explorer's zip preview fails, because `_internal\` is missing. Verify the checksum with `Get-FileHash`. Optionally verify the attestation with `gh attestation verify` (this needs network access and is done by the user, not the app). If needed, unblock the zip in its file properties before extracting; Windows' own extractor passes the Mark-of-the-Web on to the extracted files unless the zip was unblocked first, and other extractors behave differently. On SmartScreen choose "More info → Run anyway". The first-run notice explains where the data lives, the disk-encryption requirement and its limits, that "sensitive" is not a formal classification, and how several people can share one machine.
- **Locked-down machines:** AppLocker/WDAC or Smart App Control may block unsigned programs, or programs run from user-writable folders.
  - When AppLocker is enforced, its default rules allow only Windows, Program Files and administrators, so the extraction folder must be a path that IT allows.
  - Hash rules are per file and per release. With DLL rules or WDAC they must cover the `.pyd` and DLL files too, so the release publishes a per-file SHA-256 manifest of the bundle next to `SHA256SUMS.txt` (which covers only the zip).
  - Smart App Control has no per-file bypass.
  - Only code signing (X6) removes this need. The one-folder build never needs to run code from `%TEMP%`.
- **Upgrades:** extract the new version to a new folder; the data in the profile is untouched. On first start the app backs up the database and migrates it. A database written by a newer version is refused, so downgrades are blocked.
- **Portable mode:** rename `portable.ini.example` to `portable.ini`; data then goes to `.\data\`. A warning explains that copying the folder copies the data.
- **Self-test:** `cbrn-dashboard.exe --self-test --data-dir <folder>` checks paths, the database and its migrations, the three languages, main-window creation, chart rendering, an encrypted-backup round trip and PDF rendering (each check is added by the task that creates the feature). It never opens the real database: it works in a throwaway `tmp\selftest-*` folder under the resolved data folder and writes only `selftest.json` beside it, then exits 0 or 1. The windowed executable has no console, hence the file. CI runs it on every build.
- **Licences:** the bundle contains every runtime dependency's licence text, together with GPL-3.0 and LGPL-3.0 and PyInstaller's bootloader exception notice. `licenses\` also carries Qt's third-party attributions (from the Qt SBOM/attribution files of the bundled version), the OpenSSL licence (inside `cryptography` and CPython), CPython's bundled-library notices, the Microsoft Visual C++ runtime redistribution notice, and a pointer to the Qt and PySide6 source release with a written offer. The About dialog (v1.0, T10.2) shows the version, the GPL notice (no warranty), the source URL as plain text, and the component list. Each release page links the matching source tag of this project and the exact Qt and PySide6 source release matching the bundled version, and carries the written offer (GPL-3.0 §6, LGPL).
- **Bundle checks:** the build test fails if numpy, matplotlib, `QtWebEngine` or `Qt6Network` appears in the bundle, and it prints the total size so growth is visible. PyInstaller's `--exclude-module` takes Python module names and may leave Qt DLLs behind, so the build script deletes the unwanted Qt DLLs and plugins from `_internal` after the build; the test asserts on the files actually present and then runs the self-test to prove nothing needed them.

---

## 9. Testing strategy

- **Layers:**
  - `tests/domain/`: pure, fast and the majority. Table-driven, with a fixed clock.
  - `tests/storage/`: real SQLite files in `tmp_path`, migrations, constraints, backups.
  - `tests/services/`: integration of storage and domain on seeded fictitious data.
  - `tests/ui/`: pytest-qt with `QT_QPA_PLATFORM=offscreen`. View models and services do the computing; widget tests check wiring, validation messages and translation only.
  - `tests/i18n/`: §6.
  - `tests/reports/`: PDFs read back with pypdf; assertions on text, never pixels (subject to the T8.6 spike on text extraction; if it is unreliable, content assertions move to the Qt-free report model).
  - `tests/meta/`: ruff, mypy, forbidden-API and layering guards, repository hygiene, workflow pinning, dependency licences, documentation sync.
  - `tests/packaging/` (marker `packaging`): builds the executable and runs its self-test.
- **Determinism rules:**
  - No clock calls outside `clock.py` (guard test). Domain code takes `as_of` as a parameter; tests use `FixedClock`.
  - Random demo data uses a fixed seed.
  - Every file goes to `tmp_path`. An autouse session fixture points `CBRN_DASHBOARD_DATA_DIR` to a temporary folder, so tests can never touch a real data folder.
  - The offscreen platform is set in `tests/conftest.py` before Qt is imported.
  - Qt warnings fail tests (`qt_log_level_fail = WARNING`), except benign offscreen-platform messages listed by exact text in `qt_log_ignore`. The offscreen platform on Windows may emit a font-directory warning; it is the kind of message `qt_log_ignore` exists for, added by exact text when first seen in CI, with a comment.
  - All fixtures are fictitious.
- **Commands:**
  - `uv run pytest` runs the default suite; `addopts` deselects `packaging`.
  - `uv run pytest -m packaging` builds and checks the executable.
  - `uv run pytest <path>` runs one task's check.
- **CI gates:** the default suite on Windows; coverage of at least 90% for `domain`, `storage` and `services`, applied only in CI (`--cov-fail-under`), because single-task runs cover only part of the code; the packaging suite.
- **Human checks per release:** view every page in all three languages; start the app on a clean Windows profile without admin rights; back up to removable media and restore; generate both PDFs; the committee runs `docs/manual-test-script.pt-BR.md` with the demo data.

---

## 10. Phases and tasks

### 10.1 Working rules for coding agents
- **One task per commit or pull request.** The commit message starts with the task id (for example `T2.3: …`). Do not add AI co-author lines or "Generated with …" lines; this is the project owner's standing rule.
- **When a task is done:** its own check passes, and the whole default suite (`uv run pytest`) passes too. The suite includes:
  - ruff and mypy (T0.2);
  - the layering and forbidden-API guards (T0.4);
  - repository hygiene (T0.3);
  - translation completeness and sync (§6).

  A task that breaks another task's test is not done. A task that adds a self-test check or a bundled resource also runs the packaging check (`uv run pytest -m packaging tests/packaging/test_build.py`).
- **Translations travel with the code.** Every new user-visible string is added to its area's three catalogues by `uv run python scripts/i18n.py update`, then translated: pt-BR and es-ES in full, en-US as identity plus plural forms. Messages must be non-empty and placeholder-complete, but pt-BR and es-ES messages keep `type="unfinished"` until the committee reviews them (Q14). These are drafts.
- **Schema changes.** Until v0.1.0 they go only into the module's reserved migration file (`storage/migrations/README.md`), and developer and demo databases are disposable. From v0.1.0 on, migrations are append-only: fix forward with a new file numbered max+1 at merge time, never edit a shipped one.
- **Nothing beyond the appendix is invented silently.** Any rule the appendix does not state is declared in `domain/config.py` with a `placeholder` flag, and the same commit adds it to §3.5 of this plan.
- **Plan amendments.** New A, P and D ids are assigned at merge time (next free number). Design decisions go to §3.4 and assumptions or placeholders to §3.5. A task that adds one lists `PLAN.md` in its Files.
- **Data:** fixtures and demo data are fictitious. Demo identifiers start with `DEMO`. Never copy figures from the thesis or from real records into the repository. No text from the WHO guide or from internal hospital documents, and no clinical content (F06, D19).
- **Layering (D11):** `domain/` and `services/` stay Qt-free. The UI reaches data only through `services/`. Modal dialogs and file pickers go through the prompts interface (T1.9), so tests can replace them.
- **Time and files:** use `Clock`/`FixedClock`, never the wall clock (T0.4). Write files only under `tmp_path` in tests. Never read or write a real data folder.
- **Python files** start with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- **Size labels:** S ≈ under 200 changed lines, M ≈ 200–600, L ≈ over 600. Split an L task if a natural cut exists.
- **Checks:** every check below is a pytest run. Build-dependent checks carry the `packaging` marker and are run explicitly with `-m packaging`.

### 10.2 Dependency graph and parallelism
```
Phase 0
  T0.1 ─┬─► T0.2 ─► T0.8 ──────────────┐
        ├─► T0.3                       │
        ├─► T0.4                       ├─► T0.9
        ├─► T0.5 ─┐                    │
        └─► T0.6 ─┴─► T0.7 ────────────┘
Phase 1
  T1.1 (needs T0.4) ─► T1.6
  T1.2 ─► T1.3 (also T0.7) ─┬─► T1.4 (also T1.1) ─► T1.8 (also T0.5, T0.7) ─┐
                            ├─► T1.5 (also T0.7) ───────────────────────────┼─► T1.9 (also T0.7, T1.1)
                            └─► T1.7 (also T0.7) ───────────────────────────┘
  T1.10 (needs T0.6)
Phases (a summary; the task-level "Depends on" lines are authoritative)
  P0 ─► P1 ─┬─► P2 ─┐
            ├─► P3 ─┤
            ├─► P4 ─┼─► P6 ─┬─► T8.1 (MVP) ─┬─────────────────────────┐
            ├─► P5 ─┘       │               ▼                         │
            │               └─────────────► T8.2–T8.7 ─► T9.1 ─► P10  │
            └─► P7 (in parallel with P2–P6) ──────────────────────────┴─► T9.6 (closes the MVP)
  T9.2 and T9.3 can start any time after T0.9, and T9.4 after T0.9 and T9.3 (all three are part of the MVP);
  T9.5 after T0.8. T9.6 needs every MVP task.
```
The task-level "Depends on" lines in §10.3 are authoritative; the arrows above are a summary.

What can run in parallel:
- **Phase 0:** after T0.1, tasks T0.2, T0.3, T0.4, T0.5 and T0.6 run in parallel (up to five agents). T0.7 waits for T0.5 and T0.6. T0.8 needs only T0.2, so it runs alongside T0.7. T0.9 comes last.
- **Phase 1:** T1.1 (after T0.4), T1.2 (after T0.1) and T1.10 (after T0.6) each start as soon as their Phase 0 dependency has merged, without waiting for T0.7. T1.3 follows T1.2 and T0.7. Then T1.4, T1.5, T1.6 and T1.7 run in parallel (T1.6 needs only T1.1). T1.8 follows T1.4, and T1.9 closes the phase.
- **Phases 2–5:** one agent per module, all in parallel. Inside a module, the schema task (T*.1) and the domain task (T*.2) run in parallel; then the repository and service task; then the UI and demo tasks in parallel. T4.2 (country data) depends only on T0.1 and can run at any time.
- **Phase 7** starts after T1.9, the last task of Phase 1 (T7.1 needs it; T7.5 also needs T7.2). It needs nothing from Phases 2–6, so it runs alongside them.
- **Phase 6** starts once Phases 2–5 have merged. Its alert-rule task T6.2 may begin as soon as the domain tasks T2.2 and T3.2 exist.
- **T8.1** (snapshots, MVP) follows T6.1 and T6.5; the rest of Phase 8 and T9.1 are v1.0. **T9.6** closes the MVP once every MVP task has merged.
- **Phase 11** (v1.1.0) starts after the v1.0 tasks and is a separate release. After T11.2, the schema task T11.3 and the rules task T11.4 run in parallel. Then the chain is T11.5 → T11.6, after which two branches run in parallel: indicators and alerts (T11.7 → T11.8) and the shared stock UI (T11.9 → T11.10). The antidotes page T11.11 joins them; T11.13 (Settings) needs T11.5 and T11.9 only, and T11.14 (CSV) needs T11.6 only, so both can start earlier. The chain inside Phase 11 is 11 tasks: T11.2 → T11.4 → T11.5 → T11.6 → T11.7 → T11.8 → T11.11 → T11.12 → T11.16 → T11.18 → T11.19. Shared files touched by several Phase 11 tasks, which therefore merge one at a time: `domain/indicators.py`, `domain/alerts.py`, `domain/config.py`, `services/snapshots.py`, `ui/infrastructure/page.py`, `ui/dashboard/page.py`, `ui/shell/registry.py`, `i18n/__init__.py`, `PLAN.md` §3.5 and the `shell` catalogue.
- **Longest chain:** 16 tasks that must run one after another: T0.1 → T0.5 or T0.6 → T0.7 → T1.3 → T1.4 → T1.8 → T1.9 → a module UI task (T2.4, T3.4, T4.5 or T5.4) → T6.1 → T6.2 → T6.5 → T8.5 → T8.6 → T8.7 → T10.2 or T10.4 → T10.5. The branch T6.5 → T8.1 → T8.2 → T8.7 is equally long. The documentation branch T9.3 → T9.4 → T10.3 → T10.5 is shorter.
- **Conflict hot spots and their rules:**
  - Migration numbers are reserved in advance until v0.1.0 (T1.3), then taken as max+1 at merge time.
  - Module translation catalogues are split per area (D07); the `shell` catalogue is shared.
  - A module registers itself with one line in each of `ui/shell/registry.py`, `domain/registry.py`, `demo/__init__.py` and `i18n/__init__.py`; start-up hooks are one line each in `app.py` (T1.9).
  - Shared files that several tasks edit: `ui/shell/main_window.py`, `ui/shell/banners.py`, `i18n/shell_*.ts`, `selftest.py` (checks are added by T1.3, T6.4, T7.2 and T8.6), `app.py`, `pyproject.toml` with `uv.lock`, `tests/meta/test_workflows.py`, and PLAN.md §3.4 and §3.5.
  - Tasks that touch the same shared file merge one at a time: rebase, rerun the suite, then merge. Suggested order: T7.5 before T6.6 (shell files), and T7.2 before T6.4 (`selftest.py`).
  - Before merging, rebase and rerun the whole default suite.

### 10.3 Phases

#### Phase 0 — Scaffolding (MVP)

**T0.1 — Project metadata and package skeleton** (S) · Depends on: —
- Files: `pyproject.toml`, `uv.lock`, `.python-version`, `src/cbrn_dashboard/__init__.py`, `src/cbrn_dashboard/__main__.py`, `tests/test_package.py`.
- Work:
  - hatchling build backend with the src layout;
  - PEP 639 licence metadata (`license = "GPL-3.0-or-later"`, `license-files = ["LICENSE"]`);
  - the version kept once, in `__init__.py`, and read by hatch;
  - runtime dependency `PySide6>=6.8,<6.13` (Qt 6.12 is the last release supporting Windows 10, K17);
  - dependency groups `dev` (pytest, pytest-qt, pytest-cov, ruff, mypy) and `build` (pyinstaller);
  - `.python-version` set to `3.12` (D12);
  - `__main__.py` handles only `--version` for now.
- Accept: the package imports; the installed metadata version equals `__version__`; `python -m cbrn_dashboard --version` prints the version and exits 0.
- Check: `uv run pytest tests/test_package.py`

**T0.2 — Lint, format and type gates run from pytest** (S) · Depends on: T0.1
- Files: `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`), `tests/meta/test_tooling.py`.
- Work:
  - ruff rules E, F, W, I, B, UP, SIM, RUF, DTZ, T20, PTH and N;
  - mypy strict on `domain`, `services`, `storage`, `reports/model.py` and `reports/anonymise.py`;
  - pytest settings: `testpaths = ["tests"]`, markers `ui`, `packaging`, `slow`, `addopts = -m "not packaging"`, `qt_api = "pyside6"`, `qt_log_level_fail = "WARNING"`, and `qt_log_ignore` listing the benign offscreen-platform messages by exact text. The offscreen platform on Windows may emit a font-directory warning; it is added by exact text when first seen in CI, with a comment.
  - per-file ignores for `T201` (print) in `src/cbrn_dashboard/__main__.py`, `src/cbrn_dashboard/cli.py` and `scripts/**`.
- Accept: the test runs `ruff check`, `ruff format --check` and mypy through `sys.executable -m …` and asserts each exits 0. A deliberately bad file in `tmp_path` is reported, which proves the gate works.
- Check: `uv run pytest tests/meta/test_tooling.py`

**T0.3 — Repository hygiene, ignore rules and contribution rules** (S) · Depends on: T0.1
- Files: `.gitignore` (append), `CONTRIBUTING.md`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `tests/meta/test_repo_hygiene.py`.
- Work:
  - Append `/data/`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.db-journal`, `*.cbrnbak`, `*.qm`, `portable.ini` and `/scratch/` to `.gitignore`. Also append `*.sqlite3-journal`, `*.sqlite-journal`, `*-journal`, `*.before-restore-*`, `*.log.*`, `backups/`, `logs/`, `tmp/`, `prefs.json`, `selftest.json` and `location.json`.
  - `CONTRIBUTING.md` sets out the rules of §10.1 and §7: no real data in code, tests, issues or screenshots; no WHO-guide or internal-document text; no clinical content; the SPDX header; translations with every UI string; one task per commit; no source folder whose name an ignore rule matches (the hygiene test enforces it); and no committee answers in the repository — PLAN.md, the changelog, issues and pull requests record only the status of a question (open / answered and applied locally / answered and implemented in task Tn), never the content of an answer. Answers, thresholds, security rules, deployment constraints, retention rules and institution names live in a private document outside the repository, and real targets are entered in Settings and never become code defaults.
  - The pull-request template has a checklist for these rules, including the one about committee answers. The issue template warns against pasting real data.
- Accept, checked against `git ls-files`:
  - no tracked file matches a database, backup or compiled-catalogue pattern, and no tracked file is an SQLite or `.cbrnbak` file by magic bytes (`SQLite format 3\0`, `CBRNBAK1`), whatever its name;
  - no file under `src`, `tests`, `docs`, `packaging` or `scripts` is ignored (`git ls-files --others --ignored --exclude-standard`), except generated artefacts: `__pycache__`, tool caches (`.pytest_cache`, `.mypy_cache`, `.ruff_cache`) and compiled `*.qm`;
  - every tracked `.py` file starts with the SPDX line;
  - no tracked file is larger than 1 MB unless it is on an explicit allow-list.

  The test skips when not run inside a git work tree.
- Check: `uv run pytest tests/meta/test_repo_hygiene.py`

**T0.4 — Layering and forbidden-API guard tests** (S) · Depends on: T0.1
- Files: `tests/meta/test_forbidden_apis.py`, `tests/meta/_ast_rules.py`.
- Accept: an AST scan of `src/` fails on any of the following.
  - Imports of `socket`, `ssl`, `urllib`, `http`, `ftplib`, `smtplib`, `requests`, `httpx`, `webbrowser`, `PySide6.QtNetwork` or `PySide6.QtWebEngine*`; and also `asyncio`, `xmlrpc`, `imaplib`, `poplib`, `urllib3`, `subprocess`, `ctypes`, `PySide6.QtWebSockets`, and uses of `os.startfile` and `QDesktopServices`.
  - Calls to `date.today`, `datetime.now`, `datetime.utcnow` or `time.time` outside `clock.py`; and also `datetime.today`, `time.localtime`, `time.gmtime`, `time.time_ns`, `QDate.currentDate`, `QDateTime.currentDateTime`, `QDateTime.currentDateTimeUtc` and `QTime.currentTime`.
  - Matching is by attribute name, whatever the import alias.
  - Allowed exceptions: `os.startfile` and `QDesktopServices.openUrl` only inside `src/cbrn_dashboard/ui/shell/folders.py`, the one helper that accepts a local folder path (used by T7.4 "Open data folder"), which is the only file allowed to call them; `ctypes` only in the tests that read the version resource (T9.1); `subprocess` only in `scripts/` and tests.
  - Any PySide6 import in `domain/`, `services/`, `storage/`, `reports/model.py` or `reports/anonymise.py`.
  - Any `sqlite3` import in `ui/`.
  - Any import of `storage` or `services` from `domain/`.

  Each rule has a self-test on small fictitious snippets that it must catch.
- Check: `uv run pytest tests/meta/test_forbidden_apis.py`

**T0.5 — Data-location resolution** (M) · Depends on: T0.1
- Files: `src/cbrn_dashboard/paths.py`, `tests/test_paths.py`.
- Work:
  - Implement the D02 order: `--data-dir`, then `CBRN_DASHBOARD_DATA_DIR`, then `portable.ini` beside the executable, then the pointer file `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json` (written by T7.5), then `%LOCALAPPDATA%\cbrn-readiness-dashboard\`. The database file name is `cbrn-dashboard.sqlite3` inside the chosen folder.
  - Return a result holding the path, its source, a writable flag and a list of warnings: network path (UNC or a mapped network drive) and OneDrive-synced folder. OneDrive is detected from the prefixes in `OneDrive`, `OneDriveCommercial` and `OneDriveConsumer`, from the OneDrive account mount points read (read-only) from the registry, and from the cloud-placeholder attributes of the folder.
  - The writability probe, the network-drive lookup and the registry reader are injectable functions.
  - Create the folder if it is missing. Never fall back to another location silently.
  - Pure Python, no Qt.
- Accept:
  - every precedence branch resolves correctly, including the pointer file (and a missing or corrupt pointer file falling through to the default);
  - the portable marker is honoured for a simulated frozen executable;
  - UNC and OneDrive paths produce the matching warnings, including a OneDrive folder found only through a fake registry mount point and one found only through fake cloud-placeholder attributes;
  - a fake non-writable probe is reported as non-writable, not replaced by another location;
  - the real probe returns true for `tmp_path`.
- Check: `uv run pytest tests/test_paths.py`

**T0.6 — Translation framework and catalogue tests** (M) · Depends on: T0.1
- Files: `src/cbrn_dashboard/ui/shell/i18n.py`, `src/cbrn_dashboard/i18n/__init__.py`, `src/cbrn_dashboard/i18n/shell_pt_BR.ts`, `shell_en_US.ts`, `shell_es_ES.ts`, `scripts/i18n.py` (`update` and `compile` subcommands), `tests/conftest.py`, `tests/i18n/test_catalogues.py`, `tests/i18n/test_catalogues_in_sync.py`, `tests/i18n/test_translate_contexts.py`.
- Work:
  - The translator manager of §6: install and remove translators, load Qt base translations where present, set the default `QLocale`.
  - `scripts/i18n.py update` runs `pyside6-lupdate` with `-locations none`, so the `.ts` files do not churn.
  - A guard test over `src/` fails when the context argument of `QCoreApplication.translate` is not a string literal (`pyside6-lupdate` extracts only literals). A small test also checks the `self.tr()` inheritance pitfall of §6 and records whether it is real.
  - `tests/conftest.py` sets the offscreen platform before Qt is imported, points `CBRN_DASHBOARD_DATA_DIR` at a temporary folder for the whole session (autouse), compiles every `.ts` into a temporary `.qm` folder (session fixture), and provides the pseudo-locale catalogue builder.
- Accept:
  - checks 1–5 and 7 of §6 pass for the shell catalogue; check 6, the pseudo-locale walk, arrives with T1.9 (pages and the dialog registry);
  - the manager loads each language and translates a known shell string;
  - an unknown language code is rejected;
  - the context guard catches a constant or variable used as context in a fictitious snippet.
- Check: `uv run pytest tests/i18n`

**T0.7 — Application bootstrap, empty main window and self-test** (M) · Depends on: T0.5, T0.6
- Files: `src/cbrn_dashboard/cli.py`, `app.py`, `selftest.py`, `ui/shell/main_window.py`, `__main__.py` (update), `i18n/shell_*.ts` (update), `tests/test_cli.py`, `tests/ui/test_main_window.py`, `tests/test_selftest.py`.
- Work:
  - Command-line options `--data-dir`, `--lang {pt-BR,en-US,es-ES}`, `--self-test` and `--version`; `--demo` comes in T1.7.
  - The main window has a translated title, an empty navigation list, a Language menu with three entries, a status bar showing the data folder, and Quit.
  - The self-test is a registry of checks — Python, Qt, paths, i18n in three languages, main window — that writes `selftest.json` to the data folder and exits 0 or 1. The self-test never opens the real database: its checks work in a throwaway `tmp\selftest-*` folder under the resolved data folder, which is removed afterwards, and the only file it writes beside that folder is `selftest.json`.
- Accept:
  - The window opens offscreen with the translated title in each language.
  - Choosing a language in the menu retitles the window live.
  - The window closes without Qt warnings.
  - `main(["--self-test", "--data-dir", <tmp>])` returns 0, and the JSON lists every check as passed.
  - After a self-test run on a folder that already holds a fictitious database, that database is byte-identical, and no `tmp\selftest-*` folder remains.
  - An invalid option exits with code 2.
  - With no preference saved, the language is pt-BR.
- Check: `uv run pytest tests/test_cli.py tests/ui/test_main_window.py tests/test_selftest.py`

**T0.8 — CI workflow skeleton** (S) · Depends on: T0.2
- Files: `.github/workflows/ci.yml`, `tests/meta/test_workflows.py`.
- Work:
  - Triggers on push and pull request; `permissions: contents: read`; concurrency that cancels superseded runs.
  - Job `test` on a pinned Windows image, with checkout and setup-uv pinned to commit SHAs and uv's cache enabled.
  - Steps: `uv sync --locked --all-groups`, then `uv run pytest` with `QT_QPA_PLATFORM=offscreen`, then a coverage step with `--cov-fail-under=90` over `domain`, `storage` and `services`.
- Accept: the test parses the workflow text and checks that:
  - every `uses:` is pinned to a 40-character hex SHA;
  - the runner label is a pinned Windows image, not `-latest`;
  - the offscreen variable is set;
  - `--locked` is used;
  - permissions are read-only.

  A human also confirms that the first push produces a green run.
- Check: `uv run pytest tests/meta/test_workflows.py`

**T0.9 — Packaging spike: a one-folder build that passes the self-test** (M) · Depends on: T0.7, T0.8
- Files: `scripts/build_exe.py`, `src/cbrn_dashboard/resources/app.ico` (original artwork made for the project), `tests/packaging/test_build.py`, `.github/workflows/ci.yml` (add the `build` job).
- Work:
  - Drive PyInstaller through its Python API: onedir, windowed, no UPX, name `cbrn-dashboard`, the icon, and **all** `cbrn_dashboard` package data except `*.ts` as data: migration `.sql` files, resources, help and the compiled `.qm` files (from `scripts/i18n.py compile`), not only the icon and the `.qm` files.
  - Exclude `QtNetwork`, `QtWebEngine*`, `QtQml`, `QtQuick`, `Qt3D*`, `QtMultimedia`, `QtBluetooth`, `QtPositioning`, `QtSql`, `numpy`, `matplotlib` and `tkinter`. `--exclude-module` takes Python module names and may leave Qt DLLs behind, so after the build the script deletes the unwanted Qt DLLs and plugins from `_internal`.
  - Output and work folders are parameters.
  - The CI `build` job (it needs `test`) runs `uv run pytest -m packaging` and uploads the zipped folder as an artefact kept for 14 days.
- Accept:
  - the build succeeds into `tmp_path`;
  - `cbrn-dashboard.exe --self-test --data-dir <tmp>`, run offscreen, exits 0 with every check passed;
  - the bundle contains the three shell `.qm` files and Qt's offscreen platform plugin;
  - the bundle contains every non-`.ts` package-data file of the source tree (a generic comparison, not a hard-coded list), so `storage/migrations/0001_core.sql` is covered as soon as T1.3 adds it; T1.3's packaging check asserts it by name;
  - the test asserts on the files actually present in the bundle: no `Qt6Network.dll`, numpy, matplotlib or QtWebEngine, and none of the deleted Qt DLLs or plugins, and the self-test still passes without them;
  - the total size is printed.
- Check: `uv run pytest -m packaging tests/packaging/test_build.py`

#### Phase 1 — Foundations: storage, configuration, indicators, shell (MVP)

**T1.1 — Clock and date arithmetic** (S) · Depends on: T0.4
- Files: `src/cbrn_dashboard/clock.py`, `src/cbrn_dashboard/domain/dates.py`, `tests/domain/test_dates.py`.
- Accept:
  - a `Clock` interface with `SystemClock` and `FixedClock`; "today" and the day and month boundaries are the local calendar date, defined once in `clock.py`, while stored timestamps stay UTC (a `FixedClock` test shows a UTC time after midnight giving the previous local date, and the reverse);
  - adding months clamps to the month's end (31 January plus one month gives 28 or 29 February, leap years included);
  - the days between two dates are signed;
  - strict ISO date parsing rejects `2025-2-3`;
  - UTC timestamps are formatted with a trailing `Z`.
- Check: `uv run pytest tests/domain/test_dates.py`

**T1.2 — Database opening and SQLite version check** (S) · Depends on: T0.1
- Files: `src/cbrn_dashboard/storage/db.py`, `tests/storage/test_db.py`.
- Work:
  - `open_database(path, read_only=False)` applies the D06 settings: explicit transactions, foreign keys on, `journal_mode=DELETE`, `synchronous=FULL`, `secure_delete=ON`, and a busy timeout.
  - Read-only mode uses a `mode=ro` URI built with `Path.as_uri()`, or, for a UNC path, an equivalent URI with an empty authority (SQLite rejects a URI authority). Before opening, the start-up code tests that the database file itself is writable, not only its folder. A database with a hot journal cannot be opened read-only; this raises `HotJournalError`, which the shell shows as a translated explanation. In read-only mode, no log file and no preference file are written (T1.8, T1.5).
  - A `transaction()` context manager.
  - A start-up check for SQLite 3.37 or later, needed for `STRICT` tables.
- Accept:
  - foreign keys are enforced;
  - a read-only connection rejects writes with `ReadOnlyDatabaseError`, also for a path containing spaces and non-ASCII characters (the URI is built with `Path.as_uri()`);
  - a read-only open of a database with a hot journal raises `HotJournalError`;
  - a database file with the read-only attribute in a writable folder is detected as not writable;
  - a transaction commits on success and rolls back on an exception;
  - an injected older version number makes the check raise a clear error;
  - the pragmas read back with the expected values.
- Check: `uv run pytest tests/storage/test_db.py`

**T1.3 — Migration runner and core schema** (M) · Depends on: T1.2, T0.7
- Files: `storage/migrate.py`, `storage/migrations/__init__.py`, `storage/migrations/0001_core.sql` (§5.2, including the `change_log` triggers), `storage/migrations/README.md`, `selftest.py` (add a "database" check), `tests/storage/test_migrate.py`.
- Work: the runner follows D06. It does not use `executescript()`; it splits each file into statements (for example with `sqlite3.complete_statement`) and runs them with `execute()` inside one explicit `BEGIN IMMEDIATE … COMMIT`, sets `user_version` in the same transaction and rolls back on any error. A migration flagged as a table rebuild in its header comment runs with foreign keys off before `BEGIN`, `PRAGMA foreign_key_check` before `COMMIT`, and foreign keys back on afterwards.
- Accept:
  - A fresh database is brought to the latest `user_version`; running again changes nothing.
  - A database with a newer version raises `DatabaseTooNewError` and is left untouched.
  - A deliberately broken migration in a temporary migrations package rolls back and leaves the version unchanged. A migration that fails at its last statement leaves no table from its earlier statements.
  - The runner refuses to run when the available files are not contiguous from 0001, including when `user_version` is higher than the number of a missing file.
  - A non-empty database is copied with the backup API before migrating. The helper takes the database identity (real or demo) explicitly, so a demo database is backed up into `demo\backups\`, and it can be turned off for the migration of a temporary copy during restore (T7.3). T7.1 later moves this helper into `storage/backup.py`.
  - Migrations are loaded through `importlib.resources`.
  - The README reserves 0002 personnel, 0003 infrastructure, 0004 exercises, 0005 budget, 0006 indicator targets and 0007 snapshots only until v0.1.0, and states that every later migration is numbered max+1 at merge time.
  - The self-test "database" check asserts `user_version > 0` and that `change_log` exists.
  - The packaging check finds `0001_core.sql` in the bundle.
- Check: `uv run pytest tests/storage/test_migrate.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T1.4 — Repository helpers with the append-only change log** (M) · Depends on: T1.3, T1.1
- Files: `src/cbrn_dashboard/storage/repository.py`, `tests/storage/test_repository.py`.
- Accept:
  - The insert, update and delete helpers each write one `change_log` row per affected row in the same transaction. The row has the right `entity`, `entity_id` (or `entity_key` as JSON for a table without an integer id), `action`, `before_json` and `after_json`, the operator label, and a UTC time taken from the `Clock`.
  - Deleting a parent row writes one `delete` row for each cascaded child as well; the children are found through `PRAGMA foreign_key_list` before the delete, and a test with a fictitious two-level hierarchy checks the count.
  - For the personal free-text columns listed in §5.1, the log row records only that the column changed, not its old or new value; a test with a distinctive fictitious label finds it nowhere in `change_log`.
  - A rollback removes both the change and its log row.
  - A direct `UPDATE` or `DELETE` on `change_log` raises, because of the triggers (D05).
- Check: `uv run pytest tests/storage/test_repository.py`

**T1.5 — Readiness configuration, placeholders and UI preferences** (M) · Depends on: T1.3, T0.7
- Files: `domain/config.py`, `storage/settings_repo.py`, `src/cbrn_dashboard/prefs.py`, `app.py` (language from preferences), `tests/domain/test_config.py`, `tests/storage/test_settings_repo.py`, `tests/test_prefs.py`, `tests/meta/test_placeholders_documented.py`.
- Work:
  - `ReadinessConfig` holds:
    - P01–P09 with their `placeholder` flags (P08 is the `BUD_EXEC_RATE` pro-rating switch, P09 the backup-reminder age in days, default 30);
    - the A02 level-hierarchy switch (off);
    - the A05 "degraded counts as available" switch (off);
    - optional validity months per PPE level (A04, not set);
    - the default currency (A08, BRL);
    - the small-count threshold (A11, 5);
    - the institution and unit names (D18, empty);
    - the operator label (D05);
    - the handling notice of the internal report (empty by default).

    It is stored in the `setting` table, together with a per-database "confirmed" state for each placeholder (§3.5). The code-level `placeholder` flag is a constant of the release and is never changed at run time. Each value is marked in `domain/config.py` as either *local-only* (targets P03, institution and unit names, the report handling notice: no code default, flag never cleared in code, confirmed per installation only) or a *generic default* (§3.5).
  - `prefs.json` in the data folder holds the language, the "first-run notice shown" flag and the start-up summary toggle. It is written atomically. When the data folder is read-only, saving does not fail: the preferences are kept for the session only (§6).
- Accept:
  - the defaults and placeholder flags equal an explicit expected table kept in the test (not read from this plan), and a meta test checks that every flagged placeholder id appears in §3.5;
  - the local-only values (targets, institution and unit names, handling notice) have no code default other than empty or none, and are marked local-only;
  - invalid values (negative days, a threshold below 1) are rejected with error codes;
  - hard floors: a P05 below 12 characters and a P06 below 2 copies are rejected with error codes, whatever the caller;
  - the configuration round-trips through the database;
  - confirming a placeholder in Settings records the per-database confirmed state and leaves the code-level flag unchanged;
  - preferences round-trip, and a corrupt `prefs.json` falls back to the defaults with a warning;
  - with a read-only data folder, a preference change is kept for the session and no error is raised;
  - the language defaults to pt-BR and stays persisted after a switch.
- Check: `uv run pytest tests/domain/test_config.py tests/storage/test_settings_repo.py tests/test_prefs.py`

**T1.6 — Indicator framework** (M) · Depends on: T1.1
- Files: `src/cbrn_dashboard/domain/indicators.py`, `src/cbrn_dashboard/domain/registry.py`, `tests/domain/test_indicators.py`.
- Accept:
  - An indicator definition carries a code, module, unit kind (count, ratio, currency, days), direction and dimensions.
  - Evaluation gives OK, Warning or Critical, with inclusive boundaries documented and tested for both higher-is-better and lower-is-better indicators.
  - With no configured target the status is No target (D14, P03); a missing value gives No data.
  - Targets are keyed by (code, dimension).
  - The registry rejects duplicate codes and iterates in a stable order. Module providers are listed one per line in `domain/registry.py`.
- Check: `uv run pytest tests/domain/test_indicators.py`

**T1.7 — Demo-data framework and `--demo` mode** (S) · Depends on: T1.3, T0.7
- Files: `src/cbrn_dashboard/demo/__init__.py`, `cli.py` (`--demo`), `app.py`, `tests/demo/test_demo_framework.py`.
- Accept:
  - `--demo` opens `<data>\demo\demo.sqlite3`. The real database, `<data>\cbrn-dashboard.sqlite3`, is neither created nor modified (checked by its existence and modification time).
  - `app_meta.is_demo` is `1`. The demo flag of the application is read from `app_meta.is_demo`, not from the command-line flag, so a demo database opened any other way is still treated as demo (D25).
  - The demo database has its own `<data>\demo\backups\`: its pre-migration backup goes there, and nothing of it is written to `<data>\backups\`.
  - The generator is seeded and deterministic: two runs give identical rows.
  - Every generated identifier starts with `DEMO` (D25).
  - Module generators register with one line each.
- Check: `uv run pytest tests/demo/test_demo_framework.py`

**T1.8 — Logging and crash handling without record contents** (S) · Depends on: T0.5, T0.7, T1.4
- Files: `src/cbrn_dashboard/logging_setup.py`, `app.py` (exception hook), `tests/test_logging.py`.
- Accept:
  - A rotating log is kept at `<data>\logs\app.log` (1 MB × 3). In read-only mode the log stays in memory and no file is written.
  - The log formatter writes the exception type and the stack frames (file, line, function), never the exception message. An unhandled exception is reported through an injectable callback, which T1.9 wires to a translated error dialog that shows a code, not the message. Nothing is uploaded.
  - In a scenario that writes a record with a distinctive fictitious identifier through the T1.4 helpers, the identifier does not appear in the log (D22).
  - An exception raised with a message that contains a distinctive fictitious identifier leaves no trace of that identifier in the log, and the crash dialog shows a code without it.
- Check: `uv run pytest tests/test_logging.py`

**T1.9 — Shell: start-up sequence, registries, as-of date, read-only mode, banners and prompts** (M) · Depends on: T0.7, T1.5, T1.7, T1.1, T1.8
- Files: `app.py` (start-up sequence), `ui/shell/registry.py`, `ui/shell/context.py`, `ui/shell/prompts.py`, `ui/shell/banners.py`, `ui/shell/main_window.py` (update), `i18n/shell_*.ts` (update), `tests/ui/test_shell.py`, `tests/ui/test_no_hardcoded_strings.py`.
- Work:
  - T1.9 owns the start-up sequence in `app.py`: resolve the paths (T0.5), take a lock file in the data folder before opening the database (an exclusive OS file lock, so a crash leaves no stale lock; a second instance shows a translated message and exits; the lock is skipped in read-only mode), open and migrate the real database `<data>\cbrn-dashboard.sqlite3` (or the demo database, or open it read-only), build `AppContext`, then run the registered start-up hooks.
  - Clock sanity check at start-up: if the current UTC instant (`clock.py`) is earlier than the newest `change_log.at_utc` or than the build timestamp (UTC), a banner is shown and, for that session, the automatic snapshot and backup rotation hooks are skipped. "Today" for day and month boundaries stays the local calendar date.
  - Three one-line registries, each extended with one line per task:
    - start-up hooks (in `app.py`); each hook declares whether it runs in read-only mode and in demo mode;
    - settings sections: a small protocol (a key, the parent group such as Personnel or Backup, a title code and a widget factory) used by T2.4, T3.4, T4.5, T5.4, T7.4 and T8.7; T6.1 only renders them;
    - dialogs: each dialog registers a factory that builds it with fictitious data, so the pseudo-locale and accessibility walks cover dialogs as well as pages.
  - `AppContext` holds the services, the clock, the as-of date (default today, with a selector in the toolbar, D13), the read-only flag and the demo flag, and emits change signals.
  - A page registry, one line per module.
  - A prompts interface wrapping message boxes and file dialogs; tests substitute a fake. The T1.8 crash callback is wired to it.
  - A banner area for the demo banner (D25), the read-only banner, location warnings and the permanent preliminary notice (I06, P07).
  - The pseudo-locale walk (check 6 of §6) over every registered page and every registered dialog.
- Accept:
  - a page registered in the test appears in the navigation;
  - a settings section and a dialog registered in the test are returned by their registries, and a start-up hook registered in the test runs once, in order, and is skipped when it declares that it does not run in read-only or demo mode;
  - changing the as-of date emits exactly one signal;
  - read-only mode disables every action registered as an edit, and the instance lock is not taken;
  - while one instance holds the lock, a second start shows the translated message and exits without opening the database;
  - with a fake clock earlier than the newest `change_log` timestamp, the banner appears and the snapshot and rotation hooks do not run;
  - a database whose `app_meta.is_demo` is 1 shows the demo banner, whatever the command-line flag;
  - the preliminary notice is always visible;
  - the pseudo-locale walk passes for the shell (pages and the dialog registry).
- Check: `uv run pytest tests/ui/test_shell.py tests/ui/test_no_hardcoded_strings.py`

**T1.10 — Locale formatting and parsing** (S) · Depends on: T0.6
- Files: `src/cbrn_dashboard/ui/shell/formatting.py`, `tests/ui/test_formatting.py`.
- Work: the exact `QLocale` strings depend on the CLDR version inside the pinned Qt, so the expectations are regenerated deliberately on a Qt upgrade (es-ES may not group four-digit numbers). Locale-aware input widgets get `setLocale()` on a language change (§6).
- Accept:
  - The fixed date 2026-03-05 is shown as `05/03/2026` in pt-BR and es-ES and `03/05/2026` in en-US.
  - A number (1234.5), a percentage, and money in minor units for BRL and EUR are formatted to exact expected strings in all three locales, with non-breaking spaces written explicitly in the expectations.
  - User-entered numbers and amounts are parsed according to the locale and round-trip; ambiguous input is rejected with an error code.
- Check: `uv run pytest tests/ui/test_formatting.py`

#### Phase 2 — Personnel module (MVP)
This phase covers R07, R14–R16 and R36, and supplies the inputs for R25. It follows the module pattern of §10.2: T2.1 and T2.2 in parallel, then T2.3, then T2.4 and T2.5 in parallel.

**T2.1 — Personnel schema (migration 0002)** (S) · Depends on: T1.3
- Files: `storage/migrations/0002_personnel.sql`, `tests/storage/test_schema_personnel.py`.
- Work: create the tables `staff_member`, `ppe_certification`, `training_course`, `training_record` and `academic_degree` exactly as in §5.2.
- Accept:
  - The migration applies on top of 0001.
  - The database rejects a `ppe_level` other than A, B or C; a `valid_until` before `issued_on`; and an unknown degree `level` or `status`.
  - `identifier` is unique.
  - `staff_member`, `ppe_certification` and `training_record` have no `notes` column (D17); `no_renewal_from` is NULL by default; a `no_renewal_reason` outside `left_unit`, `role_change` and `other` is rejected.
  - The import natural keys are enforced: a second PPE qualification with the same staff member, level and `issued_on`; a second training record with the same staff member, course and `completed_on`; and a second degree with the same staff member, level, field and year (empty field and year included) are rejected.
  - Deleting a staff member deletes their PPE qualifications, training records and degrees.
  - A course that is in use cannot be deleted.
- Check: `uv run pytest tests/storage/test_schema_personnel.py`

**T2.2 — Personnel rules and indicators** (M) · Depends on: T1.1, T1.5, T1.6 · Parallel with: T2.1
- Files: `domain/personnel.py`, `domain/registry.py` (one line), `tests/domain/test_personnel.py`.
- Work: pure functions over plain data objects. Every function takes the as-of date *d*.
  - A person is active when `active_from` ≤ *d* and either `active_until` is empty or *d* ≤ `active_until`.
  - The PPE qualification rule is the one stated in A03, implemented once here and used by the indicators, the alerts (T6.2) and the lists: for a person, level and date *d*, the counting qualification is the one with the latest `valid_until` among those with `issued_on` ≤ *d* (ties: later `issued_on`, then higher id); it is valid when `valid_until` ≥ *d*.
  - A PPE qualification is "no renewal" on *d* when `no_renewal_from` is set and ≤ *d* (D24). It is "expiring" when it is the counting qualification, valid on *d*, has `valid_until` ≤ *d* + P01, and is not "no renewal" on *d*.
  - "Retraining needed" follows A03. The function returns the list of staff identifiers for the retraining and expiring views (R36).
  - Level hierarchy (A02):
    - with the switch off, levels are counted independently;
    - with it on, a qualification also counts for the levels mapped as covered by it in Settings. The mapping stays empty until Q2 is answered.
  - Validity pre-fill (A04): the proposed `valid_until` is `issued_on` plus the level's validity months when they are configured; otherwise there is no proposal.
  - Indicators, as defined in §5.4:
    - `PERS_CERT_VALID`, `PERS_CERT_EXPIRING` and `PERS_RETRAINING_NEEDED`, with dimension level;
    - `PERS_DEGREE`, with dimensions level and status;
    - `PERS_TRAINING_12M`.
  - `PERS_DEGREE` and the degree year: a completed degree whose recorded `year` is later than the year of *d* (the local date) is not counted on *d*. A completed degree without a year, and an in-progress degree whatever its year, is counted (QA finding P2-07).
- Accept: table-driven tests with `FixedClock` show that:
  - a PPE qualification whose `valid_until` equals the as-of date is still valid that day and counts as expiring;
  - inactive staff are never counted;
  - two qualifications at the same level count once;
  - a renewal case: a qualification issued after *d* does not hide the one that was valid on *d*, and the same person read at a later date counts the new qualification; the tie-break (same `valid_until`: later `issued_on`, then higher id) is tested;
  - qualifications with `no_renewal_from` ≤ *d* are left out of both "expiring" and "retraining needed", and one with `no_renewal_from` later than *d* is still included;
  - A02 behaves as specified both off and on (with a test mapping);
  - the training window is (*d* − 12 months, *d*];
  - degrees are counted per level and status;
  - a past as-of date gives the reading computed from the records as known today for that date (I03).
- Check: `uv run pytest tests/domain/test_personnel.py`

**T2.3 — Personnel repository and service** (M) · Depends on: T2.1, T2.2, T1.4
- Files: `storage/personnel_repo.py`, `services/personnel.py`, `tests/services/test_personnel_service.py`.
- Work:
  - Create, read, update and delete staff members, PPE qualifications, training records, courses and degrees through the T1.4 helpers.
  - "Deactivate" and "delete" are separate actions. Deactivate sets `active_until` and keeps the history. Delete is for entry mistakes and removes the dependent rows too, each logged (T1.4).
  - "Pseudonymise person" replaces the identifier with a random code, clears the label and each PPE qualification `reference`, and replaces each degree `field` with a per-row random code (so the unique index `academic_degree_key` still holds), keeping PPE qualifications, training records and degrees. The `change_log` rows record only that those columns changed (§5.1). Pseudonymising is irreversible.
  - Setting `no_renewal_from` on a PPE qualification takes an optional `no_renewal_reason` code (`left_unit`, `role_change`, `other`) instead of a note.
  - Validation returns error codes, never text: for example `VALID_UNTIL_BEFORE_ISSUED`, `DUPLICATE_IDENTIFIER`, `COURSE_IN_USE`. A course needs a pt-BR label (D16).
  - Summaries and lists for an as-of date are built by loading rows and calling the T2.2 functions.
- Accept:
  - every write produces its `change_log` row;
  - a deactivated person keeps their records and drops out of the counts after `active_until`;
  - deleting a person removes their dependent rows and writes one `delete` row for each of them;
  - after "pseudonymise person" the old identifier and label appear neither in the tables nor in `change_log`, the PPE qualifications and history remain, and the counts are unchanged;
  - a person with two degrees at the same level and year that differ only in `field` is pseudonymised without a uniqueness error;
  - on a fictitious fixture, the service summaries equal the domain results computed directly;
  - validation failures come back as codes.
- Check: `uv run pytest tests/services/test_personnel_service.py`

**T2.4 — Personnel page, dialogs and translations** (M) · Depends on: T2.3, T1.9, T1.10
- Files: `ui/personnel/page.py`, `ui/personnel/models.py`, `ui/personnel/dialogs.py`, `ui/personnel/labels.py`, `i18n/personnel_pt_BR.ts`, `i18n/personnel_en_US.ts`, `i18n/personnel_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_personnel_page.py`.
- Work:
  - A staff table with filters: active, level, needs retraining.
  - A detail view showing the person's PPE qualifications, training records and degrees.
  - One dialog per record type, with date pickers. The PPE qualification dialog pre-fills `valid_until` from A04 and offers "no renewal from" (a date) with the reason code. There are no free-text note fields. The remaining free-text fields (`label`, `reference`, degree `field`) show a hint: no names, health or contact data; the identifier field hints "a local code, not a service number".
  - Without configured validity months for the level (A04) there is no proposed `valid_until`: the field shows "Not set" (it is never pre-filled with the issue date), and saving is refused with `REQUIRED` on `valid_until` until a date is entered (QA finding P2-02).
  - A "Pseudonymise person" action, with a confirmation that says it cannot be undone.
  - Summary counts per level for the as-of date.
  - A course-list editor.
  - A module settings section — the A02 mapping, the A04 validity months and the course list (A09) — registered through the T1.9 settings-section registry, which T6.1 renders under Settings → Personnel.
  - Labels for PPE levels, degree levels and statuses, and error codes.
- Accept:
  - Adding a staff member and a PPE qualification through the dialogs makes the row appear, with dates formatted for the current language.
  - A `valid_until` before `issued_on` shows the translated error.
  - The hints are shown on the identifier, label, reference and field inputs, and no dialog has a notes field.
  - "Pseudonymise person" asks for confirmation; cancelling changes nothing; confirming replaces the identifier in the table.
  - Changing the as-of date updates the counts.
  - Read-only mode disables every edit.
  - The pseudo-locale walk passes on the page.
  - Every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_personnel_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T2.5 — Personnel demo generator** (S) · Depends on: T2.3, T1.7 · Parallel with: T2.4
- Files: `demo/personnel.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_personnel.py`.
- Accept: data is generated relative to the clock, and includes:
  - staff `DEMO-P001`, `DEMO-P002`, and so on;
  - at least one person in each state: valid, expiring within P01, expired, `no_renewal_from` set, inactive;
  - degrees at every level and status;
  - training records both inside and outside the 12-month window;
  - courses whose codes start with `DEMO`.

  The output is deterministic for a given seed. Every identifier starts with `DEMO` (D25). Values come from the seed, never from the thesis or from real records.
- Check: `uv run pytest tests/demo/test_demo_personnel.py`

#### Phase 3 — Infrastructure module (MVP)
This phase covers R08 and R17–R20, and supplies the inputs for R26 and R36.

**T3.1 — Infrastructure schema (migration 0003)** (S) · Depends on: T1.3
- Files: `storage/migrations/0003_infrastructure.sql`, `tests/storage/test_schema_infrastructure.py`.
- Work:
  - Create the tables `asset_type`, `asset`, `asset_status_event` and `maintenance_event` as in §5.2.
  - Seed the built-in asset types `bed`, `bay`, `neg_pressure_filtration` and `decon_tent`, which mirror the wording of L76 (D16). They have `built_in = 1`, empty label columns (their names come from `labels.py`) and an empty `default_maintenance_interval_days` (A06).
- Accept:
  - the four built-in types exist after the migration;
  - the database rejects a status other than the three of A05, and a second status event for the same asset on the same `effective_on`;
  - a maintenance `kind` outside the list is rejected;
  - a negative maintenance interval is rejected, and 0 is accepted (A06);
  - a second maintenance event with the same asset, `performed_on` and `kind` is rejected (import natural key, T8.4);
  - `tag` is unique;
  - a type in use cannot be deleted;
  - deleting an asset deletes its status and maintenance events.
- Check: `uv run pytest tests/storage/test_schema_infrastructure.py`

**T3.2 — Infrastructure rules and indicators** (M) · Depends on: T1.1, T1.5, T1.6 · Parallel with: T3.1
- Files: `domain/infrastructure.py`, `domain/registry.py` (one line), `tests/domain/test_infrastructure.py`.
- Work: pure functions, each taking the as-of date *d*.
  - An asset is in service when `in_service_from` ≤ *d* and either `in_service_until` is empty or *d* ≤ `in_service_until`.
  - Its status on *d* is that of the latest status event with `effective_on` ≤ *d*. With no event, the status is "unknown" (D26): not available, and flagged as a data-quality issue.
  - "Available" means operational. If the A05 switch is on, degraded also counts as available.
  - The due date follows A06:
    - first, the `next_due_on` of the latest maintenance on or before *d* that records one; it always wins, because it is a date the operator entered. Maintenance records without it (typically corrective or inspection) never reset the schedule;
    - otherwise, if the effective interval (the asset's own, or else its type's default) is 0, "no scheduled maintenance": no due date and no `MAINT_SCHEDULE_UNKNOWN` alert. An interval of 0 only switches off the interval-based fallback;
    - otherwise the latest preventive `performed_on` (or `in_service_from` when there is none) plus the interval;
    - otherwise "schedule unknown".
  - Maintenance recorded after *d* is ignored.
  - `INFRA_AVAILABLE` is a count of available units; the total of units in service is returned beside it as context (§5.4).
  - An asset is overdue when its due date is before *d*, and due soon when *d* ≤ due date ≤ *d* + P02.
  - The functions return lists by asset tag for the maintenance views (R36).
  - Indicators `INFRA_AVAILABLE` and `INFRA_MAINT_OVERDUE`, with dimension asset type (§5.4).
- Accept: table-driven tests with `FixedClock` cover:
  - status changes before, on and after *d*;
  - retired and not-yet-in-service assets being excluded;
  - the A05 switch both off and on;
  - every A06 branch (explicit next-due date, last preventive maintenance plus interval, in-service date plus interval, asset override versus type default, unknown);
  - a corrective or inspection record dated after a preventive one that recorded a next-due date does not move the due date, and a corrective record without any recorded next-due date does not reset the preventive-plus-interval schedule;
  - an interval of 0 with no recorded next-due date gives no due date, no overdue flag and no unknown-schedule flag, including when the type default is non-zero; an interval of 0 with a recorded `next_due_on` still gives that due date;
  - overdue and due-soon boundaries;
  - a past as-of date giving the reading computed from the records as known today for that date (I03).
- Check: `uv run pytest tests/domain/test_infrastructure.py`

**T3.3 — Infrastructure repository and service** (M) · Depends on: T3.1, T3.2, T1.4
- Files: `storage/infrastructure_repo.py`, `services/infrastructure.py`, `tests/services/test_infrastructure_service.py`.
- Work:
  - Creating an asset requires an initial status, which is recorded as a status event dated `in_service_from`.
  - Changing status adds a new event.
  - Recording maintenance adds a `maintenance_event`.
  - "Retire" (sets `in_service_until`) is separate from "delete" (for entry mistakes).
  - Asset types can be created and edited, with labels in three languages (only the pt-BR label is required for user-defined types, D16) and a default interval. Built-in types can be deactivated but not deleted.
  - Error codes include `DUPLICATE_TAG`, `STATUS_DATE_TAKEN`, `TYPE_IN_USE` and `BUILT_IN_TYPE`.
  - Deactivating an asset type only stops new assets of that type. `INFRA_AVAILABLE`, `INFRA_MAINT_OVERDUE` and the availability summary cover every active type plus every inactive type that still has an asset in service on the as-of date, so those assets keep counting; an inactive type without an asset in service on that date is left out (QA finding P3-01).
  - The only status event of an asset cannot be deleted (`ONLY_STATUS_EVENT`): without it the status would silently become "unknown" (D26), so the event is corrected instead. An asset whose status is still unknown on the as-of date (for example after `in_service_from` was moved before its first event) carries the flag "Status unknown (data quality)" in the asset table (T3.4) (QA finding P3-03).
- Accept:
  - every write produces its `change_log` row;
  - a new asset without an initial status is rejected;
  - deleting an asset writes a `delete` row for the asset and one for each of its status and maintenance events (T1.4);
  - on a fictitious fixture, the service availability and due lists equal the domain results;
  - deleting a built-in type returns `BUILT_IN_TYPE`.
- Check: `uv run pytest tests/services/test_infrastructure_service.py`

**T3.4 — Infrastructure page, dialogs and translations** (M) · Depends on: T3.3, T1.9, T1.10
- Files: `ui/infrastructure/page.py`, `ui/infrastructure/models.py`, `ui/infrastructure/dialogs.py`, `ui/infrastructure/labels.py`, `i18n/infrastructure_pt_BR.ts`, `i18n/infrastructure_en_US.ts`, `i18n/infrastructure_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_infrastructure_page.py`.
- Work:
  - An asset table grouped by type. For the as-of date it shows the current status, the last maintenance, the next due date and the overdue, due-soon and unknown-schedule flags.
  - Dialogs for an asset, a status change and a maintenance record, plus the history of each asset.
  - An availability summary per type.
  - A module settings section — the asset-type editor with labels in three languages and default intervals (A06), and the A05 switch — registered through the T1.9 settings-section registry, which T6.1 renders under Settings → Infrastructure.
  - Labels for the built-in types, statuses, maintenance kinds and error codes.
- Accept:
  - adding an asset and changing its status through the dialogs updates the table and the availability summary;
  - recording maintenance updates the next due date;
  - read-only mode disables every edit;
  - the pseudo-locale walk passes;
  - every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_infrastructure_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T3.5 — Infrastructure demo generator** (S) · Depends on: T3.3, T1.7 · Parallel with: T3.4
- Files: `demo/infrastructure.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_infrastructure.py`.
- Accept: the generated data includes:
  - assets `DEMO-A001`, and so on, of every built-in type;
  - one user-defined type whose code starts with `DEMO`;
  - every status;
  - at least one asset that is overdue, one due soon and one with an unknown schedule;
  - one retired asset.

  The output is deterministic for a given seed, every identifier starts with `DEMO`, and values come from the seed.
- Check: `uv run pytest tests/demo/test_demo_infrastructure.py`

#### Phase 4 — Exercises module (MVP)
This phase covers R09 and R21–R23, and supplies the editions and results used by R31. T4.2 depends only on T0.1 and can run at any time.

**T4.1 — Exercises schema (migration 0004)** (S) · Depends on: T1.3
- Files: `storage/migrations/0004_exercises.sql`, `tests/storage/test_schema_exercises.py`.
- Work: create the tables `exercise_edition`, `exercise_country`, `evaluation_metric` and `evaluation_result` as in §5.2. No metrics are seeded (A07).
- Accept:
  - the database rejects a `kind` outside `CBRAMED`, `EXBRAMED` and `OTHER` (A13); an `end_on` before `start_on`; a negative `participants` value; a country code whose length is not 2; and the same country twice in one edition;
  - `code` is unique;
  - a metric in use cannot be deleted;
  - deleting an edition deletes its countries and results.
- Check: `uv run pytest tests/storage/test_schema_exercises.py`

**T4.2 — Country reference data from CLDR** (S) · Depends on: T0.1
- Files: `scripts/gen_countries.py`, `src/cbrn_dashboard/resources/countries.json`, `src/cbrn_dashboard/resources/THIRD_PARTY_DATA.md`, `pyproject.toml` (a `tools` dependency group with Babel), `uv.lock`, `tests/test_countries.py`.
- Work:
  - Using Babel at development time only, take the country names from CLDR. CLDR has more two-letter region codes than ISO 3166-1 (for example `XK`, `AC`, `CP`, `DG`, `EA`, `IC`, `TA`, and deprecated codes), so the script keeps only the officially assigned ISO 3166-1 alpha-2 codes, taken from a list embedded in the script. Codes that are not countries (`EU`, `EZ`, `UN`, `QO`, `ZZ`) are left out the same way. Whether a non-ISO code is needed is Q7.
  - Each code gets its names in pt_BR, en_US and es_ES. The CLDR version is recorded in the JSON.
  - `THIRD_PARTY_DATA.md` carries the Unicode-3.0 notice.
- Accept:
  - codes are unique and consist of two uppercase letters;
  - the set of codes equals exactly the embedded list of officially assigned ISO 3166-1 alpha-2 codes, and none of `XK`, `AC`, `CP`, `DG`, `EA`, `IC`, `TA`, `EU`, `UN`, `ZZ` is present;
  - every code has three non-empty names;
  - the JSON records the CLDR version;
  - the notice file exists and names the Unicode licence;
  - Babel is not a runtime dependency (it is absent from `[project.dependencies]`);
  - the packaging check finds `countries.json` in the bundle.
- Check: `uv run pytest tests/test_countries.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T4.3 — Exercises rules and indicators** (M) · Depends on: T1.1, T1.6 · Parallel with: T4.1
- Files: `domain/exercises.py`, `domain/registry.py` (one line), `tests/domain/test_exercises.py`.
- Work: pure functions, each taking the as-of date *d*.
  - The history is sorted by `start_on`.
  - For each edition: participants and the number of countries represented.
  - For each kind: the latest edition whose `end_on` ≤ *d*. Editions after *d* are excluded.
  - Distinct countries over a period.
  - An evaluation summary per edition and metric, showing the value, the respondents, and the metric's scale and direction.
  - Indicators `EX_LAST_PARTICIPANTS`, `EX_LAST_COUNTRIES` and `EX_DAYS_SINCE_LAST`, with dimension kind (§5.4). `EX_DAYS_SINCE_LAST` is labelled in its definition as a design proposal pending Q1.
- Accept: table-driven tests cover:
  - the latest edition per kind both before and after a newer edition ends;
  - an empty `participants` value giving No data;
  - the country count;
  - days since the last edition at the boundary days;
  - future editions being ignored;
  - a past as-of date giving the reading computed from the records as known today for that date.
- Check: `uv run pytest tests/domain/test_exercises.py`

**T4.4 — Exercises repository and service** (M) · Depends on: T4.1, T4.2, T4.3, T1.4
- Files: `storage/exercises_repo.py`, `services/exercises.py`, `tests/services/test_exercises_service.py`.
- Work:
  - Editions can be created, edited and deleted, together with their country lists, results and metrics (labels in three languages, of which only pt-BR is required, D16; unit, scale, direction).
  - Country codes are checked against `countries.json`, loaded with `importlib.resources`.
  - A result is checked against its metric's scale.
  - Error codes include `DUPLICATE_CODE`, `UNKNOWN_COUNTRY`, `VALUE_OUT_OF_SCALE` and `METRIC_IN_USE`.
  - Once a result uses a metric, its code (`CODE_IMMUTABLE`, §5.1), unit (`UNIT_IMMUTABLE`) and direction (`DIRECTION_IMMUTABLE`) are frozen, and its scale can be changed only to one that still contains every stored result of the metric (`SCALE_EXCLUDES_RESULTS`) (QA finding P4-01).
- Accept:
  - every write produces its `change_log` row;
  - an unknown country code and an out-of-scale value are rejected with their codes;
  - on a fictitious fixture, the service history and indicator inputs equal the domain results.
- Check: `uv run pytest tests/services/test_exercises_service.py`

**T4.5 — Exercises page, dialogs and translations** (M) · Depends on: T4.4, T1.9, T1.10
- Files: `ui/exercises/page.py`, `ui/exercises/models.py`, `ui/exercises/dialogs.py`, `ui/exercises/labels.py`, `i18n/exercises_pt_BR.ts`, `i18n/exercises_en_US.ts`, `i18n/exercises_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_exercises_page.py`.
- Work:
  - An editions table with kind, dates, participants and number of countries, filterable by kind.
  - An edition dialog with a searchable multi-select country picker. Country names are shown and sorted in the current language, read from `countries.json`.
  - An evaluation-results table per edition.
  - A module settings section — the metric editor (A07) — registered through the T1.9 settings-section registry, which T6.1 renders under Settings → Exercises.
  - Labels for kinds and error codes.
- Accept:
  - adding an edition with countries and a result through the dialogs updates the table;
  - the country picker shows the localized name in each language;
  - read-only mode disables every edit;
  - the pseudo-locale walk passes;
  - every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_exercises_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T4.6 — Exercises demo generator** (S) · Depends on: T4.4, T1.7 · Parallel with: T4.5
- Files: `demo/exercises.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_exercises.py`.
- Accept: the generated data includes:
  - editions `DEMO-EX-01`, and so on, of every kind, with titles that start with "DEMO";
  - participant counts and country lists drawn from the seed — never copied from the thesis tables;
  - one edition with no participant count;
  - one future edition;
  - two metrics whose codes start with `DEMO`, with results for the past editions.

  The output is deterministic for a given seed, and every identifier starts with `DEMO`.
- Check: `uv run pytest tests/demo/test_demo_exercises.py`

#### Phase 5 — Budget module (MVP)
This phase covers R10, R24 and R36.

**T5.1 — Budget schema (migration 0005)** (S) · Depends on: T1.3
- Files: `storage/migrations/0005_budget.sql`, `tests/storage/test_schema_budget.py`.
- Work:
  - Create the tables `funding_source`, `budget_entry` and `budget_execution` as in §5.2.
  - Seed the built-in sources `DIRSA` and `OPCW_TRUST_FUND`, as named in L80 (D16). They have `built_in = 1` and empty label columns (their names come from `labels.py`). Note: the `OPCW_TRUST_FUND` seed is superseded by migration 0008 (`0008_budget_sources_r24.sql`, R24 revised in thesis commit f8b1d65): the built-in sources are now `DIRSA` and `COMAER`, and an `OPCW_TRUST_FUND` that has entries is kept as an inactive user-defined source.
- Accept:
  - both built-in sources exist after the migration;
  - a `currency` whose length is not 3 is rejected;
  - a second entry with the same fiscal year, source, currency and description (an empty description being `''`) is rejected (import natural key, T8.4);
  - a source in use cannot be deleted;
  - `budget_entry` has no `executed_minor` column; a `budget_execution` row with a negative amount is rejected, and a second row with the same entry, `executed_on` and amount is rejected (import natural key, T8.4);
  - deleting an entry deletes its execution rows.
- Check: `uv run pytest tests/storage/test_schema_budget.py`

**T5.2 — Budget rules and indicator** (S) · Depends on: T1.1, T1.6 · Parallel with: T5.1
- Files: `domain/budget.py`, `domain/registry.py` (one line), `tests/domain/test_budget.py`.
- Work: pure functions.
  - Totals are computed per (`fiscal_year`, source, currency). Allocated is the sum of the entered amounts, or "missing" when every amount is empty. Executed is the sum of the `budget_execution` amounts dated on or before the as-of date (A08).
  - Execution rate = executed ÷ allocated. It is No data when allocated is missing or zero.
  - Status of `BUD_EXEC_RATE`: when P08 is on, the rate is compared with the target multiplied by the elapsed fraction of the fiscal year (day of the year ÷ days in the year, linear pro-rating), so a year-end target is not Critical every January.
  - Only currencies of the allow-list (BRL, USD, EUR to start) with their decimal places are valid (D15).
  - Amounts are never added across currencies (D15).
  - The fiscal year of a date is its calendar year (A08).
  - A multi-year table supports budget planning (R36).
  - Indicator `BUD_EXEC_RATE`, with dimensions source and currency, for the fiscal year of the as-of date (§5.4).
- Accept: table-driven tests cover:
  - totals across several entries;
  - executed amounts read as of different dates in one year (rows dated after the as-of date are ignored);
  - a rate with zero and with missing allocated amounts;
  - the pro-rated status: with a year-end target and the same rate, the status differs between 15 January and 15 December, and with P08 off the target is used unchanged;
  - two currencies kept apart;
  - the fiscal year at the 31 December / 1 January boundary;
  - integer minor-unit arithmetic with no floating-point error in the totals.
- Check: `uv run pytest tests/domain/test_budget.py`

**T5.3 — Budget repository and service** (S) · Depends on: T5.1, T5.2, T1.4, T1.5
- Files: `storage/budget_repo.py`, `services/budget.py`, `tests/services/test_budget_service.py`, `PLAN.md` (§3.4 D27, only if the rule is refined).
- Work:
  - Budget entries can be created, edited and deleted, and each entry has dated execution rows that can be added, edited and deleted (a delete of an entry logs its execution rows, T1.4). Funding sources can be created and edited with labels in three languages (only pt-BR is required for user-defined sources, D16). Built-in sources can be deactivated but not deleted.
  - The service works in minor units only; parsing the amounts users type is the UI's job (T1.10).
  - Negative amounts are rejected (design decision D27, §3.4): corrections are made by editing the entry, and every edit is recorded in `change_log`.
  - Error codes include `NEGATIVE_AMOUNT`, `INVALID_CURRENCY` (a currency outside the allow-list of D15), `SOURCE_IN_USE` and `BUILT_IN_SOURCE`.
  - An entry with execution rows cannot change currency (`CURRENCY_IN_USE`; D15, no conversion), and its fiscal year can change only to one that contains the date of every row (`EXECUTION_OUTSIDE_FISCAL_YEAR` on `fiscal_year`). The date of an execution row must lie in the fiscal year of its entry when the row is added or edited (`EXECUTION_OUTSIDE_FISCAL_YEAR` on `executed_on`, A08); the CSV import adds rows through the same service call, so it is refused there too (T8.4). Rows that got into the database another way are still reported by `data_quality()` (QA findings P5-01, P5-02).
  - Stored amounts (allocated and executed) are at most `MAX_MINOR` = 2**53 − 1 minor units, else `INVALID_AMOUNT`: the largest integer a `float` holds exactly, because the indicator context carries amounts as floats; the database itself could hold up to 2**63 − 1 (QA finding P5-07).
- Accept:
  - every write produces its `change_log` row;
  - each invalid case returns its code, including a currency outside the allow-list;
  - deleting an entry writes a `delete` row for it and for each of its execution rows;
  - on a fictitious fixture, the service totals equal the domain results;
  - new entries use the configured default currency (A08).
- Check: `uv run pytest tests/services/test_budget_service.py`

**T5.4 — Budget page, dialogs and translations** (M) · Depends on: T5.3, T1.9, T1.10
- Files: `ui/budget/page.py`, `ui/budget/models.py`, `ui/budget/dialogs.py`, `ui/budget/labels.py`, `i18n/budget_pt_BR.ts`, `i18n/budget_en_US.ts`, `i18n/budget_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_budget_page.py`.
- Work:
  - A year selector that defaults to the as-of date's fiscal year.
  - A summary table per source and currency, showing allocated, executed (as of the as-of date) and execution rate.
  - A list of entries, each with its dated execution rows.
  - An entry dialog that takes the amount typed in the locale's format, and an execution dialog (date and amount).
  - A module settings section — the funding-source editor, the default currency (A08) and the P08 pro-rating switch — registered through the T1.9 settings-section registry, which T6.1 renders under Settings → Budget.
  - Labels for the built-in sources and the error codes.
  - The multi-year planning table (R36) is a domain and service function (`multi_year_table` in `domain/budget.py` and `services/budget.py`, T5.2). The Budget page does not show it; add a UI task if the committee wants a multi-year view (QA finding P5-05).
- Accept:
  - an amount typed as `1.234,56` in pt-BR or es-ES, or as `1,234.56` in en-US, is stored as 123456 minor units and shown back in the locale's format;
  - the summary updates after each edit, and changing the as-of date changes the executed amount;
  - two currencies appear on separate rows;
  - read-only mode disables every edit;
  - the pseudo-locale walk passes;
  - every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_budget_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T5.5 — Budget demo generator** (S) · Depends on: T5.3, T1.7 · Parallel with: T5.4
- Files: `demo/budget.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_budget.py`.
- Accept: the generated data includes:
  - entries for several fiscal years for both built-in sources, each with several dated execution rows spread over the year;
  - one user-defined source whose code starts with `DEMO`;
  - a second currency, to exercise D15;
  - one entry with no allocated amount, to give the No data case;
  - descriptions that start with "DEMO".

  Amounts come from the seed and are clearly fictitious. The output is deterministic for a given seed.
- Check: `uv run pytest tests/demo/test_demo_budget.py`

#### Phase 6 — Indicators, alerts and dashboard (MVP)
This phase covers R01, R05, R06, R25–R27 and R36. It starts once Phases 2–5 have merged. The domain part of T6.2 may start as soon as T2.2 and T3.2 exist.

**T6.1 — Indicator targets (migration 0006) and the Settings page** (M) · Depends on: T1.6, T1.9, T2.4, T3.4, T4.5, T5.4
- Files: `storage/migrations/0006_indicator_targets.sql`, `storage/targets_repo.py`, `services/indicators.py`, `ui/settings/page.py`, `ui/settings/labels.py`, `i18n/settings_pt_BR.ts`, `i18n/settings_en_US.ts`, `i18n/settings_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/services/test_indicator_service.py`, `tests/ui/test_settings_page.py`.
- Work:
  - Create the `indicator_target` table (§5.2).
  - `services/indicators.py` evaluates every registered indicator for an as-of date, using the configuration (T1.5), the stored targets and each module's inputs.
  - The Settings page has these sections:
    - *General:* language, operator label, institution and unit names (D18).
    - *Alerts:* P01 and P02.
    - *Targets:* P03. Warning and critical values per indicator and dimension, with an enable switch.
    - The module sections registered by T2.4, T3.4, T4.5 and T5.4 through the T1.9 settings-section registry, rendered under Personnel, Infrastructure, Exercises and Budget.
    - Further sections registered by later tasks (T7.4 Backup, T8.7 Reports and Snapshots) in the same registry, one line each. T6.1 only renders what the registry holds.
  - Every placeholder value shows the "placeholder — to be confirmed" badge (§3.5).
  - A changed value confirms its placeholder in the same transaction as the change: `ConfigService.save` confirms the placeholder of every field it changed whose badge is due, and `set_target` / `set_target_enabled` confirm P03 when called with `confirm_placeholder`. A failing confirmation rolls the whole save back; a save that changes nothing confirms nothing (QA findings P6-03, P6-04).
  - Ratio indicators (unit `RATIO`; today only `BUD_EXEC_RATE`) have their thresholds typed and shown as percentages and stored as ratios (90 → 0.9); the Alerts page shows their values and thresholds as percentages too (T6.3). The service refuses a ratio threshold below 0 or above `MAX_RATIO_TARGET` = 10.0 (1000 %) with `TARGET_OUT_OF_RANGE`, which catches "90" stored as 9000 % (QA finding P6-02).
  - The targets table has a "Use" column: a target whose dimension has no value on the as-of date (`known_dimensions`) is marked "Not in use"; the column follows the as-of date (QA finding P6-09).
  - A stored setting that cannot be read (`CORRUPT_SETTING`) is shown as a translated message instead of an error: on the Dashboard (T6.5) and Alerts (T6.3) pages in place of their content, in the General, Alerts and Targets sections of Settings, and in the module sections (the Personnel and Infrastructure sections show it and switch their rule inputs off). **Open (QA finding P6-01):** there is no action yet to reset one unreadable setting; the message is all the operator gets. It would need a `ConfigService.reset(field)` that deletes the stored row and un-confirms its placeholder in one transaction written to `change_log`, and a UI action that offers it.
- Accept:
  - targets round-trip and every change writes a `change_log` row;
  - targets in the wrong order for the indicator's direction are rejected with `TARGET_ORDER`;
  - an indicator without a target evaluates to No target, and a disabled target behaves as if absent;
  - the placeholder badge shows until the value is confirmed or changed, and confirming hides it on this database; the code-level flag in `domain/config.py` is unchanged (§3.5);
  - the four module sections are present;
  - read-only mode disables every edit;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/services/test_indicator_service.py tests/ui/test_settings_page.py tests/ui/test_no_hardcoded_strings.py`

**T6.2 — Alert rules** (M) · Depends on: T2.2, T3.2, T1.6 for the domain part; T2.3, T3.3 and T6.1 for the service part
- Files: `domain/alerts.py`, `services/alerts.py`, `tests/domain/test_alerts.py`, `tests/services/test_alerts_service.py`.
- Work:
  - Pure rules that produce the alert kinds of §5.5 — `CERT_EXPIRED`, `CERT_EXPIRING`, `MAINT_OVERDUE`, `MAINT_DUE_SOON`, `MAINT_SCHEDULE_UNKNOWN`, `INDICATOR_WARNING`, `INDICATOR_CRITICAL` — with the severities of §5.5.
  - Each alert carries its kind, severity, module, subject reference (staff identifier, asset tag, or indicator code and dimension), due date and days remaining.
  - The service gathers the inputs from the module services and from `services/indicators.py`.
- Accept: fixtures with `FixedClock` show that:
  - every kind is produced, with its severity;
  - alerts are sorted by severity, then by due date;
  - there is one PPE qualification alert per person and level, and one maintenance alert per asset;
  - the PPE qualification alerts use the PPE qualification rule of A03 (one definition, T2.2): a qualification issued after the as-of date does not hide the one valid on it;
  - `no_renewal_from` on or before the as-of date suppresses PPE qualification alerts (D24), and a later date does not;
  - `MAINT_SCHEDULE_UNKNOWN` is not raised for an interval of 0 with no recorded next-due date (A06);
  - disabled or absent targets produce no indicator alerts;
  - inactive staff and retired assets produce no alerts;
  - a past as-of date gives the alerts of that date.
- Check: `uv run pytest tests/domain/test_alerts.py tests/services/test_alerts_service.py`

**T6.3 — Alerts page and translated alert texts** (M) · Depends on: T6.2, T1.9, T1.10
- Files: `ui/alerts/page.py`, `ui/alerts/models.py`, `ui/alerts/labels.py`, `i18n/alerts_pt_BR.ts`, `i18n/alerts_en_US.ts`, `i18n/alerts_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_alerts_page.py`, `tests/ui/test_alert_labels.py`.
- Work:
  - The page lists the alerts for the as-of date, showing severity as text and icon, the module, the subject, the due date and a localized message. It can be filtered by module and severity.
  - Activating an alert opens the page of the record it refers to, found through the registry.
  - Messages are built from the alert's codes and parameters, with `%n` plural forms.
  - The Subject column shows the subject reference of T6.2 as data, unchanged: for an indicator alert its code and dimension (`CODE (dimension)`). The message is translated and names the indicator in words, with its dimension in words (QA finding P6-08).
- Accept:
  - every alert kind, in each of the three languages, gives a non-empty message with every placeholder filled;
  - plural forms are correct for 1 and for 2 days;
  - the filters work;
  - activating an alert switches to the right page;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_alerts_page.py tests/ui/test_alert_labels.py tests/ui/test_no_hardcoded_strings.py`

**T6.4 — Chart adapter (Qt Charts)** (S) · Depends on: T1.9
- Files: `ui/shell/charts.py`, `selftest.py` (add the "chart" check), `i18n/shell_pt_BR.ts`, `i18n/shell_en_US.ts`, `i18n/shell_es_ES.ts`, `pyproject.toml` (`qt_log_ignore`, only if Qt Charts emits a deprecation warning), `tests/ui/test_charts.py`.
- Work:
  - Build bar and grouped-bar charts from plain chart data (categories, series, values, unit).
  - Render a chart to an image, for PDFs.
  - Use one colour-blind-safe palette (Okabe–Ito), defined as a constant.
  - With no data, show a translated "No data" text instead of an empty chart.
  - No module outside this file imports Qt Charts (D08).
  - Qt Charts is deprecated since Qt 6.10. If it emits a deprecation warning at runtime, the warning is added to `qt_log_ignore` by exact text, with a comment.
- Accept:
  - the built chart's categories, series and values equal the input;
  - rendering offscreen gives a non-empty image of the requested size;
  - empty input gives the "No data" text;
  - the self-test "chart" check passes;
  - an AST check in the test confirms that `PySide6.QtCharts` is imported only in `ui/shell/charts.py`.

  No pixel comparisons are made.
- Check: `uv run pytest tests/ui/test_charts.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T6.5 — Dashboard service and overview page** (M) · Depends on: T6.1, T6.2, T6.4
- Files: `services/dashboard.py`, `ui/dashboard/page.py`, `ui/dashboard/models.py`, `ui/dashboard/labels.py`, `i18n/dashboard_pt_BR.ts`, `i18n/dashboard_en_US.ts`, `i18n/dashboard_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/services/test_dashboard_service.py`, `tests/ui/test_dashboard_page.py`.
- Work:
  - A Qt-free `DashboardData` for an as-of date holds:
    - one tile per indicator and dimension, with its unit (§5.4), value, status and target (`INFRA_AVAILABLE` also shows the in-service total as context);
    - alert counts by severity;
    - chart data: staff with a valid PPE qualification per level; availability per asset type; participants and countries per edition; allocated versus executed per (source, currency) for the fiscal year, drawn as one chart per currency with a category per source, so currencies are never mixed (D15).
  - The page shows the tiles, the charts and the alert counts. It is the default page at start-up.
  - Status follows D23: a text label plus an icon plus a colour from the colour-blind-safe palette, never colour alone.
  - Every chart has a "show as table" toggle.
- Accept:
  - on a seeded fictitious database with `FixedClock`, `DashboardData` equals the expected values and statuses (checked without widgets);
  - every tile shows its status as text;
  - each chart's table view contains exactly the chart's values;
  - changing the as-of date updates the tiles, charts and counts;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/services/test_dashboard_service.py tests/ui/test_dashboard_page.py tests/ui/test_no_hardcoded_strings.py`

**T6.6 — Start-up alert summary and status-bar badge** (S) · Depends on: T6.3, T1.5
- Files: `ui/shell/main_window.py`, `ui/shell/banners.py`, `i18n/shell_pt_BR.ts`, `i18n/shell_en_US.ts`, `i18n/shell_es_ES.ts`, `tests/ui/test_startup_summary.py`.
- Work:
  - A status-bar badge shows the alert counts by severity.
  - At start-up, if warning or critical alerts exist and the start-up summary preference (T1.5) is on, a summary banner appears with a button that opens the Alerts page. The preference defaults to on. Info-level alerts never trigger the summary; they count only in the badge and on the Alerts page.
  - The counts are refreshed whenever the as-of date or the data changes.
- Accept:
  - with warning or critical alerts, the badge and summary appear, and the button opens the Alerts page;
  - with only info-level alerts, the badge shows them but no summary appears;
  - with no alerts, no summary appears;
  - with the preference off, no summary appears but the badge stays;
  - the counts update after the as-of date changes and after a data change (R05).
- Check: `uv run pytest tests/ui/test_startup_summary.py`

#### Phase 7 — Backup, restore and data protection (MVP)
This phase covers I02, R33 and D02–D04. Its first task, T7.1, follows T1.9, the last task of Phase 1; T7.5 also needs T7.2. It needs nothing from Phases 2–6, so it runs in parallel with them.

**T7.1 — Consistent local backups and rotation** (M) · Depends on: T1.3, T1.5, T1.1, T1.9
- Files: `storage/backup.py`, `services/backup.py`, `storage/migrate.py` (switch to the shared helper), `app.py` (one start-up hook line), `tests/storage/test_backup.py`.
- Work:
  - Copy the database (`<data>\cbrn-dashboard.sqlite3`) with SQLite's online backup API into `<data>\backups\`; the demo database goes to `<data>\demo\backups\`. The helper takes the database identity (real or demo) explicitly. File names carry a UTC timestamp and the schema version.
  - Make a daily backup at the first start of each day (the local calendar date of `clock.py`).
  - The pre-migration backup from T1.3 moves to this helper and has its own pool.
  - Rotation: the daily pool keeps the newest P06 copies (7); the pre-migration pool keeps the last 3 and is never rotated out by daily backups; `.before-restore-*` safety copies (T7.3) are rotated too, keeping the last 2.
  - Each new copy passes `PRAGMA quick_check` before any older copy is deleted, and the newest copy that passed is never deleted. When the clock sanity check of T1.9 has failed, rotation is skipped for the session.
  - A suspect clock skips the rotation of all three pools, not only the daily one: the pre-migration pool (the start-up asks `clock_is_suspect` on the opened database before it migrates, because the session's own clock check runs later) and the before-restore pool (T7.3). The copy itself is still made; only older copies are kept (QA finding P7-04).
- Accept:
  - a copy taken while another connection holds an open write transaction still passes `PRAGMA integrity_check` and contains only committed data;
  - the daily backup is made once per day, however many times the app starts; its start-up hook is skipped in read-only mode and in demo mode;
  - the pre-migration backup goes through the same helper;
  - daily rotation keeps exactly P06 files and deletes the oldest; many daily backups do not remove any of the 3 pre-migration copies; the `.before-restore-*` pool keeps 2;
  - a new copy that fails `quick_check` (injected) is not counted, and no older copy is deleted because of it; the newest copy that passed is never deleted;
  - a demo database's backups appear only under `demo\backups\`;
  - nothing is written outside the data folder.
- Check: `uv run pytest tests/storage/test_backup.py`

**T7.2 — Encrypted backup container** (M) · Depends on: T7.1
- Files: `pyproject.toml` (add `cryptography` as a runtime dependency), `uv.lock`, `storage/crypto_backup.py`, `selftest.py` (add the "encrypted backup" check), `tests/storage/test_crypto_backup.py`.
- Work:
  - The `.cbrnbak` format of D04:
    - a header with magic `CBRNBAK1`, the format version, the scrypt parameters (n = 2^17, r = 8, p = 1), a random salt, the app version and the schema version;
    - the header HMAC-SHA256;
    - a Fernet token holding the bytes of a consistent copy made with the T7.1 helper;
    - at the end, an unkeyed SHA-256 of everything before it.
  - The key material is derived with the standard library's `hashlib.scrypt` with an explicit `maxmem`: 64 bytes, of which 32 are the Fernet key and 32 the HMAC key. The reader accepts only scrypt parameter sets from a short allow-list, so a crafted header cannot force a long derivation.
  - Check order and errors: bad magic or trailing checksum → `CorruptBackupError`; unknown format version → `BackupTooNewError`; scrypt parameters outside the allow-list → `CorruptBackupError`, before any key derivation; header HMAC mismatch → `WrongPassphraseError`; a Fernet failure after that → `CorruptBackupError`.
  - The schema version that drives migration is the restored database's own `user_version`; the copy in the header is informational.
  - The service enforces the minimum passphrase length P05 (12 characters at least) and a small strength rule: not on a short blocklist, and a minimum number of distinct characters.
  - It records the time of the last successful backup for the reminder (P09).
  - The encrypted file is written beside the target under a staging name (`<target>.new`), read back with the same passphrase and compared with the snapshot, and only then moved onto the target, so a failed write (`BACKUP_WRITE_FAILED`) or a failed read-back (`BACKUP_VERIFY_FAILED`) leaves an earlier backup of that name as it was. When `.cbrnbak` is appended to the chosen name, the save dialog never saw the final name, so an existing file of that name is refused (`BACKUP_TARGET_EXISTS`) unless the user agreed to replace it; T7.4 asks first (QA finding P7-10).
- Accept:
  - a round trip returns a database identical to the source;
  - a wrong passphrase (header intact) raises `WrongPassphraseError`;
  - a flipped byte in the body, a truncated file, or a wrong magic raises `CorruptBackupError`; a flipped byte in the salt, with the trailing checksum recomputed, raises `WrongPassphraseError`;
  - an unknown format version raises `BackupTooNewError`;
  - a header with scrypt parameters outside the allow-list raises `CorruptBackupError`, checked after the format version and before any key derivation;
  - two backups of the same database differ, because each has its own salt;
  - a passphrase shorter than P05, one on the blocklist, and one with too few distinct characters are each rejected;
  - the passphrase bytes appear neither in the output file nor anywhere in the data folder;
  - the self-test "encrypted backup" check passes.
- Check: `uv run pytest tests/storage/test_crypto_backup.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T7.3 — Restore service** (M) · Depends on: T7.2, T1.4
- Files: `services/restore.py`, `app.py` (empty `<data>\tmp\` at start-up), `tests/services/test_restore.py`.
- Work: the restore sequence of D04. It is not called atomic: it copies, it does not swap files.
  1. Decrypt only into `<data>\tmp\`.
  2. Run `integrity_check`.
  3. Refuse a backup whose `app_meta.is_demo` differs from the open database's (error code `DEMO_MISMATCH`).
  4. Check the schema version (the restored database's own `user_version`).
  5. Migrate the temporary copy if it is older, with the pre-migration backup turned off (T1.3 helper) so no plaintext copy is written outside `tmp\`.
  6. Close every other connection and assert that no `-journal` file exists.
  7. Keep a safety copy first, by copying: `<db>.before-restore-<UTC timestamp>` (rotated, T7.1).
  8. Copy the validated temporary database into the live one with SQLite's backup API (no rename).
  9. Reopen.
  10. Write a `change_log` row with action `restore` in the restored database; it names the safety copy.
  - When the copy fails and putting the safety copy back also fails (or the put-back database fails its integrity check), the error is `RESTORE_ROLLBACK_FAILED` instead of `RESTORE_COPY_FAILED`; it carries the file name (never the path) of the safety copy, and the message names that file. While the live database fails its own integrity check (looked at before the safety copy is made) the before-restore pool is not rotated, so later attempts never push out the good safety copy of an earlier one; with a suspect clock it is not rotated either (T7.1) (QA findings P7-01, P7-04).
  - `LIVE_UNREADABLE`: the live database cannot be read for the demo/real check, so the restore stops before anything is changed (QA finding P7-13).
  - The connection to the decrypted temporary database sets `PRAGMA temp_store=MEMORY`, so SQLite's statement journals and sort spills during the integrity check or the migration stay in memory instead of the OS temp folder; a `<data>\tmp\` that is a link is refused with `TEMP_FILE_FAILED` (QA finding P7-03).
- Accept:
  - a backup made with an older schema is restored and migrated, and no pre-migration backup is written during that migration;
  - a restored database whose own `user_version` is newer than the app raises `BackupTooNewError`;
  - a wrong passphrase, a corrupt file, a failed integrity check, a too-new schema or a demo/real mismatch (`DEMO_MISMATCH`) each leave the current database byte-identical;
  - a failure injected during the copy step (the failure cases are tested against this mechanism), a leftover `-journal` file and a second open connection each stop the restore with the current database untouched;
  - the safety copy exists after a successful restore, and the `restore` row names it;
  - the decrypted temporary file is created only inside `<data>\tmp\` and removed after both success and failure;
  - leftovers in `<data>\tmp\` are removed at start-up;
  - the `restore` row exists.
- Check: `uv run pytest tests/services/test_restore.py`

**T7.4 — Backup and restore user interface** (S) · Depends on: T7.3, T1.9
- Files: `ui/backup/actions.py`, `ui/backup/dialogs.py`, `ui/backup/labels.py`, `ui/shell/folders.py` (the one helper that opens a local folder), `i18n/backup_pt_BR.ts`, `i18n/backup_en_US.ts`, `i18n/backup_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/main_window.py` (File menu entries), `tests/ui/test_backup_ui.py`.
- Work:
  - File menu entries: "Back up…", "Restore…" and "Open data folder", which opens the local folder in Explorer through the single allowed helper of T0.4 (it accepts a local folder path only) — a local action, not a network one.
  - The passphrase dialog asks for the passphrase twice, enforces P05 and the strength rule, and warns that a lost passphrase cannot be recovered. The output path of a backup gets the network, cloud-sync and removable-media checks of T0.5/T7.5.
  - In read-only mode "Back up" reads through an in-memory copy (the backup API or `serialize()`) and writes nothing to the data folder; only the chosen output file is written.
  - Restore asks for confirmation and reports the result, and reports the error code of a demo/real mismatch in words.
  - A settings section for P05, P06 and P09 (with the hard floors of T1.5), registered through the T1.9 settings-section registry for Settings → Backup. T6.1 only renders it, so it appears once T6.1 exists.
  - Every dialog and file picker goes through the prompts interface.
  - **Open (QA finding P7-08):** removable media cannot be detected. No API the T0.4 guard allows can tell a removable drive from a fixed one: `QStorageInfo` has no removable flag (its file-system type is no indicator, USB drives are often NTFS), and `ctypes` (`GetDriveType`) is forbidden in application code. The removable-media check therefore always answers "not removable", and the advice "Keep another copy on separate media, away from this computer" is shown after every successful backup.
- Accept, using the prompts fake:
  - mismatched or too-short passphrases show a translated error and write no file;
  - a successful backup writes the `.cbrnbak` file at the chosen path and reports success;
  - restore asks for confirmation, and cancelling changes nothing;
  - read-only mode disables Restore but still allows Back up, and a Back up in read-only mode leaves the data folder byte-identical (nothing new in it);
  - "Open data folder" calls the allowed helper with the local data folder path, and the T0.4 guard still passes;
  - its settings section is tested through the registry, without the Settings page;
  - the pseudo-locale walk passes on the dialogs, which are registered in the dialog registry.
- Check: `uv run pytest tests/ui/test_backup_ui.py tests/ui/test_no_hardcoded_strings.py`

**T7.5 — Read-only mode, location warnings and the first-run data-protection notice** (S) · Depends on: T0.5, T1.5, T1.9, T7.2
- Files: `ui/shell/first_run.py`, `ui/shell/banners.py`, `ui/shell/main_window.py`, `app.py`, `paths.py` (writer for the `location.json` pointer file), `docs/data-protection.md`, `i18n/shell_pt_BR.ts`, `i18n/shell_en_US.ts`, `i18n/shell_es_ES.ts`, `tests/ui/test_first_run_and_location.py`.
- Work:
  - Apply D02 at start-up:
    - a non-writable location with an existing database opens in read-only mode;
    - a non-writable location with no database shows an explanation and offers a choice of folder through the prompts interface. The chosen folder is remembered in `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json` (D02, read by T0.5).
  - Warning banners for network and OneDrive locations, and a reminder banner when the last encrypted backup is older than P09 days.
  - The first-run notice is shown once (a flag in `prefs.json`). It says:
    - where the data lives;
    - that full-disk encryption is required by documentation (D03), that the app cannot check it, and that it does not protect files exported to removable media;
    - how backups work;
    - that "sensitive" is not a formal classification, and that real data must not be entered until the classification question (Q19) and Q4, Q11 and Q13 are answered;
    - that several people can take turns on one machine only with one shared Windows account, or with `--data-dir` pointing to a local folder restricted to the committee; with separate Windows accounts each person gets a separate database (A12).
  - `docs/data-protection.md` documents the threats, controls and LGPD note of §7, including that values already written to backups persist until those backups are deleted, and that a mandatory or non-persistent Windows profile discards `%LOCALAPPDATA%` at logoff (K05).
- Accept:
  - read-only mode shows the banner and disables every edit action;
  - with no database, the choice is offered and no file is created outside the folder finally chosen (apart from `location.json` in the profile);
  - the chosen folder is used again on the next start through `location.json`;
  - network and OneDrive paths (from injected probes) show their warnings;
  - in read-only mode nothing is written to the data folder (logs and preferences stay in memory), and a hot-journal database shows the translated explanation of T1.2;
  - the reminder banner follows the P09 age of the last encrypted backup;
  - the first-run notice appears exactly once and contains the classification statement, the disk-encryption limits and the shared-machine statement;
  - `docs/data-protection.md` exists and names the default data folder;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_first_run_and_location.py tests/ui/test_no_hardcoded_strings.py`

#### Phase 8 — Reports, import/export, snapshots and validation export (T8.1 in the MVP; T8.2–T8.7 in v1.0)
This phase covers R11–R13, R29, R31 and R35. T8.1 is part of the MVP, because its dependencies (T6.1, T6.5) are MVP tasks and the committee can start recording readings from v0.1.0; migration 0007 therefore ships in v0.1.0.

**T8.1 — Readiness snapshots (migration 0007)** (M) · Depends on: T6.1, T6.5
- Files: `storage/migrations/0007_snapshots.sql`, `services/snapshots.py`, `ui/dashboard/page.py` (a "Record snapshot" action), `app.py` (one start-up hook line for the monthly snapshot), `tests/services/test_snapshots.py`.
- Work:
  - Create `readiness_snapshot`, `readiness_snapshot_value` and `snapshot_withdrawal` as in §5.2, with `UPDATE` and `DELETE` triggers on all three.
  - Recording a snapshot for an as-of date stores, for every indicator and dimension, the value, the status and the targets in force, together with the app version, a configuration hash and `config_json`, the exact fields that were hashed, so the hash can be explained later.
  - A snapshot is never deleted. "Withdraw" appends a `snapshot_withdrawal` row (snapshot id, time, reason, operator) and writes a `change_log` row; a withdrawn snapshot stays stored but is ignored by exports and lists.
  - The configuration hash covers exactly these fields: P01–P04, P08, the A02 switch and mapping, the A04 validity months, the A05 switch, the A06 default intervals, and the targets (including their enabled flags). It excludes the operator label and the institution and unit names, so a change to those does not change the hash. T11.7 adds two fields to this list: `stock_expiry_warning_days` (P11) and `stock_item_type_minimum_quantity` (the minimum of every stock item type, as a map from type code to minimum); the hash therefore changes once on upgrade to 1.1.0 (K21).
  - The Settings → Snapshots section (P04) arrives with T8.7; until then the P04 default applies.
  - Origins:
    - `manual`;
    - `monthly`, taken at the first start in a calendar month of the local calendar date (P04; `clock.py`);
    - `report`, used by T8.7;
    - `retroactive`, whenever the local date on which the snapshot is taken is after its `as_of`, whatever triggered it (manual or report included). The service sets it and the caller cannot override it.
  - The monthly snapshot is skipped for the session when the clock sanity check of T1.9 has failed.
  - A withdrawn monthly snapshot still counts for its month: once the month's `monthly` snapshot was taken, no other is taken that month, whether or not it was withdrawn later (QA finding P8-14).
- Accept:
  - a snapshot stores one value row per indicator and dimension, and its `config_json` holds exactly the hashed fields;
  - the configuration hash changes when a target or any other hashed field changes, and not when the operator label or the institution or unit names change;
  - several starts in one month produce exactly one monthly snapshot, and its start-up hook is skipped in read-only mode and in demo mode;
  - a manual snapshot and a report snapshot for an as-of date before today get origin `retroactive`; for today's date they keep their own origin; the caller cannot force another origin;
  - an `UPDATE` or a `DELETE` on any of the three snapshot tables raises (trigger);
  - withdrawing a snapshot appends a `snapshot_withdrawal` row and a `change_log` row, leaves the snapshot and its values stored, and removes it from lists and exports;
  - in read-only mode the service refuses recording and withdrawal with the error code `READ_ONLY`, and the "Record snapshot" action is disabled (the withdraw action arrives with T8.7).
- Check: `uv run pytest tests/services/test_snapshots.py`

**T8.2 — Validation export for the predictive-validity comparison** (S) · Depends on: T8.1, T4.4
- Files: `services/validation_export.py`, `tests/services/test_validation_export.py`.
- Work:
  - For each exercise edition, prefer the latest non-withdrawn, non-retroactive snapshot taken before the edition's `start_on` (its `as_of` is before `start_on` and it was taken on a date before `start_on`).
  - If there is none, the operator may ask for a `retroactive` reading as of the day before `start_on`; otherwise the edition's rows carry the reason code `NO_PRIOR_SNAPSHOT`.
  - Write two CSV files in the D04 format, labelled as unsuppressed internal data in the file name and in a header row, with the same suppression as in the anonymised report offered as an option (A11):
    - readings: edition code, kind, `start_on`, snapshot id, snapshot `as_of`, `taken_at_utc`, `age_days` (days from the snapshot's local taken date to the edition's `start_on`), origin, indicator code, dimension, value, status;
    - results: edition code, metric code, value, respondents, scale.

  The statistical analysis is outside the app (§2.2).
  - Retroactive snapshots asked for by an export are recorded before the files are written, because their ids go into the files. When writing then fails, the error carries the ids of the snapshots it recorded (`ValidationExportError`); they stay stored, and the UI names them and says they can be withdrawn in the snapshot list (QA finding P8-08).
- Accept:
  - with snapshots both before and after an edition, the right one is chosen;
  - a withdrawn snapshot and a `retroactive` snapshot are not preferred over an earlier valid one;
  - retroactive readings are labelled with origin `retroactive`;
  - each readings row carries `taken_at_utc` and `age_days` as defined above;
  - the reason code appears when no reading exists;
  - the files contain aggregates only, with no staff identifiers; the file name and the header row say that they are unsuppressed internal data, and the suppression option replaces personnel-derived counts below the threshold by "< threshold";
  - in demo mode the file names start with `DEMO-`;
  - row order is deterministic.
- Check: `uv run pytest tests/services/test_validation_export.py`

**T8.3 — CSV export per module** (S) · Depends on: T2.3, T3.3, T4.4, T5.3
- Files: `storage/csv_io.py` (export), `services/export.py`, `docs/import-templates.md` (created here, with the column codes), `tests/storage/test_csv_export.py`.
- Work:
  - One file per entity, with stable English column codes, in the D04 format: UTF-8 with BOM, `;` separator, ISO dates, `.` as decimal point. The entities include `budget_execution` (one row per dated execution).
  - A text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with `'`.
  - When `app_meta.is_demo` is 1, every file name starts with `DEMO-`.
  - Money is written in major units with a currency column, and converted exactly from minor units using the decimal places of the currency allow-list (D15).
  - Exporting all entities is all-or-nothing: every file is written into a staging folder inside the chosen folder and moved into place only after all were written. On a failure (`EXPORT_FAILED`, with the entity in `field`) the staging folder is removed and the files already in the folder are left untouched, so a failed export never leaves a mix of new and older files. Before exporting, the UI (T8.7) counts the files of this export that already exist in the folder and asks before replacing them. This supersedes the earlier behaviour of the code, in which files finished before a failure stayed in the folder (QA finding P8-07).
- Accept:
  - reading the exported files back gives the same rows as the database;
  - a field containing `;`, quotes and line breaks survives the round trip;
  - a cell such as `=1+1`, `+x`, `-x`, `@x`, or one starting with a tab or a carriage return is exported with the `'` prefix, and the import strips it so the round trip is exact;
  - from a demo database every file name starts with `DEMO-`, and from a real database none does;
  - amounts survive exactly;
  - every exported column code is documented in `docs/import-templates.md`, which this task creates (T8.4 extends it with the import rules).
- Check: `uv run pytest tests/storage/test_csv_export.py`

**T8.4 — CSV templates and import** (M) · Depends on: T8.3
- Files: `storage/csv_io.py` (import), `services/importer.py`, `docs/import-templates.md` (extend with the import rules), `tests/fixtures/csv/` (fictitious files), `tests/services/test_importer.py`.
- Work:
  - Header-only templates for each entity.
  - Import in a single transaction, with a dry run that changes nothing.
  - Import order: list entities first (courses, asset types, evaluation metrics, funding sources), then the entities that refer to them.
  - Errors are reported per row, column and code.
  - A text cell that starts with the `'` prefix added by the export has it stripped. A file that is not valid UTF-8 is rejected as a whole with the error code `NOT_UTF8`, and the message tells the user to save the file as UTF-8. Code columns (identifiers, tags, codes) are always read as text, so leading zeros are kept.
  - The import order places budget entries before their execution rows.
  - Natural keys (each backed by a UNIQUE constraint or index in §5.2):
    - training course, asset type, evaluation metric and funding source: `code`;
    - staff: identifier;
    - PPE qualification: identifier, level, `issued_on`;
    - training record: staff identifier, course code, `completed_on`;
    - academic degree: staff identifier, level, field, year;
    - asset: tag;
    - status event: tag, `effective_on`;
    - maintenance: tag, `performed_on`, kind;
    - edition: code;
    - country: edition code, country code;
    - result: edition code, metric code;
    - budget entry: `fiscal_year`, source code, currency, description (an empty description is `''`);
    - budget execution: the budget-entry key above, `executed_on` and amount.
  - Duplicates by natural key are rejected.
  - Every imported row writes a `change_log` row with action `import`.
  - A row that the storage layer refuses (a constraint that no service check caught first) is reported for that row with `STORAGE_REFUSED`, and the import goes on to the next row; as for any error, nothing is written (QA finding P8-13).
  - An `asset` import reports, as a warning and not an error, how many of its assets are in service today and have no status event yet; until their status events are imported they count as in service with an unknown status (D26). The dry run reports the same count; the CSV format is unchanged (QA finding P8-12).
- Accept:
  - a valid fixture imports with the expected counts;
  - a file with any invalid row writes nothing and lists every error with row, column and code;
  - both `;` and `,` separators are accepted, with or without a BOM;
  - duplicates are rejected with their code;
  - a file saved in a legacy encoding (not valid UTF-8) is rejected with `NOT_UTF8` and writes nothing;
  - an identifier such as `00123` keeps its leading zeros through import;
  - a cell exported with the `'` prefix is imported without it;
  - budget execution rows import after their entries and are matched by entry key, `executed_on` and amount;
  - a dry run leaves the database unchanged;
  - every template column is documented in `docs/import-templates.md`, and vice versa.
- Check: `uv run pytest tests/services/test_importer.py`

**T8.5 — Report model and anonymisation** (M) · Depends on: T6.5
- Files: `reports/model.py`, `reports/anonymise.py`, `tests/reports/test_report_model.py`.
- Work:
  - A Qt-free report document for an as-of date contains:
    - a header with the institution and unit names (D18), the as-of date, the generation time, the app version and the operator label;
    - the preliminary notice (I06, P07);
    - key figures per module;
    - an indicator table with statuses and targets;
    - an alert summary;
    - in the internal variant only: lists of staff identifiers needing retraining and of overdue assets.
  - Two variants: internal (R11, R12) and aggregated, anonymised (R13).
  - The anonymised variant keeps counts only. It drops identifiers, labels, notes, descriptions, references and the operator label. Personnel-derived counts from 0 to threshold − 1 are shown as "< threshold" (A11), zeros included.
  - Secondary suppression: any total or sibling cell from which a suppressed value could be recomputed is suppressed too.
  - Charts of the anonymised variant are built only from the suppressed model; suppressed cells are not drawn.
  - Differencing between successive reports (the same population read at two dates) is not prevented; it is recorded as a residual risk (K03, Q10).
  - The alert summary is split by source (`reports/model.py`). For each of the severities critical and warning it holds a total and three parts: personnel (PPE qualification alerts; personnel-derived; the warning part declares the per-level `kf:PERSONNEL:expiring:<level>` cells as what it sums, the critical part the per-level `kf:PERSONNEL:expired:<level>` cells), infrastructure (maintenance alerts; never suppressed), and indicators (the readings with that status; it declares the personnel count readings that carry a status, so it is hidden whenever one of them is). The total declares its three parts, so a total with a hidden part is hidden too. The info count is maintenance only and is not personnel-derived. The personnel key figures gain an "expired" count per level (expired-qualification alerts at that level), and "retraining needed" (key figure and `PERS_RETRAINING_NEEDED` row) declares the expiring and expired cells of its level (A03), so a hidden expired count cannot be recovered as retraining minus expiring (QA findings P8-01, P8-03).
  - Residual limit, documented in `reports/anonymise.py` ("Not covered"): relations that are not declared are not considered. In particular `active_staff - valid:<level>` is the number of active people without a valid qualification at that level (expired, no renewal, or none); where every active person holds the level it equals the hidden expired count. That relation is not declared and not prevented (Q10).
  - The internal variant carries a handling notice set locally in Settings (empty by default, like D18). When `app_meta.is_demo` is 1, the report model carries the "DEMO — FICTITIOUS DATA" marker, which T8.6 draws.
- Accept:
  - on a fixture, the internal variant contains the expected sections and figures;
  - a scan of every string in the anonymised variant finds none of the fixture's identifiers, labels, notes or descriptions;
  - suppression applies to personnel-derived counts only, not to infrastructure, exercise or budget figures;
  - a fixture with a zero and with small counts shows "< threshold" for each, including the zero;
  - secondary suppression: a total from which one suppressed cell could be recomputed by subtraction is suppressed as well, and a total with no such risk is shown;
  - the chart data of the anonymised variant contains no value, label or category for a suppressed cell;
  - the threshold comes from the configuration.
- Check: `uv run pytest tests/reports/test_report_model.py`

**T8.6 — PDF rendering** (M) · Depends on: T8.5, T6.4
- Files: `reports/pdf.py`, `i18n/reports_pt_BR.ts`, `i18n/reports_en_US.ts`, `i18n/reports_es_ES.ts`, `i18n/__init__.py` (one line), `reports/message_keys.py`, `selftest.py` (add the "pdf" check), `pyproject.toml` (pypdf in the `dev` group), `uv.lock`, `tests/reports/test_report_pdf.py`, `tests/reports/test_report_pdf_parse.py`.
- Work:
  - Start with a spike: check whether pypdf extracts text reliably from a Qt-generated PDF. If it does not, content assertions move to the Qt-free report model (T8.5) and the PDF test checks page count, page size and metadata only (K18).
  - Render the report document to an A4 PDF with Qt's text-document and PDF-writer classes (D09). `QTextDocument.print()` has no per-page footer, so paginate manually with `QPainter`, drawing the footer notice and the page number on every page.
  - Include the title, page numbers, the preliminary notice in every page footer, and charts embedded through the T6.4 adapter. When the report model carries the demo marker (`app_meta.is_demo` is 1), every page, in both variants, carries a "DEMO — FICTITIOUS DATA" watermark and the PDF title says so.
  - Set the PDF document metadata (Info and XMP) explicitly, with no operator label, institution name or identifier in the anonymised variant.
  - The language is chosen per report. The renderer loads its own `QTranslator` set for that language and calls those translators directly, formats with an explicit `QLocale`, and never swaps the application's installed translators. Labels shared with the UI come from the Qt-free code→message-key map in `reports/message_keys.py`, so `reports/` does not import `ui/`.
  - **Status (QA finding P8-04, decided):** pypdf was added to the `dev` group (tests only, BSD-3-Clause, never bundled). `tests/reports/test_report_pdf_parse.py` opens the rendered PDFs with pypdf and asserts the page count, the A4 page size and, when pypdf extracts text from page 1, the preliminary notice and the page number on every page (K18: the text checks are skipped if extraction returns nothing). The content assertions on the layout built before painting (text and chart data) stay in `tests/reports/test_report_pdf.py`.
- Accept:
  - the output parses with pypdf;
  - the pages are A4;
  - if the spike shows extraction is reliable: the extracted text contains the localized title in each of the three languages, and the preliminary notice on every page, and the anonymised PDF's text contains none of the fixture identifiers; otherwise the same assertions are made on the report model and the PDF test checks page count, page size and metadata only;
  - the document metadata (Info and XMP) of the anonymised PDF contains no operator label, institution name or identifier of the fixture;
  - with a demo model, every page of both variants carries the watermark and the PDF title says "DEMO"; with a real model, none does;
  - generating a report in another language leaves the application's installed translators and default locale unchanged;
  - the self-test "pdf" check passes.
- Check: `uv run pytest tests/reports/test_report_pdf.py tests/reports/test_report_pdf_parse.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T8.7 — Reports, snapshots and import/export user interface** (M) · Depends on: T8.2, T8.4, T8.6
- Files: `ui/reports/page.py`, `ui/reports/dialogs.py`, `ui/reports/labels.py`, `i18n/reports_pt_BR.ts`, `i18n/reports_en_US.ts`, `i18n/reports_es_ES.ts` (update), `ui/shell/registry.py` (one line), `tests/ui/test_reports_page.py`.
- Work:
  - A report dialog to choose the variant, language, as-of date and output path (through the prompts interface), with a "record snapshot" option that is ticked by default (P04, origin `report`). For a past as-of date the option records a `retroactive` snapshot (T8.1), and the dialog says so.
  - Output paths for reports, CSV and the validation export get the same network, cloud-sync and removable-media warnings as the data folder (T0.5).
  - The internal report carries a handling notice set locally in Settings (empty by default, like D18); the Reports settings section holds it.
  - A snapshot list where snapshots can be recorded and withdrawn (with a reason); withdrawn snapshots are hidden by default.
  - The validation export, labelled as unsuppressed internal data, with the suppression option of T8.2.
  - CSV export, with a warning that the files contain internal data.
  - An import wizard: choose the entity and file, see the dry-run preview with its errors, confirm.
  - Settings sections for Reports (the A11 threshold and the handling notice) and Snapshots (P04), registered through the T1.9 settings-section registry.
  - A report is refused when its file name carries the marker of the other variant (`internal` for an anonymised report, `anonymised` for an internal one, compared without case); the user is told to change the name or the report. While the path is still the suggested one, it follows a change of variant or date (QA finding P8-02).
  - A "Write templates..." action writes the header-only template of every entity (T8.4) into a chosen folder, with the same destination warnings, and asks before replacing existing template files (QA finding P8-10).
- Accept, using the prompts fake:
  - each action produces its file under `tmp_path`;
  - generating a report for today with the option ticked records a snapshot with origin `report`, and for a past as-of date one with origin `retroactive`;
  - withdrawing a snapshot asks for a reason, keeps the snapshot stored and hides it from the list and from the validation export; there is no delete action;
  - an output path reported by an injected probe as network, cloud-synced or removable shows the matching warning;
  - an import dry run shows the errors and writes nothing;
  - read-only mode disables import and snapshot recording, while reports and exports stay available;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_reports_page.py tests/ui/test_no_hardcoded_strings.py`

#### Phase 9 — Packaging, release and distribution
T9.2, T9.3 and T9.4 belong to the MVP: T9.2 and T9.3 can start any time after T0.9, and T9.4 after T0.9 and T9.3. T9.5 can start any time after T0.8. T9.1 follows T8.6 and T7.2 and belongs to v1.0. T9.6 closes the MVP.

**T9.1 — Final build script and bundle-content checks** (M) · Depends on: T0.9, T9.2, T8.6, T7.2
- Files: `scripts/build_exe.py` (update), `tests/packaging/test_build.py` (extend).
- Work:
  - A Windows version resource is generated at build time from `__version__` into PyInstaller's work folder. It is never committed.
  - The excludes of T0.9 are kept, together with the post-build deletion of the unwanted Qt DLLs and plugins from `_internal` (`--exclude-module` takes Python module names and may leave Qt DLLs behind).
  - The bundle receives all package data except `*.ts` (migration `.sql` files, resources, `countries.json`, `THIRD_PARTY_DATA.md`, the `help/` files and every compiled `.qm`), plus the `licenses\` folder produced by T9.2.
  - The script prints the bundle size by top-level folder.
  - The self-test has a `demo` check (it creates and seeds a demo database inside its throwaway folder through the same entry point as `--demo`, and checks the demo flag, the seed marker and that every staff identifier starts with `DEMO`), and its `pdf` check renders a report with one small fictitious chart, so Qt Charts and `render_to_image` also run frozen (QA findings P9-12, P8-11).
- Accept (`packaging` marker):
  - every `storage/migrations/*.sql` file and `countries.json` is in the bundle;
  - the test asserts on the files actually present (no unwanted Qt DLLs or plugins), and the self-test shows nothing needed them;
  - the frozen executable's `--self-test` passes every check: paths, database, i18n in three languages, main window, chart, encrypted backup and PDF (§8);
  - the bundle contains no Qt network or web library (`Qt6Network.dll`, `Qt6WebEngine*`) and no `numpy`, `matplotlib` or `tkinter` (§7.3, §8);
  - the bundle contains no database, backup or CSV file and nothing from `tests/`, so no data is shipped;
  - the version resource, read back with the Windows version API through `ctypes`, equals `__version__`;
  - `licenses\` is present.
- Check: `uv run pytest -m packaging tests/packaging/test_build.py`

**T9.2 — Third-party licences and the dependency-licence allow-list** (M) · Depends on: T0.9
- Files: `scripts/collect_licenses.py`, `scripts/build_exe.py` (copy `licenses\` into the bundle), `tests/scripts/test_collect_licenses.py`, `tests/meta/test_dependency_licences.py`, `tests/packaging/test_build.py` (assert `licenses\` is present).
- Work:
  - From the installed runtime distributions, found through `importlib.metadata`, collect each licence text. These include PySide6 and its Essentials, Addons and shiboken6 parts, `cryptography`, `cffi` and `pycparser`.
  - Add:
    - the project's own GPL-3.0 text;
    - the LGPL-3.0 and GPL-3.0 texts for Qt;
    - the Python Software Foundation licence;
    - PyInstaller's bootloader-exception notice;
    - the Unicode/CLDR notice;
    - Qt's third-party attributions, taken from the Qt SBOM/attribution files of the bundled version;
    - the OpenSSL licence (inside `cryptography` and CPython), CPython's bundled-library notices and the Microsoft Visual C++ runtime redistribution notice;
    - a pointer to the exact Qt and PySide6 source release matching the bundled version, with a written offer for that source (GPL-3.0 §6, LGPL).
  - Write them into `licenses\`, with an index listing component, version and licence expression (the chosen alternative for an `OR` expression).
  - The allow-list test enforces the §4.2 list: MIT, BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0, LGPL-3.0 and GPL-3.0. It evaluates SPDX expressions: an `OR` expression passes when at least one alternative is allowed, and the chosen alternative is recorded in the index. PySide6 and shiboken6 declare `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`: the index records LGPL-3.0-only for Qt core and the bindings, and GPL-3.0-only for Qt Charts as a separate entry.
  - The allow-list also holds `MIT-0`, because `cffi` (a dependency of `cryptography`) declares it; §4.2 names it, and the list in the bullet above and the "`cffi` MIT" of the §4.2 table are read with it (QA finding P9-14).
  - The §4.2 table row "Cryptography", which gives `cffi` as MIT, predates finding P9-14 and is left as it was written; the `MIT-0` that `cffi` declares is recorded in the §4.2 paragraph below that table and in the bullet above (QA finding P9-14).
  - The licence index and the licence folders cover only the distributions that have files in the built bundle: the build passes the bundle to the collector, and a distribution that installs native files (`.pyd`, `.dll`, `.exe`) of which none is left in `_internal` (the build deletes them, for example the Qt PDF and web-engine wheels) gets no entry; a pure-Python distribution is compiled into the executable and counts as bundled (QA finding P9-04).
  - uv uses only its managed Pythons (`python-preference = "only-managed"`), and `.python-version` pins a full 3.12 patch version, because the CPython notices in `licenses\` describe that managed build. This is stricter than the plain `3.12` of D12 and T0.1 (QA finding P9-08).
- Accept:
  - every runtime distribution has an index entry and a licence text;
  - the allow-list test passes on the real environment;
  - a fake distribution with an unknown or disallowed licence makes it fail, and a fake `OR` expression with one allowed alternative passes and records that alternative;
  - the attribution, OpenSSL, CPython, Visual C++ runtime and source-offer files are present in `licenses\`;
  - the T0.9 build contains `licenses\` with the index.
- Check: `uv run pytest tests/scripts/test_collect_licenses.py tests/meta/test_dependency_licences.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T9.3 — Release workflow: zip, checksums, provenance attestation, draft release** (M) · Depends on: T0.8, T0.9
- Files: `.github/workflows/release.yml`, `.github/release-body.template.md`, `scripts/make_release_zip.py`, `tests/scripts/test_make_release_zip.py`, `tests/meta/test_workflows.py` (extend).
- Work:
  - The workflow triggers on tags `v*.*.*`.
  - Elevated permissions — `contents: write`, `id-token: write`, `attestations: write` — are granted only to the release job.
  - Steps:
    1. Pinned checkout and setup-uv; `uv sync --locked --all-groups` (the `build` group holds PyInstaller).
    2. A step that checks the tag equals `v` + `__version__`.
    3. The default suite, then the packaging suite.
    4. The build.
    5. `make_release_zip.py`, which writes `cbrn-readiness-dashboard-<version>-win-x64.zip` with the top folder `cbrn-readiness-dashboard\`, entries in a fixed order with fixed timestamps, and `SHA256SUMS.txt` in the `<sha256>  <file name>` format, and a per-file SHA-256 manifest of the bundle (`SHA256-FILES.txt`, every file inside the folder, `.pyd` and DLL files included) for IT teams that allow-list by file hash.
    6. GitHub's build-provenance attestation of the zip.
    7. `gh release create --draft` with the zip, the checksum file and the per-file manifest, adding `--prerelease` when the version is below 1.0.0 (the choice is made by a small function in `scripts/make_release_zip.py`, tested for 0.1.0 and 1.0.0; the workflow test asserts that the step uses it).
  - The release body, built from `.github/release-body.template.md`, states that the executable is unsigned (D10), that the tool is preliminary and not institutionally validated (I06), how to verify the checksum, what the checksum and the attestation do and do not prove (`SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity; the attestation proves where and how the build ran, not that the program is safe), and which placeholders are still flagged in `domain/config.py` (the code-level flags of §3.5). It links the matching source tag of this project and the exact Qt and PySide6 source release matching the bundled version, and carries the written offer for that source (§4.2, §8).
  - The workflow has two jobs; the steps above are not one job and there is no second build. A read-only `build` job runs steps 1–3, where the packaging suite builds the bundle once into `dist/` and runs its frozen self-test; step 5 zips that same tested folder; the release notes and the pre-release flag are written there; and the zip, the checksum files and the notes are uploaded as one workflow artefact. The `release` job, which needs `build` and alone has the write permissions, has no checkout and installs nothing: it downloads that artefact with the pinned `actions/download-artifact`, attests the zip (step 6) and creates the draft (step 7) (QA findings P9-01, P9-03).
  - The per-file manifest `SHA256-FILES.txt` is for verifying each extracted file. Allow-listing rules are then made from the verified folder with the organisation's own policy tooling, as the release body says. This supersedes the premise of step 5 and of D10, §8, T9.4 and T10.3 that IT teams allow-list by file hash straight from the manifest (QA finding P9-02; see the note on K02 in §11).
- Accept:
  - on a fake folder, the zip script produces the expected top folder and file list;
  - two runs produce byte-identical zips;
  - the checksum line verifies with `hashlib`;
  - the per-file manifest lists every file of the fake folder with the right hash, and is the same on two runs;
  - a test asserts that the release-body template contains the preliminary notice, the unsigned statement, the statement of what the checksum and attestation prove, and the link to the matching source tag, and that the Qt and PySide6 source links and the written offer are present;
  - the workflow test confirms: the tag trigger; every `uses:` pinned to a full SHA; elevated permissions scoped to the release job only; `uv sync --locked --all-groups`; the attestation step; the version-check step; that the release is created as a draft; and the `--prerelease` handling for versions below 1.0.0.
- Check: `uv run pytest tests/scripts/test_make_release_zip.py tests/meta/test_workflows.py`

**T9.4 — Release zip contents: first-run notes and the portable-mode example** (S) · Depends on: T9.3, T0.9
- Files: `packaging/README-first-run.pt-BR.txt`, `packaging/README-first-run.en-US.txt`, `packaging/README-first-run.es-ES.txt`, `packaging/portable.ini.example`, `scripts/make_release_zip.py` (include them at the folder root), `tests/scripts/test_make_release_zip.py` (extend), `tests/packaging/test_portable_mode.py`.
- Work:
  - The first-run notes are written from scratch in three languages and cover the steps of §8:
    - extract the whole zip first;
    - verify the checksum with `Get-FileHash`;
    - unblock the zip if needed (before extracting with Windows' own extractor; otherwise the files inherit the Mark-of-the-Web);
    - SmartScreen "More info → Run anyway";
    - on machines with AppLocker, WDAC or Smart App Control: the extraction folder must be a path that IT allows, and the per-file manifest exists for hash rules;
    - what the checksum and the attestation prove and do not prove;
    - the first-run notice points of T7.5 that matter before real data is entered (classification, disk encryption, shared machines);
    - where the data lives;
    - portable mode;
    - the full-disk-encryption requirement (D03);
    - the preliminary status;
    - the licence and the source URL.
  - `portable.ini.example` explains in comments what portable mode does and the risk that copying the folder copies the data (D02).
- Accept:
  - the zip contains the three notes and the example at the folder root;
  - the three notes have the same section structure;
  - each note mentions `Get-FileHash`, `%LOCALAPPDATA%\cbrn-readiness-dashboard`, the per-file manifest and the statement that "sensitive" is not a classification (Q19);
  - each first-run note contains the preliminary notice (I06, P07).
  - Packaging test (on the T0.9 build):
    1. Copy the built folder to `tmp_path` and rename the example to `portable.ini`.
    2. Clear `CBRN_DASHBOARD_DATA_DIR` and point `LOCALAPPDATA` at a temporary folder.
    3. Run `--self-test` without `--data-dir`.

    `selftest.json` must appear in `.\data\` beside the executable (the self-test opens no real database and removes its `tmp\selftest-*` folder, T0.7), and nothing must be written to the temporary `LOCALAPPDATA`.
- Check: `uv run pytest tests/scripts/test_make_release_zip.py` and `uv run pytest -m packaging tests/packaging/test_portable_mode.py`

**T9.5 — Dependency updates with Dependabot** (S) · Depends on: T0.8
- Files: `.github/dependabot.yml`, `tests/meta/test_workflows.py` (extend).
- Work:
  - Weekly update pull requests for GitHub Actions (Dependabot keeps the SHA pins) and for the uv lockfile.
  - Minor and patch updates are grouped.
  - Every update pull request runs CI, including the packaging job, before it can be merged.
  - Dependabot can leave the version comment next to a SHA pin stale, so the reviewer of each actions update checks the SHA against a tagged release.
- Accept: the test confirms that both ecosystems are configured with a schedule. A human confirms that the first Dependabot pull requests appear and run CI.
- Check: `uv run pytest tests/meta/test_workflows.py`

**T9.6 — Release v0.1.0** (S) · Depends on: every MVP task (T0.1–T7.5, T8.1, T9.2, T9.3, T9.4)
- Files: `src/cbrn_dashboard/__init__.py` (version `0.1.0`), `CHANGELOG.md` (created here), `README.md`, `docs/smoke-test.pt-BR.md`, `tests/meta/test_release_readiness.py` (created here; T10.5 extends it).
- Work:
  - Set the version to `0.1.0`.
  - Create `CHANGELOG.md` with a 0.1.0 entry that lists the placeholders still flagged in `domain/config.py` (§3.5, marking the local-only values, which are never cleared in code) and, as open questions only, the A-items without a setting (A01, A03, A12, A13, A14). It lists each question by its status only (open / answered and applied locally / answered and implemented in task Tn), never the content of an answer. It states the review status of the translations (Q14).
  - Update `README.md`: the status, the version and a link to the releases page. It no longer says "no code yet".
  - Write a short manual smoke checklist in pt-BR, `docs/smoke-test.pt-BR.md`: start the executable on a clean profile, enter one record per module, switch language, back up and restore, check the dashboard and the preliminary notice.
  - Tag `v0.1.0`; T9.3 creates the draft pre-release.
- Accept:
  - `CHANGELOG.md` has an entry for `__version__`;
  - `__version__` equals the installed metadata version;
  - the 0.1.0 entry lists exactly the placeholders still flagged in `domain/config.py`, noting which are local-only values (§3.5);
  - `README.md` no longer contains "no code yet" (case-insensitive);
  - a person runs the smoke checklist on a clean Windows profile without admin rights before publishing the draft.
- Check: `uv run pytest tests/meta/test_release_readiness.py`, then `uv run pytest` and `uv run pytest -m packaging`

#### Phase 10 — Documentation, demo, accessibility and v1.0 (v1.0)
This phase covers R28, R32 and I06, plus D23 with T6.5. It closes v1.0.

**T10.1 — Complete demo dataset and demo walkthrough** (S) · Depends on: T2.5, T3.5, T4.6, T5.5, T6.5, T8.1
- Files: `demo/__init__.py` (orchestration), `tests/demo/test_demo_complete.py`, `tests/ui/test_demo_walkthrough.py`.
- Work:
  - The demo database receives illustrative targets. They exist only in the demo database, whose banner and watermark mark everything as fictitious. They are never written to a real database and are not placeholders for one (P03 still applies to real data).
  - It also receives retroactive snapshots dated before the demo editions, so the validation export (T8.2) has content.
  - The day the demo data was created is stored in `app_meta` (`demo_created_on`), in the seeding transaction. A read-write `--demo` start of a demo database created on another day asks once whether to create the demo data again for today: yes replaces only the demo database file (a file that is not a demo database is refused and left as it is; the real database and `demo\backups\` are never touched), no keeps it as it is. In read-only mode nothing is asked or written, and a demo database without a stored creation day is not outdated (QA finding P10-02).
  - `generate()` refuses a database whose `app_meta.is_demo` is not set (`NOT_A_DEMO_DATABASE`) before it writes anything, so demo targets and snapshots never reach a real database (QA finding P10-07).
  - The year-end `BUD_EXEC_RATE` targets of the demo are stored at most at `YEAR_END_TARGET_MAX` = 1.0 (100 % of the allocation), so they are valid on every day of the year (early in January the plain quotient would be far above 1). The price: a group can read Warning or Critical only while its executed share is at or below the elapsed fraction of the year, so the DIRSA group (executed 4–12 %) reads OK instead of Critical in a demo database created before about mid-February; the walkthrough gives 13 February (`demo/targets.py`, `docs/demo-walkthrough.md`). On 31 December no execution row is dated after today, because a row must stay inside its fiscal year (QA finding P10-03).
  - The two sources word the end of that period differently, and both wordings are kept: the docstring of `demo/targets.py` says the DIRSA group reads OK "from 1 January until about the middle of February"; `docs/demo-walkthrough.md` says the table is exact "in a demo database created from 13 February on" and that one "created before 13 February" reads OK instead of Critical (QA finding P10-03).
- Accept:
  - every registered page shows at least one row;
  - the dashboard shows at least one alert of every kind in §5.5;
  - the demo banner is visible on every page;
  - the validation export of the demo database produces rows;
  - after a demo run, a real database created in another folder has no targets and no snapshots.
- Check: `uv run pytest tests/demo/test_demo_complete.py tests/ui/test_demo_walkthrough.py`

**T10.2 — In-app help in three languages and the About dialog** (M) · Depends on: T9.2, T1.9, T8.7
- Files: `src/cbrn_dashboard/help/pt_BR.md`, `help/en_US.md`, `help/es_ES.md`, `ui/shell/help.py`, `ui/shell/about.py`, `i18n/shell_pt_BR.ts`, `i18n/shell_en_US.ts`, `i18n/shell_es_ES.ts`, `tests/ui/test_help_and_about.py`.
- Work:
  - The help is written from scratch (F06), with no clinical content (D19). It covers each page, the as-of date, alerts, backups and restore, import, reports, snapshots, privacy and the preliminary status.
  - It is rendered as Markdown inside the app and follows the current UI language.
  - The About dialog shows:
    - the version;
    - the GPL-3.0-or-later notice and the absence of any warranty;
    - the source URL `https://github.com/marco-jardim/cbrn-readiness-dashboard` as plain, selectable text;
    - one entry per component from the T9.2 licence index;
    - the preliminary notice (P07).
- Accept:
  - the help loads in each language and switches with the UI language;
  - the three help files have the same heading structure;
  - the help contains no hyperlink to an external address;
  - the About dialog shows a version equal to `__version__`, the licence notice, and one line per component in the index;
  - the pseudo-locale walk passes on both dialogs.
- Check: `uv run pytest tests/ui/test_help_and_about.py tests/ui/test_no_hardcoded_strings.py`

**T10.3 — Reference documentation: install guides, indicator reference, architecture** (M) · Depends on: T6.5, T9.3, T9.4
- Files: `docs/install.pt-BR.md`, `docs/install.en-US.md`, `docs/install.es-ES.md`, `docs/indicators.md`, `docs/architecture.md`, `tests/meta/test_docs.py`.
- Work:
  - *Install guides:*
    - requirements (§8);
    - download;
    - checksum verification with `Get-FileHash`, and optional provenance verification with `gh attestation verify` (this needs network access on the user's side; the app itself stays offline);
    - unblocking and extracting;
    - SmartScreen;
    - allow-listing for IT teams using AppLocker or WDAC: an allowed extraction folder, hash rules per file and per release (the `.pyd` and DLL files too, from the per-file manifest), and the fact that Smart App Control has no per-file bypass;
    - what the checksum and the attestation prove and do not prove;
    - the data location and portable mode;
    - upgrades;
    - removal (delete the folder; the data stays in the profile until the user removes it);
    - backups.
  - *`docs/indicators.md`:* every indicator code with its definition, dimensions, appendix line (L) and R code, default target and placeholder status; and every placeholder of §3.5 with its open question.
  - *`docs/architecture.md`:* the layers (§4.1), the package map (§4.4), the migration rules, the translation workflow, and how to add a module. Its purpose is handover to another team (R32).
- Accept:
  - the three install guides exist with the same heading structure, and each mentions `Get-FileHash`, `gh attestation verify` and `%LOCALAPPDATA%\cbrn-readiness-dashboard`;
  - every indicator code in the registry appears in `docs/indicators.md`, and every code in the document exists in the registry;
  - every placeholder flagged in `domain/config.py` appears with its Q code;
  - `docs/architecture.md` names every top-level package under `src/cbrn_dashboard/`.
- Check: `uv run pytest tests/meta/test_docs.py`

**T10.4 — Accessibility and usability pass** (M) · Depends on: T6.5, T8.7
- Files: `ui/**` (adjustments), `ui/shell/main_window.py` (shortcuts), `tests/ui/test_accessibility.py`.
- Work:
  - Every action is reachable from the keyboard, through a mnemonic or a shortcut, with a sensible tab order.
  - Every interactive widget has an accessible name or a buddy label.
  - Wherever a status is shown — tiles, alerts, asset statuses, indicator tables — it appears as text plus icon plus a colour-blind-safe colour (D23, completing T6.5).
  - The window has a minimum size, and the OS font scaling and high-DPI scaling are respected.
- Accept: a walk over every registered page and every dialog in the dialog registry (T1.9) shows that:
  - every interactive widget has an accessible name or a buddy label;
  - every status display contains text;
  - every menu action has a mnemonic or a shortcut;
  - every page opens with `QT_SCALE_FACTOR=2` without Qt warnings;
  - the pseudo-locale walk still passes.
- Check: `uv run pytest tests/ui/test_accessibility.py tests/ui/test_no_hardcoded_strings.py`

**T10.5 — Release candidate and final build for v1.0** (S) · Depends on: every non-deferred task
- Files: `CHANGELOG.md` (extend; created by T9.6), `src/cbrn_dashboard/__init__.py` (version `1.0.0`), `README.md`, `src/cbrn_dashboard/domain/config.py` (flags of generic defaults cleared, and defaults changed, only when the project owner judges the value not sensitive; local-only values never), `docs/manual-test-script.pt-BR.md`, `PLAN.md` (update §3.5 and §12 with the status of each answer received, never its content), `tests/meta/test_release_readiness.py` (extend; created by T9.6).
- Work:
  - PLAN.md and the changelog record only the status of each question (open / answered and applied locally / answered and implemented in task Tn), never the content of an answer. Answers, thresholds, security rules, deployment constraints, retention rules and institution names live in a private document outside the repository. Real targets are entered in Settings and never become code defaults.
  - Placeholders are split as in §3.5. The local-only values (targets P03, institution and unit names, the report handling notice) keep their flag and their empty default in code and are confirmed per installation in Settings only. For a generic default, the flag may be cleared and the default changed only when the project owner judges that the value is not sensitive; the commit and the changelog record only the status, never the committee's reasoning.
  - The changelog entry for 1.0.0 lists every placeholder still flagged in `domain/config.py` (§3.5), and the number of translation messages still marked unfinished, or states that none remain (Q14).
  - The version is bumped.
  - The manual test script, in pt-BR for the committee, gives steps and expected results with the demo data for each page, the alerts, language switching, backup to removable media and restore, report generation, CSV import and the read-only mode.
  - Run the full default and packaging suites, then tag `v1.0.0`; T9.3 creates the draft release.
  - A person starts the executable on a clean Windows profile without admin rights, runs the manual test script, and then publishes the draft.
- Accept:
  - `CHANGELOG.md` has an entry for `__version__`;
  - `__version__` equals the installed metadata version;
  - the 1.0.0 entry lists exactly the placeholders still flagged in `domain/config.py`; the local-only values (targets, institution and unit names, handling notice) are still flagged and have no code default other than empty or none;
  - either no unfinished message remains in the `.ts` files, or the changelog states the count still pending review and it equals the count found;
  - `README.md` states version 1.0.0;
  - every question in the changelog entry is listed as `Qn` followed by one of the three status phrases and nothing else (the test checks the form, not the meaning);
  - the manual test script names every registered page.
- Check: `uv run pytest tests/meta/test_release_readiness.py`, then `uv run pytest` and `uv run pytest -m packaging`

#### Phase 11 — Stock by lot, antidotes and decontaminants (owner request 2026-11-20; v1.1.0)
This phase covers O01–O04 (§3.1b) and the decisions D32–D38. It adds the stock of CBRN consumables and equipment by lot, with dated movements, a minimum per item type, stock indicators and alerts, and the page "Antídotos e descontaminantes". It is a separate release, 1.1.0, that follows v1.0. Stock is management data only: type, lot, quantity, expiry date, price and movements; there is no dose, indication or protocol field (D19, D38, K20).

Rules that hold for every task of the phase:
- The stock tables are written only through `storage/stock_repo.py`, which uses the repository helpers of T1.4, so every write logs one `change_log` row per affected row, cascades included. The log holds no personal column.
- The names of the 17 built-in stock item types are kept exactly as the owner wrote them (title case, for example "Antídoto Químico"). They and the term "aprazamento" are flagged for the terminology review (Q14).
- Stock alert kinds and subject kinds never start with `STOCK_` (`LOT_EXPIRED`, `LOT_EXPIRING`, `LOW_STOCK`; subjects `LOT` and `ITEM_TYPE`), because `tests/meta/test_docs.py` reads every code in `docs/indicators.md` that starts with an indicator prefix as an indicator. Dimension keys are `category` and `item`, never `type`.
- Placeholders P11 and P12 and assumptions A15 and A16 are added to §3.5 by T11.4, together with the code. This phase's tasks may refer to them before then.
- The new placeholder P12 (minimum stock per type) is local-only: no code default, flag never cleared in code (§3.5). Minimums appear only in the demo database (D25).

**T11.1 — Open the 1.1.0 cycle** (S) · Depends on: T10.5 · **Status: done** (commit `a8e3e21`)
- Files: `src/cbrn_dashboard/__init__.py`, `README.md`, `docs/install.{pt-BR,en-US,es-ES}.md`, `docs/architecture.md`, `docs/smoke-test.pt-BR.md`, `docs/manual-test-script.pt-BR.md`, `CHANGELOG.md`, `tests/meta/test_release_readiness.py`.
- Work: set the version to 1.1.0; name 1.0.2 as the last published version in the documents and in the readiness tests (it stays in the changelog as published history); add an unreleased `1.1.0` changelog entry that says what has not happened (no tag, no workflow run, no manual test). No code other than the version string changes.
- Accept: the readiness tests pass for 1.1.0; the changelog entry states that it is not published.
- Check: `uv run pytest tests/meta/test_release_readiness.py`

**T11.2 — Plan amendments for the stock module** (S) · Depends on: T11.1 · **Status: done** (commit `ebcbf23`)
- Files: `PLAN.md`, `tests/meta/test_release_readiness.py`, `CHANGELOG.md`.
- Work:
  - Amend `PLAN.md` as follows: the label O (§1); the non-goal of §2.2; the new §3.1b (O01–O04); the decisions D32–D38 (§3.4); the package map (§4.4); the data model (§5.1–§5.5); the catalogue areas `stock` and `antidotes` (§6); the stock data under the "sensitive" working label (§7.1); the hashed-field note of T8.1; the Phase 11 tasks; the sizing row (§10.4); the risks K20–K23 (§11); the questions Q25–Q29 and the Q14 scope (§12); and §13.1.
  - The questions use the form of Q1–Q24 and record the status and the working answer only, never the content of an answer (T10.5). §3.5 is not touched here: A15, A16, P11 and P12 arrive with the code in T11.4.
  - Set `QUESTION_NUMBERS = range(1, 30)` in `tests/meta/test_release_readiness.py`, and list Q25–Q29 as `open` in the "Open questions" section of the 1.1.0 changelog entry.
- Accept:
  - `PLAN.md` has O01–O04, D32–D38, K20–K23 and Q25–Q29 (each opened by `**Qn —`), the amended non-goal and the Phase 11 tasks;
  - the changelog entry for 1.1.0 lists exactly Q1–Q29, each with one of the three status phrases, and the changelog test finds the same set in the plan;
  - the other tests of `tests/meta` still pass.
- Check: `uv run pytest tests/meta`

**T11.3 — Stock schema (migration 0009)** (S) · Depends on: T11.2, T1.3 · Parallel with: T11.4 · **Status: done** (commit `b3c1032`)
- Files: `storage/migrations/0009_stock.sql`, `tests/storage/test_schema_stock.py`, `docs/architecture.md` (§9, the migration list).
- Work:
  - Create `stock_item_type`, `stock_lot` and `stock_movement` as in §5.2, with `STRICT`, the date `GLOB` checks of 0003, the currency check of 0005, `UNIQUE (type_id, lot_code)` and `UNIQUE (lot_id, moved_on, kind, quantity, reference)` (an empty reference is `''`, not NULL), an index on `stock_lot (type_id)`, `ON DELETE RESTRICT` from lot to type and `ON DELETE CASCADE` from movement to lot. A price and a currency are both set or both empty. `minimum_quantity` is NULL or at least 0, and a movement quantity is at least 1.
  - Seed the 17 built-in types with `built_in = 1`, `active = 1`, NULL labels and NULL minimum (their names come from `ui/stock/labels.py`). Codes are upper snake case, like `DIRSA` and `COMAER`, and so differ from the lower-case asset-type codes: `ANTIDOTE_CHEMICAL`, `ANTIDOTE_RAD_NUCLEAR`, `ANTIDOTE_BIOLOGICAL` (category antidote); `DECONTAMINANT` (decontaminant); `DETECTOR_CHEMICAL`, `DETECTOR_RAD_NUCLEAR`, `DETECTOR_BIOLOGICAL` (detector); `MASK_FULL_FACE`, `FILTER_CBRN`, `PPE_LEVEL_A`, `PPE_LEVEL_B`, `PPE_LEVEL_C`, `GLOVE`, `BOOT`, `APRON` (ppe); `OXYGEN_CYLINDER`, `ISOLATION_STRETCHER` (other). Their pt-BR names, exactly as the owner wrote them, are: "Antídoto Químico", "Antídoto Radiológico e Nuclear", "Antídoto Biológico", "Descontaminante", "Detector Químico", "Detector Radiológico e Nuclear", "Detector Biológico", "Máscara Fullface", "Filtro QBRN (CBRN)", "EPI nível A", "EPI nível B", "EPI nível C", "Luva", "Bota", "Avental", "Cilindro de O2" and "Maca Bolha (Cápsula de Isolamento para Transporte)".
  - The header comment has no apostrophes and no text `migrate:`. Like every schema and seed migration, the file writes no `change_log` row.
- Accept:
  - the 17 built-in types exist after the migration, each with its category, and none has a label or a minimum;
  - a category outside the five, a negative minimum, a date of the wrong shape, a quantity of 0 or less, a kind outside the six, and a price without a currency (or the reverse) are rejected;
  - a second lot with the same type and code, and a second movement with the same lot, date, kind, quantity and reference, are rejected;
  - a type in use cannot be deleted; deleting a lot deletes its movements;
  - the existing migration tests pass with the ninth migration present (the tests that count or list migrations are updated if they name the last one).
- Check: `uv run pytest tests/storage/test_schema_stock.py`

**T11.4 — Stock rules, expiry window and minimum placeholders** (M) · Depends on: T11.2, T1.1, T1.5, T1.6 · Parallel with: T11.3 · **Status: done** (commit `365b324`)
- Files: `domain/stock.py`, `domain/config.py`, `docs/indicators.md` (placeholder rows only), `PLAN.md` (§3.5), `CHANGELOG.md`, `tests/domain/test_stock.py`, `tests/domain/test_config.py`, `tests/meta/test_release_readiness.py` (`LOCAL_ONLY_IDS` gains `P12`, `ASSUMPTIONS_WITHOUT_SETTING` gains `A15` and `A16`).
- Work: pure functions, no Qt, no I/O and no clock; each takes the as-of date *d*.
  - Enums `StockCategory` (antidote, decontaminant, detector, ppe, other), `MovementKind` (six kinds, with a sign of +1 for receipt and adjustment in, −1 for the others) and `LotStatus` (`VALID`, `EXPIRING`, `EXPIRED`, `EMPTY`, `NOT_RECEIVED`). The antidote page categories and the categories that need an expiry date are both antidote and decontaminant. Records `StockType`, `Lot`, `Movement`, and `StockRules(expiry_warning_days=90)`.
  - `quantity_on(movements, lot_id, d)` is the signed sum of the movements dated on or before *d*. `first_negative_day(movements)` takes the end-of-day running totals in ascending date order (the order inside one day is ignored) and returns the first date with a negative total, or None.
  - A lot is valid on *d* when `expires_on` is empty or not before *d*; its valid quantity is the on-hand quantity if valid, else 0. Status order (D34): not received (no movement on or before *d*), empty (on hand 0), expired (`expires_on` < *d*), expiring (*d* ≤ `expires_on` ≤ *d* + P11, inclusive, as `is_due_soon` of T3.2), valid.
  - `lot_rows` returns one row per lot (type code, category, lot code, first receipt date, expiry, on hand, valid quantity, status, signed days to expiry, unit price, currency, value as on hand times price or None), sorted by category, type code, expiry (no expiry last) and lot code. `type_summaries` returns on hand, valid, expired and expiring quantities, expired and expiring lot counts, the minimum and `below_minimum` (None without a minimum; otherwise valid < minimum, strict, so a minimum of 0 is never below). A type is "in use on *d*" when it has a lot with a movement on or before *d*.
  - `stock_value` returns, per currency, the valid and the expired value, plus the number of unpriced lots; currencies are never added together (D15). `expiry_schedule(rows, d, months=12)` (1 to 60 months) buckets the lots with stock into expired, one bucket per month from the month of *d* on (`domain/dates.py`), later, and no expiry; quantities are added per type inside one bucket only.
  - `domain/config.py` gains `stock_expiry_warning_days` (P11: a generic default of 90 days, added to the day fields) and the placeholder P12 (minimum stock per type: local-only, no code default, no config field, like P03; the minimum is stored in `stock_item_type`).
  - `PLAN.md` §3.5 gains A15 (whole units of issue, no unit column; Q26), A16 (the category of each built-in type; Q25), P11 (stock expiry warning window, 90 days; Settings → Alerts; Q28) and P12 (minimum stock per type, empty; Settings → Infrastructure; Q26; local-only). A15 and A16 carry no setting, so they are assumptions without a setting. The changelog entry lists P11 as a generic default, P12 as local-only, and A15 and A16 as depending on Q26 and Q25. `docs/indicators.md` gains the rows for P11 and P12.
- Accept: table-driven tests with a fixed date cover:
  - the signed sum with movements before, on and after *d*, and a backdated outflow that makes a negative end-of-day balance;
  - every status and the order between them, with the expiry exactly on *d*, on *d* + P11 and one day later;
  - a type with no minimum, with a minimum of 0, and valid one below, equal to and above the minimum;
  - values in two currencies kept apart and unpriced lots counted;
  - the schedule across a year boundary and with an expired lot;
  - `ReadinessConfig()` has `stock_expiry_warning_days == 90`; P12 is flagged, local-only and has no code default; the placeholder, documentation and release-readiness tests pass.
- Check: `uv run pytest tests/domain/test_stock.py tests/domain/test_config.py tests/meta`

**T11.5 — Stock repository and service: types and lots** (M) · Depends on: T11.3, T11.4 · **Status: done** (commit `4178ee2`)
- Files: `storage/stock_repo.py`, `services/stock.py`, `ui/shell/context.py` (`Services.stock`), `tests/storage/test_stock_repo.py`, `tests/services/test_stock_service.py`.
- Work: the service follows `services/infrastructure.py`: refuse read-only mode first, validate, then write in one transaction through the repository helpers. Error codes are enum values; the UI maps them to text.
  - Types: a built-in type is never deleted and only its minimum and its active flag change (`BUILT_IN_TYPE`). A user type needs a pt-BR label (`LABEL_PT_BR_REQUIRED`). The code is frozen once a lot uses it (`CODE_IMMUTABLE`) and so is the category (`CATEGORY_IMMUTABLE`). An inactive type takes no new lot (`TYPE_INACTIVE`), but movements on its existing lots stay possible. Deleting a user type that has lots is refused (`TYPE_IN_USE`). Setting a minimum logs an update and, when it confirms P12, a `setting` row in the same transaction.
  - Lots: creating a lot needs an initial receipt (date, quantity of at least 1) written in the same transaction (`INITIAL_RECEIPT_REQUIRED`). The expiry date is required for antidotes and decontaminants (`EXPIRY_REQUIRED`). A lot code has at most 64 characters (`TEXT_TOO_LONG`); a duplicate is `DUPLICATE_LOT`. The currency must be in the allow-list (`INVALID_CURRENCY`); a price is a whole number of minor units from 0 to the budget maximum; a price without a currency takes the default currency; no price means no currency. Deleting a lot deletes its movements, and each cascaded row gets its own `delete` row in the log.
  - `Services.stock` is wired in `build_services`.
- Accept:
  - every error code above is raised by a test, and nothing is written when one is raised;
  - a lot and its initial receipt appear together in the log, and a failure of the receipt leaves no lot;
  - deleting a lot logs one row for the lot and one for each movement;
  - read-only mode gives `READ_ONLY` for every write;
  - no `change_log` value holds a personal column.
- Check: `uv run pytest tests/storage/test_stock_repo.py tests/services/test_stock_service.py`

**T11.6 — Movements, balance rule and as-of views** (M) · Depends on: T11.5 · **Status: done** (commit `31b0491`)
- Files: `services/stock.py`, `storage/stock_repo.py`, `tests/services/test_stock_service.py` (extend), `tests/services/test_stock_movements.py`.
- Work:
  - Add, edit and delete movements. A quantity is from 1 to 1,000,000 (`INVALID_QUANTITY`); an adjustment needs a note (`NOTE_REQUIRED`); a date after `Clock.local_date()` is refused (`DATE_IN_FUTURE`, with the injected clock); a duplicate is `DUPLICATE_MOVEMENT`.
  - The balance is never negative (D33): on every insert, update and delete, backdated ones included, the change is applied in memory first and refused with `BALANCE_NEGATIVE` (field `quantity`, or the movement id for a delete) when `first_negative_day` is not None, before anything is written. The last movement of a lot cannot be deleted (`ONLY_MOVEMENT`; like `ONLY_STATUS_EVENT` in T3.3). A real lot is closed with a disposal or a loss and then shows as empty.
  - Read views for an as-of date: the lot rows, the type summaries, the value, the expiry schedule and the movements of a lot with the balance after each, all through the domain functions.
  - `alert_inputs()` returns the types, lots and movements that the alert and indicator services need.
- Accept:
  - a backdated issue that would make an earlier day negative is refused, and so is deleting a receipt that later issues depend on, and editing a quantity or a date into a negative balance;
  - an issue of the whole stock leaves 0, and the lot reads as empty;
  - a movement dated tomorrow is refused; one dated today is accepted;
  - the views for a date before the first receipt show the lot as not received;
  - every refusal leaves the database as it was.
- Check: `uv run pytest tests/services/test_stock_service.py tests/services/test_stock_movements.py`

**T11.7 — Stock indicators, `Module.STOCK`, snapshot hash and wiring** (M) · Depends on: T11.6, T6.1, T8.1 · **Status: done** (commit `a31dcdb`, with T11.9)
- Files: `domain/stock.py`, `domain/indicators.py`, `domain/registry.py` (one `PROVIDERS` line), `services/indicators.py`, `services/dashboard.py`, `services/snapshots.py`, `ui/shell/context.py`, `demo/stack.py`, `ui/reports/actions.py`, `ui/dashboard/labels.py`, `docs/indicators.md`, `tests/meta/test_docs.py`, `tests/domain/test_stock.py`, `tests/domain/test_indicators.py`, `tests/ui/test_dashboard_page.py`, `tests/ui/test_alert_labels.py`, `tests/reports/test_report_pdf.py`, `tests/services/test_stock_indicators.py`, `tests/services/test_snapshots.py`.
- Work:
  - `Module.STOCK` is appended last to `Module`. The four indicators of §5.4 are `STOCK_VALID_QTY` (dimension `category`, `item`), `STOCK_LOTS_EXPIRING`, `STOCK_LOTS_EXPIRED` and `STOCK_TYPES_BELOW_MIN` (dimension `category`), all counts. A value of `STOCK_VALID_QTY` is produced for each active type that is in use on the date or has a minimum, and for each inactive type that still has stock on hand; the lot counts for every category that has such a value; `STOCK_TYPES_BELOW_MIN` only for a category with at least one active type that has a minimum. A fresh real database therefore shows no stock tiles (D36, K22). The minimum is not a target (D35).
  - `IndicatorService`, `DashboardService`, `SnapshotService` and `ReportBuilder` each take an optional `stock=None` keyword. It is wired in `ui/shell/context.py`, `demo/stack.py`, `services/snapshots.py` and `ui/reports/actions.py`; a test asserts that `build_services` wires stock everywhere.
  - Snapshots take the stock values automatically. The hashed configuration gains `stock_expiry_warning_days` and `stock_item_type_minimum_quantity` (a map from type code to minimum, for all types), so the hash changes once on upgrade (K21; T8.1 notes the fields).
  - Dashboard labels: the units "unit/units", "lot/lots" and "item type/item types", the context text "mínimo %1" or "mínimo não definido" for `STOCK_VALID_QTY`, and the `category` and `item` parts of the dimension text (the category is left out when the item is present); the display names gain the stock types.
  - `docs/indicators.md` gains the four indicators. Their appendix column reads "none (owner request 2026-11-20)"; `tests/meta/test_docs.py` gets an exception for indicators whose source contains an `O` code (`O\d\d`), which have no `Lnn` reference.
  - The tests that enumerate `Module` are updated: `tests/domain/test_indicators.py`, `tests/ui/test_dashboard_page.py`, `tests/ui/test_alert_labels.py` and `tests/reports/test_report_pdf.py`.
- Accept:
  - the indicator values of a fictitious stock match hand-computed numbers, including a type with a minimum and no lot, an inactive type with stock, a lot with the expiry on the boundary of P11, and two categories;
  - a database with no stock gives no stock value;
  - a target on `STOCK_VALID_QTY` gives a status, and the minimum does not;
  - a snapshot holds the stock rows, and the configuration hash changes when `stock_expiry_warning_days` or a minimum changes; an indicator missing from an older snapshot is read as "no data", never as zero;
  - the documentation test passes with the four new codes and no stock alert or subject kind starting with `STOCK_`.
- Check: `uv run pytest tests/domain tests/services/test_stock_indicators.py tests/services/test_snapshots.py tests/meta/test_docs.py tests/ui/test_dashboard_page.py tests/ui/test_alert_labels.py tests/reports/test_report_pdf.py`

**T11.8 — Stock alerts** (M) · Depends on: T11.7, T6.2 · **Status: done** (commit `2fbcb57`, with T11.10 and T11.14)
- Files: `domain/alerts.py`, `services/alerts.py`, `reports/model.py` (the alert source and the alert summary only), `ui/alerts/models.py`, `ui/alerts/labels.py`, `i18n/alerts_*.ts`, `tests/domain/test_alerts.py`, `tests/services/test_alerts_service.py`, `tests/ui/test_alert_labels.py`, `tests/reports/test_report_model.py`.
- Work:
  - Add the alert kinds `LOT_EXPIRED` (critical), `LOT_EXPIRING` (warning) and `LOW_STOCK` (critical), and the subject kinds `LOT` and `ITEM_TYPE` (§5.5). A lot alert needs stock on hand, so an empty lot never alerts, and a lot has at most one alert. `LOW_STOCK` applies to an active type with a minimum, with the valid quantity as value and the minimum as threshold, and has no due date. The dimension is `category=<c>;item=<code>`. `stock_alerts(...)` reuses `lot_rows` and `type_summaries`; `all_alerts` gains keyword parameters with defaults, so existing callers do not change.
  - `AlertService` takes `stock: StockService | None = None` and reads `stock.alert_inputs()`.
  - Navigation: for the subjects `LOT` and `ITEM_TYPE`, and for an indicator of the stock module, a category of antidote or decontaminant opens the page `antidotes` and any other category opens `infrastructure`; the module page of `Module.STOCK` is `infrastructure`.
  - Messages in the context "Alerts", with `%n` plurals: "Lot %1 of %2 expired %n day(s) ago and still has stock.", "Lot %1 of %2 expires in %n day(s)." and "Valid stock of %1 is %2, below the minimum of %3.".
  - Reports: `AlertSource` gains `STOCK` and the alert summary gains the part `alert:<SEVERITY>:stock`, so the total declares four parts. This ships here, because a stock alert would otherwise break the report tests.
- Accept: tests cover each kind on, just inside and just outside its boundary; no alert for an empty lot, for a lot with no expiry, or for a type with no minimum; at most one alert per lot and per type; the severity order and due dates; the target page of every subject; all plural forms of the three messages in the three languages; the report alert summary counts stock alerts, and the anonymised summary still adds up.
- Check: `uv run pytest tests/domain/test_alerts.py tests/services/test_alerts_service.py tests/ui/test_alert_labels.py tests/reports/test_report_model.py tests/i18n`

**T11.9 — Shared stock UI: labels, models and dialogs** (M) · Depends on: T11.6, T1.9 · **Status: done** (commit `a31dcdb`, with T11.7)
- Files: `ui/stock/__init__.py`, `ui/stock/labels.py`, `ui/stock/models.py`, `ui/stock/dialogs.py`, `i18n/__init__.py` (area `stock` with the folder `ui/stock`, context `Stock`), `i18n/stock_{pt_BR,en_US,es_ES}.ts`, `ui/shell/registry.py` (dialog registry: `stock.lot`, `stock.movement`, `stock.type`, with fictitious data), `ui/shell/formatting.py` (only if a shared helper is needed), `docs/architecture.md` (§11, contexts), `reports/message_keys.py`, `tests/ui/test_stock_labels.py`, `tests/ui/test_stock_dialogs.py`.
- Work:
  - `labels.py`: the 17 built-in names (pt-BR exactly as in T11.3), the categories, the movement kinds, the lot statuses and every error code of T11.5 and T11.6, with the configuration fallback of `ui/infrastructure/labels.py`. A built-in type shows its translated name; a user type shows its own label with the fallback of §6.
  - `models.py`: table models for lots (type, lot, received, expiry, on hand, status, days to expiry, unit price, value), movements (date, kind, signed quantity, balance after, reference, note), the summary (type, category, valid, expired in stock, expiring, minimum, below minimum, valid value), the expiry schedule and the stock types. Status columns show text plus icon plus colour (D23): valid is OK, expiring is warning, expired is critical, empty is "no target", not received is "no data"; below the minimum is critical, not below is OK, no minimum is "no target" with the text "Not set". Money is formatted with the shared money helper.
  - `dialogs.py`: a lot dialog (type among the active types of the allowed categories; a lot code with the hint "manufacturer lot or receipt reference; no clinical information"; an expiry date with a "No expiry date" check box that is disabled for antidotes and decontaminants; price and currency; notes; on creation also "Received on", "Initial quantity" and "Reference"), a movement dialog (date, kind, quantity from 1 to 1,000,000, reference, a note that is required for adjustments, and the information "On hand on %1: %2"; the default date is the as-of date or today, whichever is earlier), and a type dialog (code, category, three labels, minimum with a "Not set" special value, active; for a built-in type only the minimum and the active flag are enabled). Dialogs are non-modal (`open()` and delete on close) and confirm through `context.prompts`; there is no `QMessageBox`. An amount typed in one language is shown again when the language changes.
  - `reports/message_keys.py` gets the stock type, category and lot-status keys in the shared areas, so reports can label them without importing `ui/`.
- Accept:
  - every enum member and error code has a non-empty label in the three languages, and the built-in pt-BR names are exactly the owner's wording;
  - the models give the expected texts, icons and signed quantities for a fictitious lot with several movements;
  - the dialogs validate through the service and show its error texts; the "No expiry date" box is disabled for the two categories; the pseudo-locale walk passes on the three new dialogs;
  - the catalogue tests (completeness, sync, placeholders) pass for the new area.
- Check: `uv run pytest tests/ui/test_stock_labels.py tests/ui/test_stock_dialogs.py tests/i18n tests/ui/test_no_hardcoded_strings.py`

**T11.10 — Stock panel and the Infraestrutura tabs** (M) · Depends on: T11.9, T3.4 · **Status: done** (commit `2fbcb57`, with T11.8 and T11.14)
- Files: `ui/stock/panel.py`, `ui/infrastructure/page.py`, `i18n/infrastructure_*.ts`, `i18n/stock_*.ts`, `tests/ui/test_stock_panel.py`, `tests/ui/test_infrastructure_page.py` (extend).
- Work:
  - `StockPanel(context, categories)` is the one panel of D38: the summary table; a "Show empty lots" check box (off); the text "%n lot(s) shown"; the lots table with "Add lot", "Edit lot", "Delete lot" and "Record movement"; the caption "Movements of the selected lot" with the movements table and "Edit movement" and "Delete movement". It can take a type filter (`set_type_filter(code | None)`) and show an empty state (`set_no_match()`). The edit actions are disabled in read-only mode, and writes go through the shared change helper of the shell.
  - The Infraestrutura page gets two tabs: "Equipamentos e instalações (unidades)", with today's layout unchanged, and "Estoque (lotes)", with `StockPanel(categories=None)`. The "Tipo" filter above the tabs starts with "All types", then the asset types (data = the code, as today), a separator, then the stock types ordered by category and name (data `stock:<code>`). Choosing an asset type shows the first tab and filters assets; the stock panel shows its empty state. Choosing a stock type shows the second tab and filters the lots; the asset list shows 0 rows. "All types" filters nothing and keeps the current tab, and switching tabs by hand never changes the filter. The tab order is applied after the tabs are built.
- Accept:
  - the panel adds, edits and deletes a lot and a movement through the service, shows the balance after each movement, and hides empty lots until the box is checked;
  - the refusals of the service (negative balance, future date) appear as texts and change nothing;
  - the filter behaviour of the page matches the description above, including a stock type chosen while the first tab is shown, and a language switch that keeps the choice;
  - the existing Infraestrutura tests pass unchanged;
  - read-only mode disables every edit action.
- Check: `uv run pytest tests/ui/test_stock_panel.py tests/ui/test_infrastructure_page.py tests/ui/test_no_hardcoded_strings.py`

**T11.11 — The page "Antídotos e descontaminantes"** (M) · Depends on: T11.8, T11.10 · **Status: done** (commit `9a2ca74`, with T11.12, T11.13 and T11.15)
- Files: `ui/antidotes/__init__.py`, `ui/antidotes/page.py`, `ui/shell/registry.py` (key `antidotes`, order 25), `ui/shell/formatting.py` (`format_month`), `ui/alerts/models.py` (navigation), `i18n/__init__.py` (area `antidotes` with the folder `ui/antidotes`, context `Antidotes`), `i18n/antidotes_*.ts`, `help/{pt_BR,en_US,es_ES}.md` (the topic `antidotes`), `docs/manual-test-script.pt-BR.md`, `tests/meta/test_release_readiness.py` (`PAGE_TITLES`), `tests/ui/test_antidotes_page.py`, `tests/ui/test_shell_formatting.py`.
- Work:
  - The page header reads "Situação em %1", with the note "Dados de gestão: quantidades, lotes, validades e preços." (D19). Its own "Tipo" filter starts with "Todos os antídotos e descontaminantes" and lists the types of those two categories (active ones, and inactive ones that have lots).
  - Three tabs. "Lotes e movimentações" is `StockPanel` over antidotes and decontaminants. "Aprazamento de vencimentos" has a horizon box (6, 12 or 24 months, 12 by default) and a table of period, type, lot, expiry, on hand and status (text plus icon); the periods are "Vencidos (ainda em estoque)", one per month, "Mais tarde" and "Sem validade". Month names come from a new `format_month(date, language)`, tested with exact strings in the three languages. A chart is optional and may be deferred. "Alertas" lists the stock alerts of the page's categories for the as-of date, and "Abrir registro" selects the lot in the first tab (for a lot alert) or sets the type filter (for a type or indicator alert).
  - The page is registered with its title "Antídotos e descontaminantes" (the pt-BR catalogue holds exactly that text, as the readiness test reads it), and `PAGE_TITLES` and the manual test script name it. The help gains the topic `antidotes` in all three languages with the same heading structure, with no clinical content and no links. The three languages call the tab "Aprazamento de vencimentos" / "Expiry schedule" / "Calendario de caducidades"; the pt-BR term is flagged for Q14.
- Accept:
  - the page shows only the two categories, with the filter, the three tabs and the as-of date of the shell;
  - the schedule puts a fictitious lot in the right bucket across a month and a year boundary, and the horizon box changes the number of months;
  - "Abrir registro" lands on the right lot or filter, and the alerts page opens the antidotes page for a lot alert of an antidote or decontaminant;
  - `format_month` gives the expected strings in pt-BR, en-US and es-ES;
  - the registry, readiness and help tests (every page named in the manual script and in the help; the three help files with the same headings) pass.
- Check: `uv run pytest tests/ui/test_antidotes_page.py tests/ui/test_shell_formatting.py tests/ui/test_help_and_about.py tests/meta/test_release_readiness.py tests/ui/test_no_hardcoded_strings.py`

**T11.12 — Dashboard shortcut and stock chart** (M) · Depends on: T11.7, T11.11, T6.5 · **Status: done** (commit `9a2ca74`, with T11.11, T11.13 and T11.15)
- Files: `ui/dashboard/page.py`, `ui/dashboard/labels.py`, `services/dashboard.py`, `i18n/dashboard_*.ts`, `tests/ui/test_dashboard_page.py`, `tests/services/test_dashboard_service.py`.
- Work:
  - A navigation action "Abrir antídotos e descontaminantes" in the header row beside "Record snapshot". It is a plain action, not an edit action, so it stays enabled in read-only mode; it checks that the page key is registered and then asks the window to show the page `antidotes`. There is no global shortcut.
  - The stock tiles form the group "Estoque" through the existing grouping. The dashboard service adds the chart `stock_antidotes_by_item`: its categories are the antidote and decontaminant types that have a value, and its series are `stock_valid` and `stock_minimum` (a minimum that is not set is "not recorded", D30). Series keys are never `valid`.
- Accept: the action opens the page and is enabled in read-only mode; stock tiles appear only when stock indicators have values; the chart table view lists every type with its valid quantity and its minimum or "not recorded"; the dashboard tests for the other modules pass unchanged.
- Check: `uv run pytest tests/ui/test_dashboard_page.py tests/services/test_dashboard_service.py`

**T11.13 — Settings: stock types, P12 and P11** (M) · Depends on: T11.5, T11.9 · **Status: done** (commit `9a2ca74`, with T11.11, T11.12 and T11.15)
- Files: `ui/stock/settings.py`, `ui/settings/sections.py` (the third field of the alerts section), `i18n/settings_*.ts`, `i18n/stock_*.ts`, `tests/ui/test_stock_settings.py`, `tests/ui/test_settings_page.py`, `tests/ui/test_placeholder_confirmation.py`.
- Work:
  - A "stock types" section in the infrastructure group of Settings (registered by its own key, without editing the group registry): a table of types with "Add", "Edit" and "Deactivate", and "Delete" for user types only. It shows the "placeholder — to be confirmed" badge of P12 with a Confirm action, as the infrastructure section does for A06. Setting a minimum calls the service with the placeholder confirmation `P12`.
  - P11 becomes the third field of the alerts section, with its badge, saved through the config service.
- Accept: a minimum is set, changed and cleared, and the badge appears and disappears as for the other placeholders; a built-in type cannot be deleted or renamed; P11 is saved and changes the lot alerts for the next evaluation; read-only mode disables the sections; the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_stock_settings.py tests/ui/test_settings_page.py tests/ui/test_placeholder_confirmation.py`

**T11.14 — CSV export and import of stock** (M) · Depends on: T11.6, T8.3, T8.4 · **Status: done** (commit `2fbcb57`, with T11.8 and T11.10)
- Files: `storage/csv_io.py`, `services/export.py`, `services/importer.py`, `docs/import-templates.md`, `ui/reports/labels.py`, `tests/storage/test_csv_io.py`, `tests/services/test_importer.py`, `tests/services/test_export.py`.
- Work: three entities, in import order after `funding_source` and `budget_execution`:
  - `stock_item_type` (code, built-in, category, the three labels, minimum quantity, active; key: code), imported like asset types, including the refusal to change a built-in type;
  - `stock_lot` (type code, lot code, expiry date, unit price, currency, notes; key: type code and lot code), with a warning count `LOT_WITHOUT_MOVEMENTS` for a lot that has no movement (like the warning of T8.4);
  - `stock_movement` (type code, lot code, date, kind, quantity, reference, note; key: all but the note, with `''` for an empty reference).
  - The importer applies the movements of a lot in the order of date, then inflows before outflows, then file line. `BALANCE_NEGATIVE` and `DATE_IN_FUTURE` are reported on the offending file line, and the import stays atomic. Entity labels and the new error codes are added to the reports UI labels and to the import templates document.
- Accept: a round trip (export, import into an empty database) gives the same lots, movements and quantities; a file whose movements make a balance negative is refused as a whole with the line number; a movement in the future is refused; a lot without movements gives the warning; a built-in type cannot be altered; export cells are protected against formula injection as in T8.3.
- Check: `uv run pytest tests/storage/test_csv_io.py tests/services/test_importer.py tests/services/test_export.py`

**T11.15 — Reports: stock in the internal and the anonymised report** (M) · Depends on: T11.7, T11.8, T8.6 · **Status: done** (commit `9a2ca74`, with T11.11, T11.12 and T11.13)
- Files: `reports/model.py`, `reports/anonymise.py`, `reports/labels.py`, `reports/message_keys.py`, `reports/pdf.py`, `i18n/reports_*.ts`, `i18n/reportsui_*.ts`, `tests/reports/test_report_model.py`, `tests/reports/test_report_pdf.py`, `tests/reports/test_report_anonymise.py`.
- Work:
  - `Cell` gains `internal_only: bool = False`. A key-figure group for `Module.STOCK` has the counts of expired lots, expiring lots and types below the minimum, and, per currency, the valid and the expired stock value (not counts, internal only). The `STOCK_VALID_QTY` cells and the stock chart are internal only. `ReportDocument` gains `stock_lots` (the expired and expiring lots with stock, internal only; empty by default).
  - The anonymised report drops every internal-only cell, row and chart and empties `stock_lots` (D37); it keeps the lot counts, the counts of types below the minimum and the stock alert counts. A test checks that no total in it contains an internal-only cell. The "not covered" note of the module names Q27.
  - The PDF formats the stock values as money and has a section "Lotes vencidos ou a vencer com estoque" in the internal report. Labels: the stock module, the four indicator names, the dimension names "Categoria" and "Item", the chart series and the alert source.
- Accept: the internal report shows the stock figures, the chart and the list of lots; the anonymised report shows none of the quantities, values or prices of any type, only the counts; two currencies are never added; the report tests for the other modules and the anonymisation tests pass unchanged; the PDF opens in three languages.
- Check: `uv run pytest tests/reports`

**T11.16 — Demo data and walkthrough for stock** (M) · Depends on: T11.8, T11.11, T11.12, T10.1 · **Status: done** (commit `2147d1e`)
- Files: `demo/stock.py`, `demo/__init__.py` (registered after the budget and before the targets), `docs/demo-walkthrough.md`, `tests/demo/test_demo_stock.py`, `tests/demo/test_demo_complete.py`, `tests/ui/test_demo_walkthrough.py`.
- Work: the demo writes through `StockService` with the operator `DEMO`, with dates relative to the day the demo is made and none after it. It creates:
  - "Antídoto Químico": `DEMO-L001` valid (expires in 400 days; 50 received 200 days ago, 5 issued 30 days ago), `DEMO-L002` expiring (in 20 days, 10 on hand), `DEMO-L003` expired (15 days ago, 4 still on hand, so `LOT_EXPIRED`) and `DEMO-L004` empty (10 received, 10 disposed of after the expiry);
  - "Antídoto Radiológico e Nuclear" with a minimum of 20 and a valid quantity of 8 (`LOW_STOCK`); "Antídoto Biológico" with a minimum of 5, a valid quantity of 12, and a loss, an adjustment in and an adjustment out with notes; "Descontaminante" with one valid and one expiring lot, one priced in USD;
  - a "Detector Químico" lot with no expiry, one expiring lot each of "EPI nível A" and "Luva", small no-expiry lots of "Cilindro de O2" and "Maca Bolha (Cápsula de Isolamento para Transporte)", one lot with no price, and one lot first received 10 days ago (so it shows as not received 30 days ago);
  - a user type `DEMO-ANTIDOTE-X` whose pt-BR label starts with "DEMO", category antidote.
  - The minimums exist in the demo database only (D25) and P12 is not confirmed. The walkthrough gains the sections "Infraestrutura → Estoque (lotes)" and "Antídotos e descontaminantes" with the expected states.
- Accept: every lot shows the status above; the alerts include each stock kind; the demo antidotes page, the Infraestrutura stock tab and the dashboard tiles show rows; every identifier starts with `DEMO`; a real database created after a demo run has no stock rows and no minimum.
- Check: `uv run pytest tests/demo tests/ui/test_demo_walkthrough.py`

**T11.17 — Help and reference documentation for stock** (S) · Depends on: T11.11, T11.14, T11.15 · **Status: done** (commit `57b6b44`)
- Files: `help/{pt_BR,en_US,es_ES}.md` (the topic `infrastructure_stock`, under Infraestrutura), `docs/architecture.md`, `docs/data-protection.md`, `docs/indicators.md`, `docs/import-templates.md`, `README.md`, `tests/ui/test_help_and_about.py`, `tests/meta/test_docs.py`.
- Work: the help gets "### Estoque (lotes)" with the same heading structure in the three languages, no clinical content and no links. The architecture document gets the new packages, the three tables and the catalogue areas; the data-protection guide says that stock data is covered by the same handling as the other data and that the anonymised report omits per-type quantities (Q27); the README lists the stock feature.
- Accept: the help tests (same headings, no external link) and the documentation tests pass.
- Check: `uv run pytest tests/ui/test_help_and_about.py tests/meta/test_docs.py tests/meta/test_readme.py`

**T11.18 — Accessibility, pseudo-locale and read-only QA for stock** (M) · Depends on: T11.10, T11.12, T11.13, T11.14, T11.15, T11.16 · **Status: done** (T11.18 QA fixes commit)
- Files: `ui/**` (adjustments), `tests/ui/test_accessibility.py`, `tests/ui/test_no_hardcoded_strings.py`, `tests/ui/_scale_probe.py`, `tests/ui/test_stock_readonly.py`.
- Work: walk the new page, the stock tab, the three stock dialogs and the Settings section. Every interactive widget has an accessible name or a buddy label; every status shows text; every action has a mnemonic or a shortcut; a sensible tab order; the pseudo-locale walk finds no hard-coded text; the page opens with `QT_SCALE_FACTOR=2` without Qt warnings; in read-only mode every write action is disabled while the navigation action of the dashboard stays enabled.
- Accept: the walks above pass with the new page and dialogs included (`stock.lot`, `stock.movement` and `stock.type` use fictitious data); a language switch with a dialog open keeps its content.
- Check: `uv run pytest tests/ui/test_accessibility.py tests/ui/test_no_hardcoded_strings.py tests/ui/test_stock_readonly.py`

**T11.19 — Release 1.1.0** (S) · Depends on: every task of Phase 11
- Files: `CHANGELOG.md`, `README.md`, `docs/manual-test-script.pt-BR.md`, `docs/smoke-test.pt-BR.md`, `tests/meta/test_release_readiness.py`, `PLAN.md` (status of Phase 11; §3.5 and §12 with the status of each answer received, never its content).
- Work:
  - The 1.1.0 changelog entry says what ships (replacing "Planned for 1.1.0"), lists exactly the placeholders still flagged (including P11 and P12, with P12 marked local-only), the assumptions without a setting (A15 and A16), the status of Q1–Q29, the number of unfinished translation messages found, and the one-time change of the configuration hash (K21). Answers to Q25–Q29, if any arrive, are recorded as a status only.
  - The manual test script gets the stock steps for the demo data; `docs/smoke-test.pt-BR.md` stays correct for 1.1.0.
  - Run the full default and packaging suites; a person tags `v1.1.0`, runs the manual test on a clean Windows profile and publishes the draft release. The entry gets its date only then.
- Accept: the readiness tests pass (the entry lists the placeholders found in code, the question statuses of Q1–Q29 and the count of unfinished messages found); the default suite and the packaging suite pass; the frozen self-test passes with the stock tables present.
- Check: `uv run pytest tests/meta/test_release_readiness.py`, then `uv run pytest` and `uv run pytest -m packaging`

#### Phase 12 — Notice removal (1.2.0)
This phase implements D39 (owner decision of 2026-11-24). It removes the preliminary-version notices, the warning against entering real data, the placeholder badges and the Confirm actions, and clears the placeholder flags. It is a separate release, 1.2.0, that follows 1.1.0. It is not a claim of institutional homologation (R30, K25) and it records only the status of each answered question, never the content of an answer.

Rules that hold for every task of the phase:
- Kept: the DEMO banner and the `DEMO` identifiers (D25), the data-protection notice without the gate sentence, the "sensitive is a working label, not a formal classification" sentence (§7.1), and the rule that no real data enters the repository (F05, K04).
- The local-only values P03, P10, D18 and P12 keep empty code defaults and are set per installation in Settings; they are not shown as placeholders.
- Done tasks of earlier phases are not rewritten; this phase supersedes their notice and badge requirements (D39).
- No wording anywhere states that the tool is validated, approved or homologated.
- The snapshot configuration hash does not change: no hashed field is added, removed or given a new default (K24; see T12.12 and T12.13).

**T12.1 — Open the 1.2.0 cycle** (S) · Depends on: T11.19 · **Status: done**
- Files: `src/cbrn_dashboard/__init__.py`, `README.md`, `CHANGELOG.md`, `docs/`, `tests/meta/test_release_readiness.py`.
- Work: set the version to 1.2.0; name 1.1.0 as the last published version where the documents and the readiness tests do so; add an unreleased `1.2.0` changelog entry that says what has not happened (no tag, no workflow run, no manual test).
- Accept: the readiness tests pass for 1.2.0 and the changelog entry states that it is not published.
- Check: `uv run pytest tests/meta/test_release_readiness.py`

**T12.2 — Plan amendments D39 and Phase 12** (S) · Depends on: T12.1 · **Status: done**
- Files: `PLAN.md`.
- Work: add D39 (§3.4), the notes on I06, P07 and D28, K24 and K25 (§11), §13.2, this phase and its sizing row (§10.4). §3.5, §7.1, §12, K12 and K19 are not touched here; T12.13 and T12.14 do that.
- Accept: `PLAN.md` has D39, K24, K25, §13.2 and T12.1–T12.15, and the question statuses are unchanged.
- Check: `uv run pytest tests/meta`

**T12.3 — No preliminary notice in reports** (S) · Depends on: T12.2 · **Status: pending**
- Files: `reports/model.py`, `reports/message_keys.py`, `reports/labels.py`, `reports/pdf.py`, `reports/anonymise.py`, `tests/reports/`.
- Work: remove `ReportDocument.preliminary_notice_code`, `PRELIMINARY_NOTICE_CODE`, `ReportTexts.preliminary_notice`, `PRELIMINARY_KEY`, the PDF notice box and the footer notice; keep the footer rule and "Page %1 of %2".
- Accept: neither report model nor PDF text carries a preliminary notice; every page still has the footer rule and the page counter.
- Check: `uv run pytest tests/reports`

**T12.4 — Shell without the preliminary banner** (S) · Depends on: T12.2 · **Status: pending**
- Files: `ui/shell/`, `ui/help/` (or the equivalent module), `help/{pt_BR,en_US,es_ES}.md`, `i18n/` catalogues of the `shell` area, `tests/ui/test_shell.py`, `tests/ui/test_help_and_about.py`.
- Work: remove the PRELIMINARY banner, the About line and the help topic "preliminary" in the three languages; the DEMO banner stays permanent in demo mode (D25). Q15 is answered and implemented here.
- Accept: no banner, About line or help topic mentions a preliminary version; the DEMO banner is still shown in demo mode; the help has the same headings in the three languages.
- Check: `uv run pytest tests/ui/test_shell.py tests/ui/test_help_and_about.py`

**T12.5 — Lift the real-data gate in the app** (S) · Depends on: T12.2 · **Status: pending**
- Files: `ui/shell/` (first-run notice), `help/{pt_BR,en_US,es_ES}.md` (privacy topic), `i18n/` catalogues, `tests/ui/test_first_run_and_location.py`, `tests/ui/test_help_and_about.py`.
- Work: the first-run classification paragraph keeps only the sentence that "sensitive" is a working label, not a formal classification; the help privacy topic loses the warning against real data. Q19, Q4, Q11 and Q13 are answered and implemented here.
- Accept: no text in the app tells the operator to wait for an answer before entering real data; the working-label sentence is still shown.
- Check: `uv run pytest tests/ui/test_first_run_and_location.py tests/ui/test_help_and_about.py`

**T12.6 — Shipped notes without notices** (S) · Depends on: T12.2 · **Status: pending**
- Files: `packaging/README-first-run.*.txt`, `packaging/installer/cbrn-dashboard.iss`, `.github/release-body.template.md`, `tests/packaging/`.
- Work: remove the preliminary notice and the gate sentence from the first-run notes, the installer before-install notices and the release body template; the template keeps the unsigned-executable statement, the checksum and attestation text, the source links and the written offer (D10, §8).
- Accept: no shipped note mentions a preliminary version or the gate; the checksum and licence statements are unchanged.
- Check: `uv run pytest tests/packaging tests/meta/test_release_readiness.py`

**T12.7 — Settings General, Alerts and Targets without badges** (M) · Depends on: T12.2 · **Status: pending**
- Files: `ui/settings/sections.py`, `ui/settings/page.py`, `i18n/` catalogues of the `settings` area, `tests/ui/test_settings_page.py`, `tests/ui/test_placeholder_confirmation.py` (deleted).
- Work: remove the badges and Confirm actions of the General, Alerts and Targets sections; delete `PlaceholderBadge` and `tests/ui/test_placeholder_confirmation.py`. Saving, validation and the local-only fields behave as before.
- Accept: the three sections show no badge or Confirm action; every field still saves and reloads; `PlaceholderBadge` no longer exists.
- Check: `uv run pytest tests/ui/test_settings_page.py`

**T12.8 — Stock item types without the P12 badge** (S) · Depends on: T12.7 · **Status: pending**
- Files: `ui/settings/` (stock types section), `tests/ui/test_stock_settings.py`.
- Work: remove the P12 badge from the stock item types section; the minimum stays an empty-by-default, per-installation value (D35).
- Accept: the section shows no badge; a minimum still saves and clears.
- Check: `uv run pytest tests/ui/test_stock_settings.py`

**T12.9 — Personnel and Infrastructure sections without badges** (S) · Depends on: T12.7 · **Status: pending**
- Files: `ui/settings/` (personnel and infrastructure sections), `tests/ui/test_settings_page.py`.
- Work: remove the badges and Confirm actions of the two sections.
- Accept: neither section shows a badge or Confirm action; their fields behave as before.
- Check: `uv run pytest tests/ui/test_settings_page.py`

**T12.10 — Budget and Backup sections without badges** (S) · Depends on: T12.7 · **Status: pending**
- Files: `ui/settings/` (budget and backup sections), `tests/ui/test_settings_page.py`.
- Work: remove the badges and Confirm actions of the two sections.
- Accept: neither section shows a badge or Confirm action; their fields behave as before.
- Check: `uv run pytest tests/ui/test_settings_page.py`

**T12.11 — Reports and Snapshots sections and help texts without badges** (S) · Depends on: T12.7 · **Status: pending**
- Files: `ui/settings/` (reports and snapshots sections), `help/{pt_BR,en_US,es_ES}.md`, `i18n/` catalogues, `tests/ui/test_settings_page.py`, `tests/ui/test_help_and_about.py`.
- Work: remove the badges and Confirm actions of the two sections; remove the sentences about badges and confirmation from the help texts in the three languages.
- Accept: no section and no help text mentions a badge, a placeholder flag or a confirmation.
- Check: `uv run pytest tests/ui/test_settings_page.py tests/ui/test_help_and_about.py`

**T12.12 — Services and storage: delete the confirmation machinery** (M) · Depends on: T12.7, T12.8, T12.9, T12.10, T12.11 · **Status: pending**
- Files: `storage/settings_repo.py`, `services/settings_service.py`, `tests/storage/test_settings_repo.py`, `tests/services/`.
- Work: delete the `confirmed.<ID>` keys handling, the confirmation functions and their call sites. Existing `confirmed.<ID>` rows in `app_settings` stay unused: no migration, no deletion. The snapshot configuration hash does not change (no hashed field is touched; K24).
- Accept: no code reads or writes `confirmed.<ID>`; a database with such rows opens and works; a snapshot taken before and after the change has the same configuration hash.
- Check: `uv run pytest tests/storage/test_settings_repo.py tests/services`

**T12.13 — Clear every placeholder flag and withdraw P07** (M) · Depends on: T12.12 · **Status: pending**
- Files: `domain/config.py`, `PLAN.md` (§3.5), `docs/indicators.md`, readiness rules in `tests/meta/`, `tests/domain/`.
- Work: clear the placeholder flag of every generic default (they become confirmed code defaults) and of the local-only values P03, P10, D18 and P12, which keep empty code defaults; withdraw P07 and remove it from the registry; update §3.5, `docs/indicators.md` and the readiness rules that list flagged placeholders. The `ReadinessConfig()` defaults test and the snapshot configuration hash do not change (K24).
- Accept: no placeholder flag is set; `flagged_placeholder_ids()` is empty; the plan and the code agree on §3.5; the defaults test and the hash test pass unchanged.
- Check: `uv run pytest tests/domain tests/meta/test_placeholders_documented.py tests/meta/test_docs.py`

**T12.14 — Documentation, question statuses and the no-notice guard** (M) · Depends on: T12.3, T12.4, T12.5, T12.6, T12.13 · **Status: pending**
- Files: `PLAN.md` (§3.5, §7.1, §12, K12, K19), `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/`, `tests/meta/`.
- Work: set the status of Q15 to "answered and implemented in task T12.4" and of Q19, Q4, Q11 and Q13 to "answered and implemented in task T12.5", never the content of an answer; update §7.1, K12 and K19 and the documents that name the notice or the gate; add a no-notice guard test in `tests/meta` that scans the sources, catalogues, help, shipped notes and templates for the removed notices and for validation claims, and allows the DEMO banner and the working-label sentence.
- Accept: the guard test and the readiness tests pass; the documents state no gate and no preliminary notice; no answer content is recorded.
- Check: `uv run pytest tests/meta`

**T12.15 — Release 1.2.0** (S) · Depends on: every task of Phase 12 · **Status: pending**
- Files: `CHANGELOG.md`, `README.md`, `docs/manual-test-script.pt-BR.md`, `docs/smoke-test.pt-BR.md`, `tests/meta/test_release_readiness.py`, `PLAN.md` (status of Phase 12).
- Work: the 1.2.0 changelog entry says what ships, lists the local-only values with empty code defaults (P03, P10, D18, P12), the assumptions without a setting, the status of Q1–Q29 and the number of unfinished translation messages. Run the full default and packaging suites; a person tags `v1.2.0`, runs the manual test on a clean Windows profile and publishes the draft release. The entry gets its date only then.
- Accept: the readiness tests pass; the default suite and the packaging suite pass; the frozen self-test passes.
- Check: `uv run pytest tests/meta/test_release_readiness.py`, then `uv run pytest` and `uv run pytest -m packaging`

### 10.4 MVP cut, deferred work and sizing

**MVP v0.1** consists of Phases 0–7 (T0.1–T7.5) plus T8.1 (readiness snapshots), T9.2 (licence bundle), T9.3 (release pipeline), T9.4 (first-run notes and the portable example) and T9.6 (the v0.1.0 release). It contains:
- all five modules of L74–L82, with data entry, editing, deactivation and deletion, and the change log;
- every indicator of §5.4, evaluated for any as-of date from the records as known today, with configurable targets (none by default);
- the alerts of §5.5, the dashboard with tiles, charts and table views, and the start-up summary;
- the trilingual interface with live switching;
- placeholders flagged in Settings;
- readiness snapshots (manual, monthly and retroactive, never deletable, only withdrawn), recorded from the first release;
- local storage in the profile, read-only handling, location warnings and the first-run notice;
- automatic local backups, encrypted manual backups and restore;
- the demo mode;
- the one-folder executable with self-test, bundled licences, first-run notes in three languages, checksums and a provenance attestation, released as a draft pre-release. The install guides (T10.3) and the About dialog (T10.2) arrive in v1.0.

That is enough for the committee to review the indicators and placeholders with demo data, and to start entering real data on their own machine once the questions that gate real data are answered: the formal-classification question (Q19), Q4, Q11 and Q13 (§12). "Sensitive" is a working label, not a classification (§7.1).

**v1.0** adds:
- the rest of Phase 8 (T8.2–T8.7): the validation export, CSV export and import, and PDF reports, internal and anonymised, with the snapshot and settings user interface (T8.1 is in the MVP);
- T9.1 (final build and bundle checks) and T9.5 (Dependabot);
- Phase 10 (T10.1–T10.5): the complete demo, help and About, the reference documentation, the accessibility pass and the release candidate.

**Deferred beyond v1.0.** Each item is started only if an answer in §12 or field use asks for it.

| ID | Item | Trigger | Related |
|---|---|---|---|
| X1 | Encryption of the live database (SQLCipher or an app-level encrypted file) | Q11 requires it | D03 |
| X2 | Several users editing shared data (needs an architecture other than SQLite on a file share) | Q12 | D05, A12 |
| X3 | XLSX export | Q10 | D09 |
| X4 | Composite readiness score with an agreed formula and weights | Q9 | §5.4 |
| X5 | One-file executable variant | Q13 | D01 |
| X6 | Code signing (open-source signing programme or paid certificate) | Q13 | D10 |
| X7 | Alert acknowledgement and snooze, and Windows notifications (local only, no network) | field use | §5.5 |
| X8 | Change-log redaction and retention tool | Q12 | D05 |
| X9 | Replace the chart backend: either accept QtQml/QtQuick in the bundle for Qt Graphs, or draw the bar charts with `QPainter` inside the adapter | Qt Charts deprecation (removal or breakage) | D08, K09 |
| X10 | Breakdowns of exercise participants (for example by role or origin), still as counts only | Q7 | D20 |
| X11 | Dark and high-contrast themes beyond the OS default | field use | D23 |
| X12 | macOS and Linux builds | demand | §2.2 |
| X13 | Argon2id key derivation for encrypted backups, instead of scrypt | Q11 requires it | D04 |

**X6 status:** integration prepared (SignPath Foundation OSS program); not active until the project is accepted. The release workflow has an optional `sign` job that is skipped while the repository variable `SIGNPATH_ORGANIZATION_ID` is empty, so releases stay unsigned (D10). Only `cbrn-dashboard.exe` is signed (`.signpath/artifact-configurations/release.xml`); the policy page is `CODE-SIGNING-POLICY.md`.

**X5 status:** a one-file executable is still deferred. What exists instead is a per-user **installer**: the release workflow builds `cbrn-readiness-dashboard-<version>-win-x64-setup.exe` with Inno Setup 6 from the tested one-folder bundle on every release (`packaging/installer/cbrn-dashboard.iss`, `scripts/build_installer.py`), smoke-tests it (silent install, frozen self-test, silent uninstall that keeps the data), checksums and attests it. It needs no administrator rights, so Q13 does not have to be answered for a single download, and it keeps the one-folder build (D01). The installer is not signed (X6 signs `cbrn-dashboard.exe` only).

**Sizing.** Sizes use the labels of §10.1 (S ≈ under 200 changed lines, M ≈ 200–600, L ≈ over 600). There are no L tasks: everything larger was split.

| Phase | Tasks | S | M | Release |
|---|---|---|---|---|
| 0 Scaffolding | 9 | 5 | 4 | MVP |
| 1 Foundations | 10 | 5 | 5 | MVP |
| 2 Personnel | 5 | 2 | 3 | MVP |
| 3 Infrastructure | 5 | 2 | 3 | MVP |
| 4 Exercises | 6 | 3 | 3 | MVP |
| 5 Budget | 5 | 4 | 1 | MVP |
| 6 Indicators, alerts, dashboard | 6 | 2 | 4 | MVP |
| 7 Backup and data protection | 5 | 2 | 3 | MVP |
| 8 Reports, import/export, snapshots | 7 | 2 | 5 | T8.1 MVP; T8.2–T8.7 v1.0 |
| 9 Packaging and release | 6 | 3 | 3 | T9.2, T9.3, T9.4, T9.6 MVP; T9.1, T9.5 v1.0 |
| 10 Documentation and v1.0 | 5 | 2 | 3 | v1.0 |
| 11 Stock by lot, antidotes and decontaminants | 19 | 5 | 14 | 1.1.0 |
| 12 Notice removal | 15 | 11 | 4 | 1.2.0 |
| **Total** | **103** | **48** | **55** | MVP 56 tasks (27 S, 29 M); v1.0 adds 13 (5 S, 8 M); 1.1.0 adds 19 (5 S, 14 M); 1.2.0 adds 15 (11 S, 4 M) |

Honest remarks on size:
- The MVP is about four fifths of the task count of v1.0 (56 of 69). Phase 11 adds 19 tasks for 1.1.0 and Phase 12 adds 15 for 1.2.0, so the plan has 103 tasks in all.
- The longest chain of tasks that must run one after another is 16 tasks (§10.2): T0.1 → T0.5 or T0.6 → T0.7 → T1.3 → T1.4 → T1.8 → T1.9 → a module UI task (T2.4, T3.4, T4.5 or T5.4) → T6.1 → T6.2 → T6.5 → T8.5 → T8.6 → T8.7 → T10.2 or T10.4 → T10.5. The branch T6.5 → T8.1 → T8.2 → T8.7 is equally long. The documentation branch T9.3 → T9.4 → T10.3 → T10.5 is shorter. Running modules and Phase 7 in parallel shortens the elapsed time, but not this chain.
- The UI tasks carry most of the effort and most of the translation work. Each UI task also adds translations in three languages, which the committee still has to review (Q14).
- Answers to §12 may add work. Most answers are applied in Settings without code: P01–P06, P08, P09, targets, A02, A04, A05, A06 intervals, A07 metrics, A09 courses and the A11 threshold. P07 (the disclaimer wording) lives in the translations and needs a commit. A01, A03, A12, A13 and A14 have no setting: they are assumptions, and an answer that contradicts them, like one that contradicts A08 or A10 or requests X1–X6, needs new tasks. Clearing a placeholder flag in `domain/config.py` is always a commit (§3.5).
- No calendar estimate is given. Agent throughput and review time are unknown, and the institutional steps (§10.5) dominate the elapsed time.

### 10.5 Relation to the appendix timeline
The appendix describes the process as requirements gathering with the committee, incremental prototyping, tests with retroactive 2022–2025 data, and institutional homologation (L87), with an estimate of twelve to eighteen months for the whole process (L91). This plan fits into that process as follows.

- **Requirements gathering (R28).** The open questions of §12 are the agenda. The MVP is designed so the committee can answer most of them by changing Settings and reviewing the placeholders, rather than by waiting for code.
- **Incremental prototyping (R28).** MVP v0.1 (T9.6), any point releases, then v1.0. Each release is a draft GitHub release with checksums; releases below 1.0.0 are marked pre-release. Feedback goes into §3.5, §12 and new tasks.
- **Retroactive tests, 2022–2025 (R29).** On the committee's own machine, records are entered by hand or imported from CSV (T8.4, with templates matched to the existing records' structure — Q16). The indicators are then read for past as-of dates (I03), and retroactive snapshots (T8.1) record those readings. Snapshots are available from v0.1.0, so readings can be recorded early; CSV import follows in v1.0. The data never enters the repository (F05).
- **Predictive validity (R31).** The comparison needs snapshots taken before the next EXBRAMED edition and that edition's evaluation results, which the validation export (T8.2) joins. It therefore cannot be completed before that edition has taken place. The plan assumes no date for it.
- **Homologation (R30).** This is an institutional step after v1.0 and outside the software. v1.0 is handed over as a preliminary, not yet validated tool (I06).
- **Duration (R34).** The twelve to eighteen months of L91 are the appendix's estimate for the whole process, of which software development is one part. The plan makes no calendar commitment. Outside the software, the critical path is answering §12, entering the retroactive data and the institutional steps.
- **Partner team (R32).** The task breakdown, the architecture notes (T10.3) and the contribution rules (T0.3) let any development team — including a partner institution, as the appendix suggests (L91) — continue the work.

---

## 11. Risks and mitigations
Likelihood and impact are rated H (high), M (medium) or L (low).

| ID | Risk | L / I | Mitigation | Related |
|---|---|---|---|---|
| K01 | Domain questions stay unanswered: indicators, targets, validity periods, meaning of "available", budget stages. This could cause rework or leave a tool that nobody trusts. | H / M | Every rule is configurable and every placeholder is flagged in Settings. The MVP is delivered early so the committee can answer by trying it. §10.4 lists which answers need only Settings and which need code. No readiness target is invented (P03). | §3.5, §12 Q1–Q9 |
| K02 | The unsigned executable is blocked or warned against: SmartScreen, Smart App Control (no per-file bypass), AppLocker/WDAC (default rules allow only Windows, Program Files and administrators; hash rules are per file and per release and must cover `.pyd` and DLL files), antivirus false positives, or Mark-of-the-Web inherited on extraction. On a locked-down machine the tool may simply not run. | H / H | One-folder build without UPX (D01). Published SHA-256 checksums, a per-file manifest of the bundle and a provenance attestation (T9.3); the checksums prove transfer integrity, not authenticity. In the MVP, the first-run notes in three languages (T9.4); from v1.0, install guides in three languages, including an allowed extraction folder and allow-listing by file hash for IT teams (T10.3). Code signing stays deferred (X6) until Q13 is answered. | D01, D10, Q13 |
| K03 | Sensitive data leaves the machine through the network, cloud sync, unencrypted copies, exports or external reports. | M / H | No network code, enforced by test (T0.4, including hand-offs to the shell), and no Qt network or web libraries in the bundle (T9.1). Data lives in the profile, with warnings for OneDrive and network paths (D02, T7.5), also for the output paths of reports and exports (T8.7). Manual backups are encrypted (T7.2). External reports are anonymised with small-count suppression, secondary suppression and suppressed charts (T8.5). Residual: differencing between successive anonymised reports can reveal a suppressed count (Q10); the validation export is unsuppressed internal data unless the option is used (T8.2). | F02, F05, §7 |
| K04 | Real data enters the public repository through commits, test fixtures, issues or screenshots. | M / H | Ignore rules and a hygiene test over tracked files (T0.3). Contribution rules, a pull-request checklist and an issue-template warning. Demo data only, with `DEMO` identifiers and a separate file (D25). Data lives outside the working copy by default (D02). | F05, T0.3 |
| K05 | The only copy of the data is lost: disk failure, corruption, a failed migration, a bad restore, or a mandatory, roaming or non-persistent (VDI) Windows profile that discards `%LOCALAPPDATA%` at logoff. | M / H | Rollback journal with `synchronous=FULL` (D06). Automatic daily backups and a separate pre-migration pool that daily backups never rotate out, each copy checked with `quick_check` before an older one is deleted (T7.1). Restore validates first, keeps a safety copy and copies into the live database with SQLite's backup API (not an atomic swap), after closing other connections and under a single-instance lock; any failure leaves the current database untouched (T1.9, T7.3). A reminder banner appears when the last encrypted backup is old (P09). The documentation tells users to keep encrypted backups on separate media; the profile type is asked in Q13. | I02, D04, Q13 |
| K06 | A backup passphrase is forgotten, so the encrypted backup cannot be read. | M / M | The passphrase is entered twice, with a minimum length (P05, never below 12), a small strength rule and an explicit warning that it cannot be recovered (T7.4). The format tells a wrong passphrase from corruption (T7.2). The automatic local backups in the protected profile do not depend on a passphrase (T7.1). | D04, Q11 |
| K07 | The workstation has no full-disk encryption, so a lost device exposes the database. | M / H | A first-run notice and the data-protection guide state the requirement and its limits: the app cannot verify it and it does not protect exported files on removable media (T7.5). Data is minimised (D17). Database encryption (X1) is held ready behind `open_database()` in case Q11 requires it. | D03, Q11 |
| K08 | Translations are poor, or the terminology is inconsistent across pt-BR, en-US and es-ES. | M / M | Completeness, sync, placeholder and pseudo-locale tests (§6). Terms in English source strings are kept stable. The committee reviews the terminology before v1.0 (Q14), and the review status is recorded in the changelog (T10.5). | D07, Q14 |
| K09 | Qt Charts is deprecated since Qt 6.10 in favour of Qt Graphs, whose 2D graphs need Qt Quick/QML (excluded from the bundle) and are GPL-3.0 as well, so the replacement is not a local swap. | M / M | All charts go through one adapter, the single touch point (D08, T6.4). Every chart has a table view (T6.5). A deprecation warning, if any, is added to `qt_log_ignore` by exact text (T6.4). The PySide6 upper bound limits exposure (K17). Replacing the backend is deferred item X9. | D08 |
| K10 | Dependencies drift: PySide6, PyInstaller or Python changes break the build, or a dependency's licence changes. | M / M | `uv.lock` with hashes, pinned runner image and actions (T0.8). Dependabot pull requests run the packaging suite (T9.5). Frozen self-test in CI (T0.9, T9.1). The licence allow-list test fails on any disallowed or unknown licence (T9.2). | §4.2 |
| K11 | Scope creeps towards clinical or procedural content, which might import non-GPL text such as the WHO guide or internal documents. | M / H | Non-goal (§2.2) and design decision D19. Contribution rules and the pull-request checklist forbid it (T0.3). The help is written from scratch (T10.2). Anything clinical belongs to PTT 1, which is out of scope. | F06, D19 |
| K12 | The tool is read as institutionally validated, or its readings as an official readiness standard. | M / H | A permanent preliminary notice in the UI banner, every PDF page, the About dialog, the first-run notes and the release body (I06, P07). "No target" is the default status (D14). Indicator definitions are documented (T10.3). Snapshots record the configuration hash, the hashed configuration itself and the app version (T8.1). Homologation stays outside the software (R30). | I06, Q15 |
| K13 | Retroactive readings are mistaken for readings taken at the time, or a snapshot is removed to hide an unfavourable reading. | M / M | The service sets the origin `retroactive` whenever a snapshot is taken after its as-of date, whatever triggered it; snapshots cannot be updated or deleted (triggers), only withdrawn by an append-only record with a reason (T8.1). The validation export carries the origin, `taken_at_utc` and age of every reading, prefers non-retroactive, non-withdrawn snapshots, and ignores withdrawn ones (T8.2). | R29, R31 |
| K14 | The database is used from a network share, or by several people at once, and gets corrupted. | L / H | Network-path warning (D02, T7.5). Single-operator design (D05, A12) and a single-instance lock (T1.9). Shared use is deferred item X2 (Q12). | D02, D05 |
| K15 | The change log and the backups keep personal data after the record itself has been deleted or changed, and the LGPD right to erasure cannot be met by deleting a row. | M / H | Data minimisation (D17); no free-text notes columns; personal free-text values are not copied into the log (§5.1). A "pseudonymise person" action removes the identifier and free text while keeping history (T2.3). Values already written to backups persist until those backups are deleted; this is documented in the data-protection guide (T7.5). Retention is Q12; a redaction tool is deferred item X8. | D05, Q4, Q12 |
| K16 | Parallel coding agents conflict over migrations, catalogues or registries. | M / L | Reserved migration numbers (T1.3). One catalogue per area (D07). One-line registrations. Tasks that touch the same shared file (§10.2 hot spots, including the `shell` catalogue) merge one at a time. Rebase and run the full suite before merging (§10.2). | §10.1, §10.2 |
| K17 | Qt 6.12 is the last Qt release that supports Windows 10, so PySide6 is capped at `<6.13` while Windows 10 is a target; the cap blocks newer Qt fixes and may block Dependabot updates. | M / L | The constraint is explicit (T0.1, §4.2, §8). The yearly stack review (§4.2) checks whether Windows 10 is still a target. Dependabot pull requests run the packaging suite (T9.5). | §4.2, §8, K10 |
| K18 | Text extraction with pypdf from Qt-generated PDFs is unverified, and Qt's `QTextDocument.print()` has no per-page footer, so the PDF tests or the pagination may not work as planned. | M / L | T8.6 starts with a spike and paginates manually with `QPainter`. If extraction is unreliable, content assertions move to the Qt-free report model and the PDF test checks page count, page size and metadata only. | D09, T8.6 |
| K19 | The data, or part of it, is formally classified or access-restricted (Lei 12.527/2011, arts. 23–28, or military rules), and real data is entered into a design that is not suitable for it. | M / H | Q19 is first in §12 and gates the entry of real data, together with Q4, Q11 and Q13. §1, §7.1, §10.4, the first-run notice (T7.5) and the first-run notes (T9.4) say that "sensitive" is not a classification and that real data must not be entered until the question is answered. Until then only demo data is used. As the plan reads Lei 12.527/2011 art. 28 and Decreto 7.845/2012 art. 19, a classification is made by a formal decision of the competent authority; this is not legal advice, and the plan gives no legal conclusion. | F05, §7.1, Q19 |
| K20 | Clinical creep through the antidote and decontaminant stock: item names, lot codes or notes start to carry indications, doses or protocols, which would import clinical content (K11) and possibly non-GPL text. | M / H | The stock tables have no dose, indication or protocol column (D38). The built-in names are item types only. The lot-code input and the notes carry a hint that no clinical information belongs there. The help for the stock features is written from scratch and has no clinical content or links (T11.17). The non-goal of §2.2 is amended, not removed, and the pull-request checklist still forbids clinical content. | K11, D19, D38, §2.2 |
| K21 | Snapshots taken before 1.1.0 are not comparable with later ones: the configuration hash changes once on upgrade, because the hashed fields grow by `stock_expiry_warning_days` and `stock_item_type_minimum_quantity`, and the `STOCK_*` indicators are missing from older snapshots. | H / L | The change is documented in the changelog entry for 1.1.0 and in T8.1. T11.7 checks that an indicator missing from an older snapshot is read as "no data", never as zero. Old snapshots are not rewritten (they cannot be changed, K13). | K13, T8.1, T11.7 |
| K22 | Tile inflation: stock adds many tiles to the dashboard (one per item type, plus lot and minimum counts), and the committee stops reading it. | M / M | A `STOCK_VALID_QTY` value exists only for a type that is in use on the date or has a minimum (D36). Stock tiles form their own "Estoque" group. A fresh real database shows no stock tiles. The antidotes page and the dashboard shortcut carry the detail instead of the overview. | D36, T11.7, T11.12 |
| K23 | Stock data (quantities, expiry dates, prices, the lots that are short or expired) reaches third parties through reports, exports or backups, which would disclose readiness gaps. | M / H | Stock carries the "sensitive" working label (§7.1). The anonymised report omits per-type quantities, values and prices and the stock chart, and keeps only counts (D37, T11.15); a test checks that no total in it contains an internal-only cell. The internal report lists expired and expiring lots and is for internal use only. CSV export and backups follow the existing controls (§7.3). Whether the counts themselves are safe is Q27. | K03, D37, Q27 |
| K24 | Default drift: with the confirmations gone (D39), nothing pins a generic default on an existing database, so a later change of a code default silently changes the value on every installation that never saved that field. | M / M | Any change of a generic default needs a step that writes the old value to the existing databases, plus the existing `ReadinessConfig()` defaults test. T12.12 and T12.13 note that the configuration hash does not change. | D39, T12.12, T12.13 |
| K25 | Removing the notices is read as institutional homologation, or lifting the gate publicly reveals something about the answers to Q19, Q4, Q11 and Q13. | M / H | A no-notice guard test (T12.14). No wording that claims validation anywhere; R30 stays outside the software. Only the status of each question is recorded, never the content of an answer. | D39, R30, T12.14 |

Note on K02 (QA finding P9-02): the mitigation "allow-listing by file hash for IT teams", taken straight from the per-file manifest, is superseded. `SHA256-FILES.txt` is for verifying each extracted file; IT teams then make their allow-listing rules from the verified folder with their organisation's own policy tooling (T9.3). The same reading applies to D10, §8, T9.4 and T10.3.

---

## 12. Open questions for the author
"Committee" means the hospital's CBRN defence committee. Every question about the application has a working answer in the app (§3.5) until it is answered; Q18 concerns the plan's traceability, not app behaviour, and has no in-app working answer. None blocks building the MVP; Q19, Q4, Q11 and Q13 gate the entry of real data. Q25–Q29 were added on 2026-11-20 with Phase 11 (stock); none of them blocks version 1.1.0. This document records only the status of each question (open / answered and applied locally / answered and implemented in task Tn), never the content of an answer (T10.5).

**Q19 — Formal classification (gates real-data use).** Is any of this data formally classified or access-restricted under the access-to-information law (Lei 12.527/2011, arts. 23–28) or under military rules? As the plan reads Lei 12.527/2011 art. 28 and Decreto 7.845/2012 art. 19, a classification is made by a formal decision of the competent authority; this is not legal advice. The statute text: Decreto 7.845/2012 requires, for classified information, cryptographic resources based on a State algorithm and isolated equipment (arts. 31, 39, 40). The plan's reading, not legal advice: if the data is classified, this design (plaintext SQLite, plaintext automatic backups, commercial cryptography, an unsigned binary from a public repository) is unsuitable, and real data must not be entered.
- Answered by: the committee, with the institution's information-security and legal advisers.
- Confirms: F05, §7.1 and the first-run notice (T7.5).
- Until answered: only demo data is used; "sensitive" in this plan is a working label, not a classification.

**Q1 — Indicators and targets.** Is the proposed indicator list (§5.4) right, including the design proposal `EX_DAYS_SINCE_LAST`? Which indicators make up the "padrão esperado de prontidão" (L82), and what warning and critical values apply to each — for example, a minimum number of staff with a valid level-A PPE qualification?
- Answered by: the committee.
- Confirms: P03 and the indicator list. Enables the `INDICATOR_WARNING` and `INDICATOR_CRITICAL` alerts (R27).
- Until answered: no targets are set. Every indicator shows "No target" and raises no indicator alert.

**Q2 — PPE qualifications and retraining.** Does each level (A, B, C) have a fixed validity period, and how long is it? Does a qualification at one level also count for other levels, and if so for which? What exactly makes retraining ("reciclagem") necessary: expiry only, or also elapsed time or hours? How many days before expiry should alerts start?
- Answered by: the committee.
- Confirms: A02, A03, A04 and P01 (90 days).
- Until answered: levels are counted independently, valid-until dates are entered per qualification, retraining means expired or expiring, and the warning window is 90 days.
- Also open: whether to record respirator fit tests (model, size, date; 12-month validity per OSHA 29 CFR 1910.134(f)(2) / the PPR of Portaria MTP 672/2021) and the medical clearance for respirator use; recording them would be new tasks.

**Q3 — Training and degrees.** Which kinds of training ("capacitação") should be recorded — that is, what goes on the course list? Should degrees in progress be recorded alongside completed ones?
- Answered by: the committee.
- Confirms: A09 and A10.
- Until answered: the course list is empty and editable, and degrees carry a completed / in-progress status.

**Q4 — Staff data and categories.** Which personal data may the app hold under the institution's reading of the LGPD? The plan proposes an internal code per person plus an optional short label, and no national ID numbers, birth dates, contact or health data. Should a professional category be recorded, and with which categories? Is the "pseudonymise person" action (identifier replaced by a random code, free text cleared or replaced by random codes, history kept) an acceptable response to an erasure request? Can a person who leaves and later returns be entered as a new record (A14)? *The plan's reading, not legal advice:* the national-defence exclusion (LGPD art. 4, III) requires an exclusive purpose and probably does not cover staff-management data, and an internal code is pseudonymisation, so the data stays personal (art. 13, §4).
- Answered by: the committee.
- Confirms: D17, A14 and the category list. Gates the entry of real data.
- Until answered: only the internal code, an optional label and a free, empty category list are available; no real data is entered.

**Q5 — Beds and bays.** Does "leitos e baias disponíveis" (L76) mean installed units in working order, or units free at a given moment? Which status categories are needed, and does "degraded" count as available? Is equipment that leaves service and returns entered as a new record (A14)?
- Answered by: the committee.
- Confirms: A01, A05 and A14. Tracking occupancy would need new tasks.
- Until answered: available means in service and operational; degraded counts as unavailable.

**Q6 — Equipment and maintenance.** Should "equipamentos de pressão negativa e filtragem" be one category or several? What maintenance interval applies to each type, and how many days in advance should maintenance alerts start?
- Answered by: the committee.
- Confirms: A06 and P02 (30 days), and the built-in type list.
- Until answered: one built-in type mirrors the appendix wording, intervals are not set ("schedule unknown"), and the warning window is 30 days.

**Q7 — Exercises.** Which aggregated evaluation results ("resultados agregados de avaliação", L78) should be recorded: metric names, scales and units? Besides the CBRAMED and EXBRAMED editions, should other courses or exercises be recorded? Is a total participant count enough, or are breakdowns needed? Is any country code outside ISO 3166-1 alpha-2 needed (CLDR has more codes, such as `XK`)?
- Answered by: the committee.
- Confirms: A07, A13 and the country list (T4.2). Breakdowns would be deferred item X10.
- Until answered: the metric list is empty and user-defined, the kinds are CBRAMED, EXBRAMED and other, and only a total count is recorded.

**Q8 — Budget.** Which execution stages should be tracked? In which currencies are the Comando da Aeronáutica (COMAER) and DIRSA amounts recorded, and is conversion needed? Is the fiscal year the calendar year? Are there other funding sources? Should the execution target be pro-rated over the fiscal year (the working default, P08), and are BRL, USD and EUR enough as currencies?
- Answered by: the committee.
- Confirms: A08, P08 and the currency allow-list (D15). More stages or currency conversion would need new tasks.
- Until answered: an allocated amount and dated execution rows are tracked, the default currency is BRL, currencies are never mixed or converted, the fiscal year is the calendar year, and the execution target is pro-rated linearly.

**Q9 — Readiness reading and predictive validity (L87).** Is a single composite readiness score wanted, and if so with which formula and weights? How will the performance actually observed in the next EXBRAMED be measured and recorded? How often should the app record snapshots?
- Answered by: the thesis author, with the committee.
- Confirms: P04. A composite score would be deferred item X4.
- Until answered: no composite score is computed. The "reading" is the full set of indicator values in a snapshot. Snapshots are taken monthly and with every report.

**Q10 — Reports.** What should the internal report (for the committee, DIRSA and the Air Force Command) contain, and the aggregated, anonymised report (thesis L69 names the OPCW Technical Secretariat as a possible recipient)? In which languages? Below which count should personnel figures be suppressed in the anonymised report? Are PDF and CSV enough, or is XLSX needed? What disclosure rule does the recipient apply to successive anonymised reports, given that the difference between two reports can reveal a suppressed count? Is the handling notice of the internal report needed, and what does it say (set locally, never in the repository)?
- Answered by: the committee.
- Confirms: A11 (threshold 5) and the report sections. XLSX would be deferred item X3.
- Until answered: the two PDF variants of T8.5 and T8.6 are produced in the chosen UI language, personnel-derived counts below 5 (zeros included) are suppressed with secondary suppression, and differencing is a documented residual risk. The anonymised report is for internal use; the app never sends anything, and any external release is decided by the chain of command.
- Also recorded as residual (QA findings P8-01, P8-16): the anonymised variant prints the operator-entered codes as they are (funding-source, asset-type and edition codes), and the built-in source `DIRSA` by its code, as a proper name (the built-in source `COMAER` is printed by its translated name); and the undeclared relation `active_staff - valid:<level>` can reveal a hidden expired count (T8.5).

**Q11 — Information security (L91).** Which institutional rules apply to this data? In particular: is encryption of the database file itself required, in addition to full-disk encryption of the workstation? Where may backups be stored? Is there a passphrase policy? Is Argon2id required instead of scrypt for the backup key? After how many days should the reminder for an old encrypted backup appear (P09)? Gates the entry of real data, together with Q19, Q4 and Q13.
- Answered by: the committee.
- Confirms: R33, D03, P05 (12 characters) and P09. Database encryption would be deferred item X1; Argon2id would be deferred item X13.
- Until answered: OS-level protection, data minimisation, encrypted manual backups and a 12-character minimum passphrase, with a reminder after 30 days; no real data is entered.

**Q12 — Users and history.** Will one person per installation maintain the data, or must several people edit the same data? May the change history record an operator name, and how long should the history be kept? If several people take turns on one machine, will they share one Windows account, or use a local folder restricted to the committee through `--data-dir` (separate Windows accounts give separate databases)? How long may backups that hold erased or pseudonymised values be kept?
- Answered by: the committee.
- Confirms: A12 and D05. Shared use would be deferred item X2; a retention or redaction tool would be X8.
- Until answered: a single local operator, an optional operator label, and change history kept indefinitely (personal free-text values are not logged).

**Q13 — Deployment.** How will the app be deployed on the hospital's machines? Is an unsigned executable delivered as a zip folder acceptable? Is a single `.exe` file mandatory? Is code signing expected? What type of Windows profile is used (roaming, mandatory, non-persistent/VDI — a mandatory or non-persistent profile discards `%LOCALAPPDATA%` at logoff)? Is AppLocker/WDAC or Smart App Control enforced, and which folders may run programs? Gates the entry of real data, together with Q19, Q4 and Q11.
- Answered by: the committee, with whoever manages those machines.
- Confirms: D01, D10 and the default data location (D02). A single file would be deferred item X5; signing would be X6.
- Until answered: a one-folder zip, unsigned, with checksums, a per-file manifest and a provenance attestation; no real data is entered.

**Q14 — Terminology.** Can the committee review the interface terms in pt-BR, en-US and es-ES — for example the PPE level names, "baia", "reciclagem", and the Spanish and English equivalents of "prontidão"?
- Answered by: the committee.
- Confirms: the translation catalogues (§6).
- Until answered: draft translations are used, and the review status is recorded as pending in the changelog.
- Also in scope (added with Phase 11): the term "aprazamento" (tab title "Aprazamento de vencimentos") and the title-case names of the 17 built-in stock item types, which are kept exactly as the owner wrote them.

**Q15 — Preliminary notice.** What should the "preliminary version, not institutionally validated" notice say, and where should it appear in the interface and in reports?
- Answered by: the thesis author, with the committee.
- Confirms: P07 and I06.
- Until answered: the placeholder text appears in the UI banner, on every PDF page, in the About dialog, in the first-run notes and in the release notes.

**Q16 — Retroactive data, 2022–2025 (L87).** In what form do these records exist — spreadsheets, documents, tables — so that the CSV import templates can match their structure? Only the structure is needed, never the data.
- Answered by: the committee.
- Confirms: the column layout of the import templates (T8.4).
- Until answered: the templates follow the data model of §5.2, and records can still be entered by hand.

**Q17 — Report headers.** Which institution and unit names should appear in report headers? They are set locally in Settings and never stored in the repository.
- Answered by: the committee.
- Confirms: D18.
- Until answered: the names are empty, and the header shows only the report title, the as-of date and the app version.

**Q18 — Requirements source.** The appendix source is not in the repository, so the R01–R36 quotes and the `Lnn` references of §3.1 cannot be checked from the repository. Should the author either publish the L55–L95 excerpt as `docs/requirements-source.pt-BR.md`, or record the thesis version and the SHA-256 of the source in the header of this plan?
- Status: Answered and applied: the source is `postextual/apendice-a.tex` of the private thesis repository, commit `f8b1d65a76b53019573fb789c09d3d938dbffb59` (2026-11-13), SHA-256 `fbe30bc40ff6ab5ebace449dd3309e2dc2ff8f216d4ad9048c77a83b9c6661c1`; the excerpt is not copied into this repository because the thesis is unpublished; all 36 quotes R01–R36 and their line numbers were checked against it.
- Answered by: the thesis author.
- Confirms: the traceability table of §3.1.
- Until answered: the quotes and line references are unverifiable from the repository; the application is not affected.

**Q20 — Qt and PySide6 source for the written offer.** The source links in the release body and in `SOURCE-OFFER.md` are built from URL patterns of `download.qt.io` in `scripts/make_release_zip.py` and have not been checked to resolve for the bundled versions. `uv.lock` records only wheels for the PySide6 family, so `SOURCE-OFFER.md` says it records no source archive for those packages. Are those links right, and is the written offer enough for the PySide6 family? (Phase 9 QA; the per-package source list is finding P9-10)
- Status: answered and applied locally
- Answered by: the project owner.
- Confirms: §4.2, T9.2 and T9.3 (the source pointer and the written offer).
- Until answered: the links are generated from the patterns and the written offer covers the Qt and PySide6 source of the bundled versions.

**Q21 — Visual C++ runtime notice.** Is the wording of `MSVC-RUNTIME.md` (the runtime files are redistributed unmodified, with a pointer to Microsoft's terms, and the file list is written from the files found in the bundle) what Microsoft's redistribution terms require? (Phase 9 QA; the generated file list is finding P9-07)
- Status: answered and implemented in task T9.2
- Answered by: the project owner.
- Confirms: T9.2 (the Visual C++ runtime notice).
- Until answered: the notice is shipped with that wording, unconfirmed.

**Q22 — Qt third-party attributions.** The PySide6 wheels the bundle is built from ship no SBOM and no attribution files, so `QT-THIRD-PARTY.md` carries a pointer to Qt's "Licenses Used in Qt" page and to the Qt source release instead of the attribution texts that T9.2 asks for. Is the pointer acceptable, or must the attribution texts be taken from the Qt source release? (Phase 9 QA)
- Status: answered and implemented in task T9.2
- Answered by: the project owner.
- Confirms: T9.2 and §8 (Qt's third-party attributions).
- Until answered: the pointer is shipped, recorded as a known limitation.

**Q23 — First release run and attestation.** The two-job release workflow (T9.3) has not run yet. Do the repository's plan and settings allow GitHub's build-provenance attestation, and does the workflow produce the draft release as tested? (Phase 9 QA; the two jobs are findings P9-01, P9-03)
- Answered by: the project owner, on the first tag.
- Confirms: D10 and T9.3.
- Until answered: the workflow is checked only by the workflow tests; the first tag is the first real run.

**Q24 — Branch protection.** Merging only green pull requests (Dependabot ones included, T9.5) needs branch protection on `main` with the CI jobs `test` and `build` as required status checks. That is a setting of the repository on the hosting site, which nothing in the repository's files can enforce. Is it configured? (Phase 9 QA)
- Status: answered and applied locally
- Answered by: the project owner.
- Confirms: T9.5 and `CONTRIBUTING.md`.
- Until answered: the rule is stated in `CONTRIBUTING.md` only.

**Q25 — Classification of stock items and per-unit tracking.** Are the categories given to the 17 built-in stock item types (antidote, decontaminant, detector, PPE, other) the right ones? Do some items also need per-unit tracking with a status or maintenance — for example the calibration of detectors, the hydrostatic test of an oxygen cylinder, the bubble stretcher, or the inspection of a full-face mask — and if so, should they be recorded as assets (§5.2) as well as stock? (Owner request of 2026-11-20; added with Phase 11.)
- Answered by: the committee.
- Confirms: D32 and A16 (the category of each built-in type). Per-unit tracking of stock items would need new tasks.
- Until answered: stock is recorded by lot only, with no status or maintenance on lots; an item that needs both is entered as two records (D32); the categories of the built-in types are the working ones (A16).

**Q26 — Units of issue and minimum stock.** Which unit of issue applies to each item type (unit, box, kit), and can a quantity be fractional? Which minimum stock applies to each type, and is a minimum needed per storage location? (Owner request of 2026-11-20; added with Phase 11.)
- Answered by: the committee.
- Confirms: A15 (whole units, no unit column) and P12 (minimum per type, a local-only value).
- Until answered: quantities are whole units of issue with no unit column, no minimum is set (the field is empty and flagged as a placeholder), and no `LOW_STOCK` alert is raised. A minimum is entered per installation in Settings and never becomes a code default.

**Q27 — Sensitivity of stock data in reports.** May per-type stock quantities, values and prices appear in the anonymised report, or must they stay in internal reports only? Who receives the internal list of expired and expiring lots? Are the counts of lots and of types below the minimum acceptable in the anonymised report? (Owner request of 2026-11-20; added with Phase 11.)
- Answered by: the committee, with the institution's information-security advisers.
- Confirms: D37 and K23.
- Until answered: the anonymised report omits per-type stock quantities, values and prices and the stock chart, and keeps counts only; the internal list of expired and expiring lots is for the internal report only.

**Q28 — Expiry rules.** Is a warning window of 90 days before expiry right (P11), and may it differ per category? If the source gives only a month and a year for an expiry, is the last day of the month meant? Must an expiry date also be required for the other categories (detector, PPE, other)? Is a lot that has expired and is still in stock a critical alert? (Owner request of 2026-11-20; added with Phase 11.)
- Answered by: the committee.
- Confirms: P11 (a generic default) and D34.
- Until answered: the warning window is 90 days for all categories, a full expiry date is entered, the date is required only for antidotes and decontaminants, and an expired lot that still has stock is critical.

**Q29 — Movements and locations.** Are the six movement kinds (receipt, issue, disposal, loss, adjustment in, adjustment out) enough? Are transfers between locations needed, a storage location per lot, or an absolute stock count (an inventory count that sets the quantity)? (Owner request of 2026-11-20; added with Phase 11.)
- Answered by: the committee.
- Confirms: D33. Locations, transfers or absolute counts would need new tasks.
- Until answered: six movement kinds, no location, no transfers; a count that differs from the record is entered as an adjustment with a note.

---

## 13. Definition of done for version 1.0
Version 1.0 is done when every item below can be verified.

1. **Tasks:** every task from T0.1 to T10.5, including T9.6, is merged. Deferred items X1–X13 are excluded.
2. **Default suite:** `uv run pytest` passes in CI on the pinned Windows image. This covers lint, types, guards, hygiene, translation completeness and sync, and the pseudo-locale walk. The CI coverage gate (at least 90% for `domain`, `storage` and `services`) passes.
3. **Packaging suite:** `uv run pytest -m packaging` passes in CI. The frozen self-test passes every check; the bundle-content checks pass (no Qt network or web libraries, no data files); the portable-mode test passes.
4. **CI is green** on the commit tagged `v1.0.1`.
5. **Release artefacts:** the release workflow produced `cbrn-readiness-dashboard-1.0.1-win-x64.zip`, `SHA256SUMS.txt`, a per-file manifest of the bundle, a build-provenance attestation and a draft GitHub release. A person has verified the checksum with `Get-FileHash` before publishing; the checksum proves transfer integrity, not authenticity.
6. **Three languages:**
   - pt-BR, en-US and es-ES are complete according to the automated tests;
   - the terminology review (Q14) is recorded in `CHANGELOG.md`: either no unfinished message remains in the catalogues, or the changelog states the count still pending review (T10.5 test);
   - the in-app help exists in all three languages with the same structure.
7. **Placeholders** (1.0.x and 1.1.0; from 1.2.0 see §13.2)**:** every placeholder of §3.5 is either a generic default whose flag was cleared in `domain/config.py` because the project owner judged the value not sensitive, or still flagged in `domain/config.py` and listed in the changelog entry for 1.0.0 (T10.5 test). The local-only values (targets, institution and unit names, the report handling notice) stay flagged, have no code default and are confirmed per installation in Settings only. The A-items without a setting (A01, A03, A12, A13, A14) are listed only as open questions. The changelog and PLAN.md record only the status of each question, never the content of an answer.
8. **Preliminary notice** (1.0.x and 1.1.0; from 1.2.0 see §13.2)**:** it is present in the UI banner, on every PDF page, in the About dialog, in the first-run notes and in the release body (tests in T1.9, T8.6, T10.2, T9.4 and T9.3).
9. **Documentation:** all of these exist and pass their tests where tests apply:
   - `README.md`; `PLAN.md` (updated §3.5 and §12, with the status of each question and never the content of an answer); `CONTRIBUTING.md`; `CHANGELOG.md`;
   - `docs/install.{pt-BR,en-US,es-ES}.md`, `docs/indicators.md`, `docs/architecture.md`, `docs/data-protection.md`, `docs/import-templates.md`, `docs/manual-test-script.pt-BR.md`, `docs/smoke-test.pt-BR.md`;
   - the in-app help;
   - the `licenses\` folder in the bundle.
10. **Manual test:** a person has run `docs/manual-test-script.pt-BR.md` on the built zip, on a clean Windows profile without admin rights, and recorded the result in the changelog. The run includes: entering data in every module; switching languages; read-only mode; an encrypted backup to removable media and its restore (including a wrong passphrase and a demo/real mismatch); both PDF reports; a CSV import with a deliberate error.
11. **Offline:** source contains no network-capable modules (T0.4), and the bundle contains no Qt network or web libraries (T9.1). No telemetry, no update check.
12. **Licences:** the allow-list test passes, and the `licenses\` folder and the About dialog list every bundled component (T9.2, T10.2). The release body links the matching source tag and the Qt and PySide6 source release, and carries the written offer (T9.3).
13. **Repository content:** the hygiene test passes, and a person has reviewed the tagged tree. It contains no real data, no database or backup files, no text from the WHO guide or from internal hospital documents, no clinical content, and no committee answers (only the status of each question). All demo data is fictitious and uses `DEMO` identifiers.
14. **Out of scope** (1.0.x and 1.1.0; from 1.2.0 see §13.2)**:** institutional homologation (R30) and the result of the predictive-validity comparison (R31) are not part of this definition. v1.0 is handed over for institutional evaluation as a preliminary tool. The entry of real data is gated by the answers to Q19 (formal classification), Q4, Q11 and Q13 (§12); until then only demo data is used.

### 13.1 Definition of done for 1.1.0
Version 1.1.0 (stock by lot, antidotes and decontaminants; Phase 11) is done when items 2, 3 and 6 to 13 of the list above apply to it, with these changes, and every task from T11.1 to T11.19 is merged:
- the version, the release artefacts (item 5), the checked commit (item 4) and the manual test (item 10) are those of 1.1.0, and the manual test script includes the stock steps with the demo data;
- the changelog entry for 1.1.0 lists the placeholders still flagged (P11 and P12 included, P12 local-only with no code default), A15 and A16 among the assumptions without a setting, the status of Q1–Q29 and the number of unfinished translation messages (items 6 and 7);
- the help exists in the three languages with the same structure, including the antidotes page and the stock tab, and contains no clinical content (items 6 and 9, D19, D38);
- the anonymised report contains no per-type stock quantity, value or price (D37), and the documentation says so (items 9 and 13);
- the one-time change of the snapshot configuration hash is documented in the changelog (K21);
- the deferred items X1–X13 stay excluded, and the entry of real data stays gated as in item 14.

### 13.2 Definition of done for 1.2.0
Version 1.2.0 (notice removal; Phase 12; D39) is done when items 2, 3, 5, 6 and 9 to 13 of the list in §13 apply to it, with these changes, and every task from T12.1 to T12.15 is merged:
- the version, the release artefacts (item 5), the checked commit (item 4) and the manual test (item 10) are those of 1.2.0;
- item 7 becomes: no placeholder flag is set; the local-only values (P03, P10, D18, P12) have empty code defaults and are listed in the changelog; no badge or Confirm action exists;
- item 8 becomes: the no-notice scan in `tests/meta` passes; the DEMO banner is still shown in demo mode (D25);
- item 14 becomes: the real-data gate is lifted (D39); institutional homologation (R30) and the result of the predictive-validity comparison (R31) stay outside the software;
- the changelog and `PLAN.md` record only the status of Q15, Q19, Q4, Q11 and Q13, never the content of an answer.
