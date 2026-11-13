# CBRN Readiness Dashboard — Implementation Plan

| | |
|---|---|
| Repository | `marco-jardim/cbrn-readiness-dashboard` (public) |
| Licence | GPL-3.0-or-later |
| Plan status | Draft for review by the project owner and the hospital's CBRN defence committee. No code yet. |
| Requirements source | Appendix A of the thesis, product "PTT 2" (appendix source lines 55–95, in Portuguese). `Lnn` = line *nn* of that source. |
| Date | 2026-11-12 |

Contents: 1 Summary · 2 Scope and non-goals · 3 Requirements · 4 Architecture and stack decisions · 5 Data model · 6 Internationalisation · 7 Security and privacy · 8 Packaging and distribution · 9 Testing strategy · 10 Phases and tasks · 11 Risks and mitigations · 12 Open questions for the author · 13 Definition of done for version 1.0

---

## 1. Summary

The CBRN Readiness Dashboard is an offline Windows desktop application. The hospital's CBRN defence committee (CDQBRN) uses it to record, in one place, the readiness indicators that Appendix A lists for "PTT 2", and to monitor them continuously. The indicators are:
- staff certified per PPE level, with certificate validity, training and academic degrees;
- beds, bays, negative-pressure and filtration equipment, and decontamination tents, with their status and maintenance;
- the history of the CBRAMED and EXBRAMED editions;
- annual budget execution per funding source;
- alerts derived from all of the above (L65, L74–L82).

What the solution looks like:
- Python 3.12 and PySide6 (Qt Widgets). Data is kept in a SQLite file in the user's Windows profile. There is no network code at all.
- The interface is in pt-BR (default), en-US and es-ES, and the user can switch language while the app is running.
- PyInstaller builds a portable, unsigned executable that ships as a zip folder. No installer, no admin rights.
- Licensed GPL-3.0-or-later. The public repository holds code and clearly fictitious demo data only.

The appendix states intent, not specifications. It names the modules and what the indicators are about, but gives no formulas, targets, validity periods, users or report layouts. This plan therefore:
- implements exactly the subject matter the appendix names;
- makes every rule configurable;
- ships clearly marked placeholder defaults and no invented readiness targets;
- lists the decisions the committee must take (§12).

Two releases are planned:
- **MVP v0.1** (Phases 0–7, plus the licence bundle and the release pipeline). It contains all five modules with data entry, indicators evaluated "as of" any date, alerts, the dashboard, the trilingual UI, a change log, encrypted backup and restore, and the portable build. This is enough for the committee to start entering data and reviewing the indicators.
- **v1.0** (Phases 8–10). It adds PDF reports (internal, and aggregated/anonymised), CSV import and export for the 2022–2025 retroactive data, readiness snapshots with the export needed for the predictive-validity comparison (L87), the final build and the user documentation.

v1.0 is a preliminary tool that has not been validated by the institution. Homologation (L87) is an institutional step outside the software.

Labels used in this plan:
- **R**: explicit requirement from the appendix.
- **F**: fixed decision by the project owner.
- **I**: implicit requirement, a necessary consequence of R or F.
- **D**: design decision made in this plan.
- **A / P**: assumption or placeholder default that needs confirmation, linked to an open question **Q**.
- **T**: task (§10). **X**: deferred item (§10.4).

---

## 2. Scope and non-goals

### 2.1 In scope (v1.0)
- The five modules of L74–L82 and the dashboard (R01–R27).
- As-of-date evaluation of every indicator, readiness snapshots and the validation export (R04, R29, R31).
- PDF reports, both internal and aggregated/anonymised, plus CSV import and export (R11, R13, R29).
- Local storage, backups, the trilingual UI, the portable Windows build, and a public CI and release pipeline.

### 2.2 Non-goals
- PTT 1, the technical-operational manual (L3–L53). Also out: any clinical, triage, decontamination or antidote content. The application stores management data only (D19).
- Any text from the WHO guide "Initial clinical management of chemical weapons" (CC BY-NC-SA) or from internal hospital documents (F06).
- Servers, web or mobile versions, several users editing at the same time, databases on network shares (D05).
- Integration with hospital, human-resources or financial systems; automatic data collection.
- Sending anything to DIRSA, the Air Force Command or the OPCW. The app produces files; people send them.
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
| CBRAMED, EXBRAMED | The course and exercise series whose history the exercises module records (L78). |
| DIRSA | The Air Force health directorate. It is both a report recipient and a funding source (L65, L80). |
| OPAQ / OPCW | Organisation for the Prohibition of Chemical Weapons. Its Trust Fund is a funding source (L80); its Technical Secretariat receives anonymised reports (L69). |
| QBRN | Portuguese and Spanish for CBRN. |
| As-of date | The date for which every indicator and alert is computed. Defaults to today (D13). |

---

## 3. Requirements

### 3.1 Explicit requirements from Appendix A (PTT 2) and traceability

The appendix defines **five modules**: personnel (L74), infrastructure (L76), exercises (L78), budget (L80) and alerts (L82). Phases are listed in §10; "—" means the item is not a software feature.

| ID | Appendix statement (line) | Feature in this plan | Phase |
|---|---|---|---|
| R01 | "Painel de Indicadores de Prontidão Operacional e Capacitação QBRN do HFAG (*Dashboard* CDQBRN)" (L55) | The application itself; dashboard overview page | P0, P6 |
| R02 | "Produto tecnológico - sistema de informação e gestão" (L57) | Data-entry and management desktop app with a local database | P1–P5 |
| R03 | "sem um instrumento único de consolidação" (L61) | One local database for all modules; CSV import of existing records | P1–P5, P8 |
| R04 | "leitos, pessoal qualificado, investimento e evolução histórica do CTH" (L61) | History: as-of-date evaluation, status and maintenance history, snapshots | P1, P3, P8 |
| R05 | "verificada apenas episodicamente [...] e não por um mecanismo de acompanhamento contínuo" (L61) | Dashboard re-evaluated on every start; start-up alert summary; periodic snapshots | P6, P8 |
| R06 | "Centralizar e monitorar de forma contínua os indicadores de prontidão QBRN" (L65) | Indicator framework and dashboard | P1, P6 |
| R07 | "pessoal certificado por nível de EPI e validade da certificação" (L65) | Personnel module | P2 |
| R08 | "disponibilidade de leitos e equipamentos do CTH" (L65) | Infrastructure module | P3 |
| R09 | "histórico de exercícios realizados" (L65) | Exercises module | P4 |
| R10 | "execução orçamentária" (L65) | Budget module | P5 |
| R11 | "subsidiar decisões da CDQBRN/HFAG e a prestação de contas à DIRSA e à OPAQ" (L65) | Internal PDF report; CSV export | P8 |
| R12 | "Gestão da CDQBRN/HFAG; Diretoria de Saúde da Aeronáutica (DIRSA); Comando da Aeronáutica" (L69) | Audience of the dashboard and internal reports (not app accounts; see D05) | P6, P8 |
| R13 | "em relatórios agregados e anonimizados, o Secretariado Técnico da OPAQ" (L69) | Aggregated, anonymised report variant | P8 |
| R14 | "quantitativo de profissionais certificados por nível de EPI (A, B, C)" (L74) | Count of staff with a valid certificate per level, as of a date | P2 |
| R15 | "validade das certificações e necessidade de reciclagem" (L74) | Expiry tracking; list of staff needing retraining | P2, P6 |
| R16 | "capacitação e titulação (especialização, mestrado, doutorado)" (L74) | Training records; academic degrees | P2 |
| R17 | "leitos e baias disponíveis no CTH" (L76) | Bed and bay register with operational status; availability counts | P3 |
| R18 | "status operacional dos equipamentos de pressão negativa e filtragem" (L76) | Equipment register with status history | P3 |
| R19 | "tendas de descontaminação" (L76) | Tent register with status | P3 |
| R20 | "data da última manutenção" (L76) | Maintenance log; last and next maintenance | P3 |
| R21 | "histórico do CBRAMED e do EXBRAMED" (L78) | Register of editions | P4 |
| R22 | "número de participantes e países representados" (L78) | Participant count and country list per edition | P4 |
| R23 | "resultados agregados de avaliação" (L78) | Aggregated evaluation results per edition (configurable metrics) | P4 |
| R24 | "execução financeira anual por fonte (DIRSA, Trust Fund da OPAQ)" (L80) | Annual budget entries per source; execution rate | P5 |
| R25 | "certificações a vencer" (L82) | Certificate expiry alerts | P6 |
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

### 3.2 Fixed decisions (project owner)
| ID | Decision |
|---|---|
| F01 | A Python desktop application for Windows, delivered as a portable executable. No installer, no admin rights. |
| F02 | Local database only, fully offline. No server, no telemetry, no network calls. |
| F03 | Interface in pt-BR (default), en-US and es-ES, switchable by the user. The appendix uses the same three languages for PTT 1's glossary (L40); for PTT 2 the languages are an owner decision, not an appendix requirement. |
| F04 | GPL-3.0-or-later, published in the public repository `marco-jardim/cbrn-readiness-dashboard`. |
| F05 | Real data (staff qualifications, infrastructure status, exercises, budget) is sensitive and never leaves the user's machine. The repository holds only code and clearly fictitious demo data. |
| F06 | No text from the WHO guide "Initial clinical management of chemical weapons" (its non-commercial clause is incompatible with the GPL) or from internal hospital documents, anywhere in the application or the repository. |

### 3.3 Implicit requirements
| ID | Requirement | Follows from |
|---|---|---|
| I01 | Data persists across sessions and application upgrades, via versioned schema migrations with an automatic backup first | R06, F02 |
| I02 | Backup and restore, because the local file is the only copy | F02 |
| I03 | Every indicator can be evaluated as of any date, past or present | R04, R29, R31 |
| I04 | Rules, warning windows and targets are configurable | R28 (requirements have not been gathered yet) |
| I05 | Input validation and data-quality warnings | R06 |
| I06 | A visible "preliminary, not validated" notice in the UI and in reports | R30 |
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
| D13 | A global as-of date selector; every indicator is computable for any date | §5.4 |
| D14 | Indicator statuses OK / Warning / Critical / No target / No data. No default targets | §5.4 |
| D15 | Money stored as whole minor units (cents) with an ISO 4217 currency code. No conversion; totals never mix currencies | §5 |
| D16 | Built-in list entries mirror the appendix wording. Users may add entries, each with labels in all three languages | §5, §6 |
| D17 | Staff identified by an internal code. No national ID numbers, birth dates, contact or health data | §7 |
| D18 | Institution and unit names are set locally in Settings, never hard-coded | §7 |
| D19 | The application contains no clinical or procedural content | §2.2 |
| D20 | Exercise participants recorded only as counts; countries as ISO 3166-1 alpha-2 codes | §5 |
| D21 | Snapshots taken manually, monthly, and whenever a report is generated | §5.4 |
| D22 | Log files contain event codes only, never record contents | §7 |
| D23 | Status shown as text plus icon plus a colour-blind-safe colour, never colour alone | §10 (T6.5, T10.4) |
| D24 | A certificate can be marked "no renewal", which stops expiry alerts for it | §5.5 |
| D25 | Demo data lives in a separate database file, every identifier starts with `DEMO`, and a permanent banner is shown | §7 |

### 3.5 Assumptions and placeholder defaults
None of the items below is stated in the appendix. Each is an assumption (A) or a placeholder default (P) that needs confirmation, and each is linked to an open question (§12) except P06, which is purely technical.

Every placeholder is declared in `domain/config.py` with a `placeholder` flag. Settings shows it with a "placeholder — to be confirmed" badge until the operator confirms or changes it.

| ID | Assumption or placeholder | Default in v1 | Configurable in | Q |
|---|---|---|---|---|
| A01 | "Leitos e baias disponíveis" (L76) means units in service whose current status is operational, not how many are free at a given moment | — | — | Q5 |
| A02 | PPE levels A, B, C are counted independently: a level-A certificate does not also count as B or C | hierarchy off | Settings → Personnel | Q2 |
| A03 | "Necessidade de reciclagem" (L74) means the person's latest certificate at a level has expired or expires within the warning window, and is not marked "no renewal" (D24) | — | — | Q2 |
| A04 | Each certificate records an explicit valid-until date. An optional validity period per level only pre-fills the form | period not set | Settings → Personnel | Q2 |
| A05 | Asset statuses are operational, degraded and out of service. Only "operational" counts as available | degraded counts as unavailable | Settings → Infrastructure | Q5 |
| A06 | Maintenance due date = the recorded "next due" date if there is one; otherwise last maintenance (or in-service date) plus the interval; with no interval, "schedule unknown" | interval not set | per asset type, per asset | Q6 |
| A07 | Evaluation results (L78) are values of user-defined metrics (name, unit, scale) per edition | no metrics seeded | Settings → Exercises | Q7 |
| A08 | Budget = allocated and executed amounts per fiscal year (taken as the calendar year), per source and currency | currency BRL | Settings → Budget | Q8 |
| A09 | "Capacitação" (L74) = the dated completion of a course from an editable course list | empty list | Settings → Personnel | Q3 |
| A10 | Degrees (L74) carry a status: completed or in progress | completed | per record | Q3 |
| A11 | The anonymised report (L69) shows only aggregate counts, and suppresses personnel-derived counts below a threshold | threshold 5 | Settings → Reports | Q10 |
| A12 | One operator, or several people taking turns on one machine; nobody edits at the same time | — | — | Q12 |
| A13 | The exercise register holds CBRAMED and EXBRAMED editions (L78), plus an "other" kind | — | — | Q7 |
| P01 | Warning window before a certificate expires | 90 days | Settings | Q2 |
| P02 | Warning window before maintenance is due | 30 days | Settings | Q6 |
| P03 | Indicator targets (warning and critical values) | none, so the status shows "no target" | Settings → Targets | Q1 |
| P04 | Automatic snapshots (D21) | monthly (first start in a month) and on every report | Settings | Q9 |
| P05 | Minimum backup passphrase length | 12 characters | Settings | Q11 |
| P06 | Number of automatic local backups kept | 7 | Settings | — (technical) |
| P07 | Disclaimer wording (I06) | "Preliminary version — indicators not institutionally validated." | translations | Q15 |

---

## 4. Architecture and stack decisions

### 4.1 Layers (D11)
```
ui/        PySide6 widgets, table models, dialogs, translations (Qt)
  │ calls
services/  use cases: add a certificate, evaluate indicators, back up... (no Qt)
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
| Runtime | CPython 3.12 x64, pinned in `.python-version`, `requires-python = ">=3.12"` | PSF-2.0 (GPL-compatible) | chosen (D12) | Wheels exist for PySide6, PyInstaller and `cryptography`. Security support runs to Oct 2028, whereas 3.10 reaches end of life in Oct 2026. Re-evaluated yearly. |
| UI | PySide6 (Qt 6 Widgets), `>=6.8,<7` | LGPL-3.0 for the bindings and core Qt modules; GPL-3.0 for the Qt Charts module | confirmed | The official Qt binding. Native Windows look; translations, PDF output and charts are built in. LGPL-3.0 and GPL-3.0 are both compatible with GPL-3.0-or-later. Tkinter was rejected: no built-in charts, PDF or translation tooling. PyQt6 (GPL-3.0) would also be compatible, but it is not the official binding and has no LGPL option. |
| Storage | SQLite through the standard-library `sqlite3` | public domain | confirmed | One file, no administration, transactional, online backup API; nothing extra to bundle. |
| Packaging | PyInstaller `>=6.10`, one-folder (D01) | GPL-2.0-or-later with a bootloader exception | confirmed | Mature PySide6 support; the exception allows bundling code under any licence. Nuitka (Apache-2.0) needs a C compiler and long builds; cx_Freeze is less used with PySide6; Briefcase targets installers. |
| Environment | uv, with `uv.lock` committed | MIT / Apache-2.0 | confirmed | Locked dependencies with hashes; fetches the right Python version; fast in CI. Development tool only, not shipped. |
| Tests | pytest + **pytest-qt** + **pytest-cov** | MIT (all three) | pytest confirmed; plugins added | pytest-qt drives widgets in Qt's offscreen platform, so UI tests need no display; pytest-cov enforces coverage in CI. Test tools only, not shipped. |
| Lint / format | ruff (`check` and `format`) | MIT | confirmed | One fast tool for both lint and formatting; called from a pytest test so the single allowed check command covers it (T0.2). Not shipped. |
| Type checking | **mypy**, strict on `domain`, `services`, `storage` and the Qt-free parts of `reports` | MIT | added | Catches mistakes early in domain and storage code written by agents. Not shipped. |
| Cryptography | **`cryptography`** (Fernet) + the standard library's `hashlib.scrypt` | Apache-2.0 OR BSD-3-Clause | added (runtime) | Encrypted backups (D03, D04). The standard library has no authenticated encryption. Apache-2.0 is compatible with GPL-3.0. Its own dependencies (`cffi` MIT, `pycparser` BSD-3-Clause) are compatible too. |
| Reading PDFs in tests | **pypdf** | BSD-3-Clause | added (tests only) | Extracts text from generated reports so tests can check content. Avoids the AGPL-licensed PyMuPDF. |
| Country names | CLDR data extracted with **Babel** at development time (`scripts/gen_countries.py`) | Unicode-3.0 for the data; BSD-3-Clause for Babel | added (tool only) | Country names in three languages for the exercises module (D20), with no runtime dependency. Only the generated JSON and the CLDR notice are shipped. |
| Charts | Qt Charts, through `ui/shell/charts.py` (D08) | GPL-3.0 | chosen | Already inside the PySide6 wheel; see the tradeoff in §4.3. |
| Reports | Qt's own text-document and PDF-writer classes (D09) | as PySide6 | chosen | No extra dependency; see §4.3. |

The runtime dependencies are only PySide6 and `cryptography`, plus `cryptography`'s own dependencies. A dependency-licence allow-list test (T9.2) fails the build if anything outside MIT, BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0, LGPL-3.0 or GPL-3.0 enters the runtime environment.

The project's source code is GPL-3.0-or-later. Because the binary bundle includes the GPL-3.0 Qt Charts library, the built executable as a whole is distributed under GPL-3.0. The Qt DLLs stay replaceable in the one-folder layout, and the full source and build scripts are public, which meets the LGPL's relinking expectation for the LGPL parts.

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
  4. the default, `%LOCALAPPDATA%\cbrn-readiness-dashboard\`.

  The chosen folder holds the database, `prefs.json`, `backups\`, `logs\`, `tmp\` and the separate `demo\` database.
- *Read-only location:* at start-up the app tests writability by creating and deleting a temporary file. The read-only flag on a Windows folder does not stop file creation, so the flag alone proves nothing.
  - If the location is not writable and a database exists, the app opens it read-only (an SQLite read-only URI), shows a banner and disables every edit action.
  - If it is not writable and no database exists, the app explains the problem in the current language and lets the user choose another folder.
  - It never writes anywhere else silently. In portable mode the choice is remembered in the profile, not in the read-only folder.
- *Warnings:* the app warns when the folder is on a network path (UNC or a mapped network drive), because SQLite locking is unreliable over file shares. It also warns when the folder is inside a OneDrive-synced folder, because the data would leave the machine.
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
- *Automatic local backups:* plain copies in `<data>\backups\`, made with SQLite's online backup API so they are consistent even while the app is open. One is made before every schema migration and one at the first start of each day. The newest 7 are kept (P06).
- *Manual encrypted backup:* a `.cbrnbak` file written wherever the user chooses, for example removable media. The format is a header (magic `CBRNBAK1`, format version, scrypt parameters, salt, app version, schema version) followed by a Fernet token holding the database bytes. The passphrase is entered twice, must meet the minimum length (P05) and is never stored.
- *Restore:*
  1. Decrypt into `<data>\tmp\`.
  2. Run `PRAGMA integrity_check`.
  3. Check that the schema version is not newer than the app, and migrate the copy if it is older.
  4. Keep a safety copy of the current database.
  5. Swap the files atomically.

  Any failure leaves the current database untouched.
- *Export:* CSV per module in a locale-independent format (UTF-8 with BOM, `;` separator, ISO dates, `.` decimal point, stable English column codes), and PDF reports (D09).
- *Import:* CSV templates for the retroactive 2022–2025 data (R29). Each file is validated and imported in a single transaction; a dry run shows the result first; errors are reported per row; duplicates by natural key are rejected; every import is recorded in `change_log`.
- *Tradeoff:* unlike a password-protected zip, an encrypted backup can only be opened by the app, or by a short documented Python recipe that uses the same `cryptography` library. That is accepted because Fernet is a reviewed, hard-to-misuse scheme, whereas zip AES variants are weaker and inconsistently implemented. It also keeps a single restore code path that always validates and migrates.

**D05 — A single local operator: no accounts or roles in v1, but an append-only change log.**
- *Decision:* the Windows session is the access boundary. The operator may enter an optional label (a name or a role) in Settings; it is stamped on `change_log` rows and on reports.
- *Change log:* every insert, update, delete, import and restore writes a `change_log` row in the same transaction, with before and after values as JSON. Database triggers forbid updating or deleting `change_log` rows.
- *Tradeoff — accounts and roles:* app-level logins on top of an unencrypted SQLite file can be bypassed by opening the file in any SQLite tool. They would add friction and a password to forget, without real protection. Real multi-user use (A12, Q12) would need a shared database, which SQLite on network shares does not support safely, so it is a v2 architecture question (deferred item X2).
- *Tradeoff — audit trail:* the change log costs little when it is built into the repository layer from the start, and is expensive to add later. It supports audits and inspections (R35) and the reconstruction of history. It is not tamper-proof against someone with access to the file, and it keeps old values of personal data; retention is Q12, and a redaction tool is deferred item X8.

**D06 — Data-access layer and migrations: standard-library `sqlite3` with plain SQL, and numbered SQL migration files.**
- *Decision — repositories:* one per module in `storage/`, running explicit SQL against `STRICT` tables with foreign keys on, inside explicit transactions (`isolation_level=None` with explicit `BEGIN`/`COMMIT`).
- *Connection settings:* rollback journal (`journal_mode=DELETE`, which leaves no extra WAL files beside the database), `synchronous=FULL` and `secure_delete=ON`. All connections, read-only ones included, are opened by `open_database()`.
- *Migrations:*
  - Numbered `.sql` files in `storage/migrations/`, loaded with `importlib.resources` so they also work inside the frozen executable.
  - Each runs inside a transaction (SQLite supports transactional schema changes), and the schema version is tracked in `PRAGMA user_version`.
  - The app makes a backup before migrating and refuses to open a database newer than itself.
  - A migration is never edited after it has shipped in a tagged release.
  - Numbers 0002–0007 are reserved per module, so parallel work does not collide.
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
- *One catalogue per area:* lets agents working in parallel avoid merge conflicts in shared translation files.

**D08 — Charts: Qt Charts, used only through the adapter `ui/shell/charts.py`.**
- *Qt Charts:*
  - Licence: GPL-3.0, compatible with this project.
  - Bundle size: it is already inside the PySide6 wheel and adds only a few Qt DLLs.
  - It looks native, renders offscreen, and can draw into the same painter that writes PDFs (D09).
- *pyqtgraph:* MIT, but it needs numpy, which adds tens of megabytes, and it has a scientific rather than management look.
- *matplotlib:* a permissive PSF-style licence, but it needs numpy, Pillow and several other packages. It gives the largest bundle and the slowest start-up, although its static export is the best.
- *Risk:* Qt is steering new charting work towards Qt Graphs. The adapter keeps a later switch local (deferred item X9).
- Charts are secondary: every number shown in a chart also appears in a tile or a table, so a chart problem never hides data.

**D09 — Reports and export: PDF and CSV in v1; XLSX deferred.**
- *Decision:* PDF reports are built with Qt's own text-document and PDF-writer classes, with no extra dependency. There are two variants:
  - the internal report, for the committee, DIRSA and the Air Force Command (R11, R12);
  - the aggregated, anonymised report for the OPCW Technical Secretariat (R13, A11).

  Both carry the preliminary-version notice (I06, P07). CSV serves data exchange and the retroactive import (R29, D04).
- The appendix calls for reports and accountability (L65, L69, L95) but does not mention spreadsheets. XLSX is therefore deferred item X3, pending Q10. `openpyxl` (MIT) would be compatible if it is needed.
- *Tradeoff:* Qt's subset of HTML gives less layout control than ReportLab (BSD) or WeasyPrint. But it adds no dependency, uses the same fonts and chart rendering as the UI, and is enough for tables, key figures and embedded charts.

**D10 — CI on GitHub Actions; an unsigned executable.**
- *On every push and pull request:*
  - A job on a **pinned** Windows runner image (not `windows-latest`) runs `uv sync --locked`, then the default pytest suite with Qt's offscreen platform. That suite includes ruff, mypy, the guard tests and the translation-completeness tests. Coverage is gated in CI.
  - A second job builds the one-folder executable with PyInstaller, runs the built executable's `--self-test`, and uploads the zipped folder as a short-lived workflow artefact.
- *On a version tag:* a release workflow rebuilds and retests, then produces:
  - the zip;
  - a `SHA256SUMS.txt` file;
  - a build-provenance attestation, made with GitHub's attestation action and verifiable with `gh attestation verify`.

  It then creates a **draft** GitHub release. A person publishes it after a manual smoke test.
- *Supply chain:* every action is pinned to a full commit SHA, workflow permissions are least-privilege, and Dependabot proposes updates.
- *Unsigned executable — consequences:* Windows SmartScreen shows "Windows protected your PC" the first time a downloaded copy runs. Smart App Control, or AppLocker/WDAC policies, may block it outright.
- *Mitigations:* one-folder layout, no UPX, published checksums and attestation, install guides in three languages, and allow-listing by file hash by the institution's IT team.
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
│                  install.{pt-BR,en-US,es-ES}.md  manual-test-script.pt-BR.md
├─ src/cbrn_dashboard/
│  ├─ __init__.py (version)  __main__.py  app.py  cli.py  clock.py  paths.py  prefs.py
│  │  logging_setup.py  selftest.py
│  ├─ domain/      config.py  dates.py  indicators.py  registry.py
│  │               personnel.py  infrastructure.py  exercises.py  budget.py  alerts.py
│  ├─ storage/     db.py  migrate.py  repository.py  settings_repo.py  targets_repo.py
│  │               personnel_repo.py  infrastructure_repo.py  exercises_repo.py  budget_repo.py
│  │               backup.py  crypto_backup.py  csv_io.py
│  │               migrations/  README.md (number reservations)  0001_core.sql … 0007_snapshots.sql
│  ├─ services/    personnel.py  infrastructure.py  exercises.py  budget.py
│  │               indicators.py  alerts.py  dashboard.py  snapshots.py  validation_export.py
│  │               backup.py  restore.py  export.py  importer.py
│  ├─ reports/     model.py  anonymise.py  pdf.py
│  ├─ ui/
│  │  ├─ shell/    main_window.py  i18n.py  formatting.py  charts.py  prompts.py  registry.py
│  │  │            context.py  banners.py  first_run.py  about.py  help.py
│  │  └─ personnel/  infrastructure/  exercises/  budget/  dashboard/  alerts/  settings/  backup/  reports/
│  │               (each: page.py, dialogs.py, models.py, labels.py as needed)
│  ├─ i18n/        __init__.py (area → source-folder map, language list)
│  │               <area>_pt_BR.ts  <area>_en_US.ts  <area>_es_ES.ts   (.qm generated, not committed)
│  ├─ help/        pt_BR.md  en_US.md  es_ES.md
│  ├─ resources/   app.ico  countries.json  THIRD_PARTY_DATA.md
│  └─ demo/        __init__.py  personnel.py  infrastructure.py  exercises.py  budget.py
└─ tests/
   ├─ conftest.py
   ├─ meta/  domain/  storage/  services/  ui/  i18n/  reports/  demo/  scripts/  packaging/
   └─ fixtures/    (fictitious data only, e.g. csv/)
```
Notes on the layout:
- The existing `.gitignore` already ignores `build/`, `dist/`, `lib/`, `var/`, `*.spec`, `*.mo` and `*.pot`. So no source folder may use those names, there is no committed PyInstaller spec file (`scripts/build_exe.py` passes every option), and gettext is not used (D07).
- The storage package is called `storage`, not `data`, so a root-anchored `/data/` ignore rule can protect a portable data folder created inside a working copy.
- T0.3 adds ignore rules for database, backup and compiled-catalogue files.

---

## 5. Data model

### 5.1 Conventions
- `STRICT` tables, which need SQLite 3.37 or later; the version is checked at start-up (T1.2). Integer primary keys.
- Dates are text `YYYY-MM-DD`. Timestamps are UTC ISO 8601 text ending in `Z`. Booleans are `0`/`1`.
- Money is a whole number of minor units (cents) plus an ISO 4217 currency code (D15).
- Foreign keys are on. Child rows are deleted with their parent (`ON DELETE CASCADE`). List entries that other rows use cannot be deleted (`ON DELETE RESTRICT`); they are deactivated instead. Built-in list entries (D16) cannot be deleted at all.
- User-defined list entries (asset types, courses, evaluation metrics, funding sources) have three label columns, `label_pt_br`, `label_en_us` and `label_es_es` (§6).
- Every write goes through the repository helpers, which record a `change_log` row in the same transaction (D05).
- In the sketch below, comments cite the appendix line (L) or the plan code (D, A, P) that motivates a column or constraint. The DDL is illustrative; the migration files are the source of truth.

### 5.2 Schema sketch
```sql
-- 0001_core.sql
CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;       -- is_demo, created_with
CREATE TABLE setting  (key TEXT PRIMARY KEY, value_json TEXT NOT NULL) STRICT;  -- readiness config (P01..P07)
CREATE TABLE change_log (
  id INTEGER PRIMARY KEY,
  at_utc TEXT NOT NULL,                  -- ISO 8601 UTC
  operator TEXT NOT NULL DEFAULT '',     -- optional operator label (D05)
  entity TEXT NOT NULL, entity_id INTEGER,
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
  active_from TEXT NOT NULL, active_until TEXT,
  notes TEXT
) STRICT;
CREATE TABLE ppe_certification (
  id INTEGER PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
  ppe_level TEXT NOT NULL CHECK (ppe_level IN ('A','B','C')),        -- L74
  issued_on TEXT NOT NULL,
  valid_until TEXT NOT NULL CHECK (valid_until >= issued_on),        -- A04
  no_renewal INTEGER NOT NULL DEFAULT 0,                             -- D24
  reference TEXT, notes TEXT
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
  completed_on TEXT NOT NULL, hours REAL, notes TEXT
) STRICT;
CREATE TABLE academic_degree (
  id INTEGER PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('specialisation','master','doctorate')),       -- L74
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','in_progress')), -- A10
  year INTEGER, field TEXT
) STRICT;

-- 0003_infrastructure.sql
CREATE TABLE asset_type (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
  built_in INTEGER NOT NULL DEFAULT 0,   -- seeded: bed, bay, neg_pressure_filtration, decon_tent (L76)
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT,
  default_maintenance_interval_days INTEGER,                          -- NULL = not set (A06)
  active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE asset (
  id INTEGER PRIMARY KEY,
  type_id INTEGER NOT NULL REFERENCES asset_type(id) ON DELETE RESTRICT,
  tag TEXT NOT NULL UNIQUE, description TEXT, location TEXT,
  in_service_from TEXT NOT NULL, in_service_until TEXT,
  maintenance_interval_days INTEGER,                                  -- overrides type default
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
  next_due_on TEXT, note TEXT
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
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,   -- seeded: DIRSA, OPCW_TRUST_FUND (L80)
  built_in INTEGER NOT NULL DEFAULT 0,
  label_pt_br TEXT, label_en_us TEXT, label_es_es TEXT, active INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE budget_entry (
  id INTEGER PRIMARY KEY,
  fiscal_year INTEGER NOT NULL,                                       -- A08
  source_id INTEGER NOT NULL REFERENCES funding_source(id) ON DELETE RESTRICT,
  currency TEXT NOT NULL CHECK (length(currency) = 3),                -- ISO 4217 (D15)
  allocated_minor INTEGER,
  executed_minor INTEGER NOT NULL DEFAULT 0,
  description TEXT, notes TEXT
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
  app_version TEXT NOT NULL, config_hash TEXT NOT NULL, note TEXT
) STRICT;
CREATE TABLE readiness_snapshot_value (
  snapshot_id INTEGER NOT NULL REFERENCES readiness_snapshot(id) ON DELETE CASCADE,
  indicator_code TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '',
  value REAL, status TEXT NOT NULL, warning_value REAL, critical_value REAL,
  PRIMARY KEY (snapshot_id, indicator_code, dimension)
) STRICT;
-- triggers: RAISE(ABORT) on UPDATE of either snapshot table (snapshots are evidence for R31)
```
Migration numbers 0002–0007 are reserved in `storage/migrations/README.md`, so modules developed in parallel do not collide.

### 5.3 Relations
- `staff_member` 1–n `ppe_certification`, `training_record`, `academic_degree`. `training_course` 1–n `training_record`.
- `asset_type` 1–n `asset`. `asset` 1–n `asset_status_event` and `maintenance_event`. An asset's status on a date is its latest status event on or before that date.
- `exercise_edition` 1–n `exercise_country` and `evaluation_result`. `evaluation_metric` 1–n `evaluation_result`.
- `funding_source` 1–n `budget_entry`.
- `indicator_target` and `readiness_snapshot_value` refer to indicator codes from the code registry (`domain/registry.py`), not to tables.
- `change_log` refers to any table by entity name and row id. It has no foreign key on purpose, so it outlives deleted rows.

### 5.4 Proposed initial indicators (D13, D14)
Every indicator is computed for the as-of date, either the global selector or a snapshot date. An indicator can be split by a *dimension*, such as the PPE level or the funding source; targets are stored per (code, dimension).

Statuses:
- **OK**, **Warning** or **Critical** when a target exists;
- **No target** when none is configured — the default, so the app invents no readiness standard (P03);
- **No data** when the value cannot be computed.

| Code | Proposed definition | Dimension | Source | Default target |
|---|---|---|---|---|
| `PERS_CERT_VALID` | Active staff with a certificate at the level where valid-until ≥ as-of date | level A/B/C | R14 | none |
| `PERS_CERT_EXPIRING` | Certificates of active staff expiring within the warning window (P01) | level | R15, R25 | none |
| `PERS_RETRAINING_NEEDED` | Active staff needing retraining as defined in A03 | level | R15, R36 | none |
| `PERS_DEGREE` | Active staff with a degree at the level (completed; in-progress counted separately) | level, status | R16 | none |
| `PERS_TRAINING_12M` | Training records completed in the 12 months before the as-of date | — | R16, A09 | none |
| `INFRA_AVAILABLE` | Units in service and operational, out of all units in service | asset type | R17–R19, A01, A05 | none |
| `INFRA_MAINT_OVERDUE` | Units in service whose maintenance due date is before the as-of date | asset type | R20, R26 | none |
| `EX_LAST_PARTICIPANTS` | Participants in the latest edition that ended on or before the as-of date | kind | R22 | none |
| `EX_LAST_COUNTRIES` | Countries represented in that edition | kind | R22 | none |
| `EX_DAYS_SINCE_LAST` | Days since the latest edition ended. *A design proposal (D), not stated in the appendix; needs Q1.* | kind | R05 | none |
| `BUD_EXEC_RATE` | Executed ÷ allocated for the as-of date's fiscal year; No data when allocated is missing or zero | source, currency | R24 | none |

A composite "readiness score" is **not** computed in v1. Its formula would be an invented domain fact (Q9, deferred item X4). The "panel reading" for R31 is the full vector of indicator values and statuses stored in a snapshot.

### 5.5 Alert kinds
Alerts are computed when needed, not stored. They are sorted by severity, then by due date.

| Kind | Trigger | Severity | Source |
|---|---|---|---|
| `CERT_EXPIRED` | An active person's latest certificate at a level has expired and is not marked `no_renewal` (D24) | critical | R25, R15 |
| `CERT_EXPIRING` | That certificate expires within P01 | warning | R25 |
| `MAINT_OVERDUE` | An in-service asset's due date (A06) is before the as-of date | critical | R26 |
| `MAINT_DUE_SOON` | Its due date falls within P02 | warning | R26 |
| `MAINT_SCHEDULE_UNKNOWN` | An in-service asset has neither an interval nor a next-due date | info (data quality, D) | I05 |
| `INDICATOR_WARNING` / `INDICATOR_CRITICAL` | An indicator value crosses a configured, enabled target | warning / critical | R27 |

---

## 6. Internationalisation

- **Languages:** pt-BR is the default on first start, whatever the Windows locale (F03). en-US and es-ES are available. The user switches through a Language menu and in Settings; the choice is saved in `prefs.json` in the data folder. A `--lang` option overrides it for one run.
- **Source strings:** written in English in the code. Use `QCoreApplication.translate("<Context>", "...")` with an explicit context constant per module. This avoids a PySide pitfall: with `self.tr()`, inherited methods take the subclass's context and lose their translation.
- **Catalogues:** one per area (`shell`, `personnel`, `infrastructure`, `exercises`, `budget`, `dashboard`, `alerts`, `settings`, `backup`, `reports`), times three languages. They are `.ts` XML files in `src/cbrn_dashboard/i18n/`, and the map from area to source folders is in `i18n/__init__.py`. *Reason:* agents working in parallel never edit the same catalogue.
  - `en_US` is a real catalogue too (identity translations plus English plural forms), so the completeness rule is the same for all three languages.
  - `.qm` files are compiled by `scripts/i18n.py compile`, by a session fixture in the tests and by the build. They are never committed (they go in `.gitignore`).
  - Running from source without compiled `.qm` files shows the English source strings and a status-bar warning; nothing is compiled silently.
- **Live switching:** the translator manager removes the old translators and installs the new ones — the app catalogues plus Qt's own `qtbase_*` translations where the wheel provides them — and sets the default `QLocale`. Qt then sends a `LanguageChange` event, and each widget's `retranslate()` re-applies its texts. Table models translate their headers on every `headerData` call.
- **Codes, not text, below the UI:** the domain and services layers return enum codes and parameters: alert kinds, validation error codes, statuses. Each UI area's `labels.py` maps codes to translated strings; a test makes sure every enum member has a label. Plural-aware messages use `%n`, for example "expires in %n day(s)".
- **User-defined list entries:** asset types, courses, metrics and funding sources store three labels. Display falls back from the current language to pt-BR, then en-US, then the code.
- **Dates and numbers:**
  - Dates are stored as ISO text and displayed with explicit four-digit-year patterns: pt-BR `dd/MM/yyyy`, es-ES `dd/MM/yyyy`, en-US `MM/dd/yyyy`. Date entry uses `QDateEdit` with a calendar pop-up.
  - Numbers, percentages and money are formatted and parsed with `QLocale`. The decimal separator is a comma for pt-BR and es-ES and a point for en-US. Currency symbols come from a small map (BRL→R$, EUR→€, USD→US$); other currencies show their ISO code.
  - Exports always use the locale-independent format (§4.3, D04).
- **Countries:** a `countries.json` file generated from CLDR (via Babel, development time only) holds names in all three languages, with the Unicode licence notice in `resources/THIRD_PARTY_DATA.md`.
- **Reports** are generated in a language chosen in the report dialog; the default is the current UI language.
- **Tests that keep the three languages complete** (`tests/i18n/`, `tests/ui/`):
  1. All three catalogues of each area contain the same set of source messages.
  2. No translation is unfinished, empty, obsolete or "vanished", and plural forms are complete.
  3. Placeholders match between source and translation (`%1`…`%9`, `%n`).
  4. **Sync check:** running `pyside6-lupdate` on a temporary copy of each catalogue adds or removes no messages, so every string in the code has been extracted.
  5. `pyside6-lrelease` compiles every catalogue without warnings.
  6. **Pseudo-locale check:** a test-only catalogue wraps every translation as `⟦…⟧`. Every registered page is opened and every widget text, title, action, tooltip and header is walked; any visible non-data text without the markers fails the test. This catches hard-coded strings and missing `retranslate()`.
  7. Every enum member (alert kinds, statuses, error codes) has a non-empty label in all three languages.
  8. Formatting tests assert exact strings for fixed dates, numbers and amounts in each locale (non-breaking spaces written explicitly).
- **Human review:** translations written during development are drafts. The committee reviews the terminology (Q14) before v1.0. Glossary terms are written from scratch, not taken from PTT 1 material or internal documents (F06).

---

## 7. Security and privacy

### 7.1 Data classification
- **Sensitive** (real data, local only): personnel records — qualifications of identifiable staff, which is personal data under Brazil's LGPD — infrastructure status and budget figures.
- **Public:** code, fictitious demo data, translations, documentation.

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
| No network code: a guard test forbids `socket`, `ssl`, `urllib`, `http`, `requests`, `webbrowser`, `PySide6.QtNetwork` and `QtWebEngine*`; Qt network and web libraries are excluded from the bundle; no update check, telemetry or crash upload; the app opens no sockets, so it causes no firewall prompts | 5 | T0.4, T0.9, T9.1 |
| Data minimisation: staff identified by an internal code with an optional label; no national ID numbers, birth dates, contact or health data (D17); exercise participants only as counts (D20) | 1, 2, 4 | P2, P4 |
| Per-user profile location; warnings for network paths and OneDrive (D02) | 4, 5 | T0.5, T7.5 |
| Full-disk encryption required by documentation and shown in a first-run notice (D03) | 1 | T7.5, `docs/data-protection.md` |
| Encrypted backups: Fernet (AES-128-CBC with HMAC-SHA256) with a key derived by scrypt (n=2^15, r=8, p=1, stored in the header so it can be raised later). The passphrase is never stored; a forgotten passphrase means the backup is unrecoverable, and the user is warned | 1, 6 | T7.2 |
| Decrypted temporary files only inside `<data>\tmp\`, deleted after use; `tmp\` emptied at start-up | 1, 4 | T7.3 |
| `PRAGMA secure_delete=ON` (limited on SSDs by wear levelling) | 1 | T1.2 |
| Anonymised report: counts only, no identifiers, notes or free text; personnel counts below the threshold suppressed (A11) | 2, 5 | T8.5 |
| Append-only change log (keeps old values; retention is Q12) | audit | T1.4 |
| Logs hold event codes only, never record contents (D22) | 2 | T1.8 |
| Demo data separated: own file, `DEMO` prefix, banner (D25) | 2 | T1.7 |
| Repository hygiene: `.gitignore` rules, a test over tracked files, contribution rules, a warning in the issue template | 2 | T0.3 |
| Content licensing: no clinical content (D19); no text from the WHO guide or internal documents; pull-request checklist | licence | T0.3 |
| Supply chain: `uv.lock` with hashes; GitHub Actions pinned by commit SHA; Dependabot; dependency-licence allow-list test; provenance attestation | integrity | T0.8, T9.2, T9.3, T9.5 |
| LGPD note: the institution is the data controller. The software supports minimisation, OS-level access control and deletion; the legal assessment belongs to the institution (Q4, Q11) | — | `docs/data-protection.md` |

---

## 8. Packaging and distribution

- **Target:** Windows 10 (1809 or later) and Windows 11, x64. No admin rights, no installer, no registry writes.
- **Artefact:** `cbrn-readiness-dashboard-<version>-win-x64.zip` contains one folder, `cbrn-readiness-dashboard\`, holding:
  - `cbrn-dashboard.exe` and `_internal\` (Python, Qt, catalogues, resources);
  - `licenses\` (third-party licence texts);
  - `README-first-run.{pt-BR,en-US,es-ES}.txt`;
  - `portable.ini.example`.

  The release also carries `SHA256SUMS.txt` and a build-provenance attestation.
- **First run:** extract the whole zip first. Running the program from inside Explorer's zip preview fails, because `_internal\` is missing. Verify the checksum with `Get-FileHash`. Optionally verify the attestation with `gh attestation verify` (this needs network access and is done by the user, not the app). If needed, unblock the zip in its file properties before extracting; on SmartScreen choose "More info → Run anyway". The first-run notice explains where the data lives and the disk-encryption requirement.
- **Locked-down machines:** AppLocker/WDAC or Smart App Control may block unsigned programs, or programs run from user-writable folders. IT can allow the executable by file hash; the hash changes with every release and is published in `SHA256SUMS.txt`. Only code signing (X6) removes this need. The one-folder build never needs to run code from `%TEMP%`.
- **Upgrades:** extract the new version to a new folder; the data in the profile is untouched. On first start the app backs up the database and migrates it. A database written by a newer version is refused, so downgrades are blocked.
- **Portable mode:** rename `portable.ini.example` to `portable.ini`; data then goes to `.\data\`. A warning explains that copying the folder copies the data.
- **Self-test:** `cbrn-dashboard.exe --self-test --data-dir <folder>` checks paths, migrations, the three languages, main-window creation, chart rendering, an encrypted-backup round trip and PDF rendering. It writes `selftest.json` and exits 0 or 1. The windowed executable has no console, hence the file. CI runs it on every build.
- **Licences:** the bundle contains every runtime dependency's licence text, together with GPL-3.0 and LGPL-3.0 and PyInstaller's bootloader exception notice. The About dialog shows the version, the GPL notice (no warranty), the source URL as plain text, and the component list. The release page links the matching source tag (GPL-3.0 §6).
- **Bundle checks:** the build test fails if numpy, matplotlib, `QtWebEngine` or `Qt6Network` appears in the bundle, and it prints the total size so growth is visible.

---

## 9. Testing strategy

- **Layers:**
  - `tests/domain/`: pure, fast and the majority. Table-driven, with a fixed clock.
  - `tests/storage/`: real SQLite files in `tmp_path`, migrations, constraints, backups.
  - `tests/services/`: integration of storage and domain on seeded fictitious data.
  - `tests/ui/`: pytest-qt with `QT_QPA_PLATFORM=offscreen`. View models and services do the computing; widget tests check wiring, validation messages and translation only.
  - `tests/i18n/`: §6.
  - `tests/reports/`: PDFs read back with pypdf; assertions on text, never pixels.
  - `tests/meta/`: ruff, mypy, forbidden-API and layering guards, repository hygiene, workflow pinning, dependency licences, documentation sync.
  - `tests/packaging/` (marker `packaging`): builds the executable and runs its self-test.
- **Determinism rules:**
  - No clock calls outside `clock.py` (guard test). Domain code takes `as_of` as a parameter; tests use `FixedClock`.
  - Random demo data uses a fixed seed.
  - Every file goes to `tmp_path`. An autouse session fixture points `CBRN_DASHBOARD_DATA_DIR` to a temporary folder, so tests can never touch a real data folder.
  - The offscreen platform is set in `tests/conftest.py` before Qt is imported.
  - Qt warnings fail tests (`qt_log_level_fail = WARNING`), except benign offscreen-platform messages listed by exact text in `qt_log_ignore`.
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

  A task that breaks another task's test is not done.
- **Translations travel with the code.** Every new user-visible string is added to its area's three catalogues by `uv run python scripts/i18n.py update`, then translated: pt-BR and es-ES in full, en-US as identity plus plural forms. These are drafts; the committee reviews the terminology later (Q14).
- **Schema changes** go only into the module's reserved migration file (`storage/migrations/README.md`). After the first tagged release (v0.1.0), migrations are append-only: fix forward with a new file, never edit a shipped one.
- **Nothing beyond the appendix is invented silently.** Any rule the appendix does not state is declared in `domain/config.py` with a `placeholder` flag, and the same commit adds it to §3.5 of this plan.
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
  T1.1 ─► T1.6
  T1.2 ─► T1.3 ─┬─► T1.4 (also T1.1) ─► T1.8 (also T0.5, T0.7)
                ├─► T1.5
                └─► T1.7 (also T0.7)
  T1.9 (needs T0.7, T1.5, T1.7)        T1.10 (needs T0.6)
Phases
  P0 ─► P1 ─┬─► P2 ─┐
            ├─► P3 ─┤
            ├─► P4 ─┼─► P6 ─► P8 ─► T9.1, T9.4 ─► P10
            ├─► P5 ─┘
            └─► P7 (in parallel with P2–P6)
  T9.2 and T9.3 can start any time after T0.9 (both are part of the MVP); T9.5 after T0.8.
```
What can run in parallel:
- **Phase 0:** after T0.1, tasks T0.2, T0.3, T0.4, T0.5 and T0.6 run in parallel (up to five agents). T0.7 waits for T0.5 and T0.6. T0.8 needs only T0.2, so it runs alongside T0.7. T0.9 comes last.
- **Phase 1:** T1.1, T1.2 and T1.10 start at once. T1.3 follows T1.2. Then T1.4, T1.5, T1.6 and T1.7 run in parallel. T1.8 and T1.9 close the phase.
- **Phases 2–5:** one agent per module, all in parallel. Inside a module, the schema task (T*.1) and the domain task (T*.2) run in parallel; then the repository and service task; then the UI and demo tasks in parallel. T4.2 (country data) depends only on T0.1 and can run at any time.
- **Phase 7** depends only on Phase 1 and T0.7, so it runs alongside Phases 2–6.
- **Phase 6** starts once Phases 2–5 have merged. Its alert-rule task T6.2 may begin as soon as the domain tasks T2.2 and T3.2 exist.
- **Conflict hot spots and their rules:**
  - Migration numbers are reserved in advance (T1.3).
  - Translation catalogues are split per area (D07).
  - A module registers itself with one line in each of `ui/shell/registry.py`, `domain/registry.py`, `demo/__init__.py`, `i18n/__init__.py` and `selftest.py`.
  - Before merging, rebase and rerun the whole default suite.

### 10.3 Phases

#### Phase 0 — Scaffolding (MVP)

**T0.1 — Project metadata and package skeleton** (S) · Depends on: —
- Files: `pyproject.toml`, `uv.lock`, `.python-version`, `src/cbrn_dashboard/__init__.py`, `src/cbrn_dashboard/__main__.py`, `tests/test_package.py`.
- Work:
  - hatchling build backend with the src layout;
  - PEP 639 licence metadata (`license = "GPL-3.0-or-later"`, `license-files = ["LICENSE"]`);
  - the version kept once, in `__init__.py`, and read by hatch;
  - runtime dependency `PySide6>=6.8,<7`;
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
  - pytest settings: `testpaths = ["tests"]`, markers `ui`, `packaging`, `slow`, `addopts = -m "not packaging"`, `qt_api = "pyside6"`, `qt_log_level_fail = "WARNING"`, and `qt_log_ignore` listing the benign offscreen-platform messages by exact text.
- Accept: the test runs `ruff check`, `ruff format --check` and mypy through `sys.executable -m …` and asserts each exits 0. A deliberately bad file in `tmp_path` is reported, which proves the gate works.
- Check: `uv run pytest tests/meta/test_tooling.py`

**T0.3 — Repository hygiene, ignore rules and contribution rules** (S) · Depends on: T0.1
- Files: `.gitignore` (append), `CONTRIBUTING.md`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `tests/meta/test_repo_hygiene.py`.
- Work:
  - Append `/data/`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.db-journal`, `*.cbrnbak`, `*.qm`, `portable.ini` and `/scratch/` to `.gitignore`.
  - `CONTRIBUTING.md` sets out the rules of §10.1 and §7: no real data in code, tests, issues or screenshots; no WHO-guide or internal-document text; no clinical content; the SPDX header; translations with every UI string; one task per commit; the forbidden folder names of §4.4.
  - The pull-request template has a checklist for these rules. The issue template warns against pasting real data.
- Accept, checked against `git ls-files`:
  - no tracked file matches a database, backup or compiled-catalogue pattern;
  - every tracked `.py` file starts with the SPDX line;
  - no tracked file is larger than 1 MB unless it is on an explicit allow-list.

  The test skips when not run inside a git work tree.
- Check: `uv run pytest tests/meta/test_repo_hygiene.py`

**T0.4 — Layering and forbidden-API guard tests** (S) · Depends on: T0.1
- Files: `tests/meta/test_forbidden_apis.py`, `tests/meta/_ast_rules.py`.
- Accept: an AST scan of `src/` fails on any of the following.
  - Imports of `socket`, `ssl`, `urllib`, `http`, `ftplib`, `smtplib`, `requests`, `httpx`, `webbrowser`, `PySide6.QtNetwork` or `PySide6.QtWebEngine*`.
  - Calls to `date.today`, `datetime.now`, `datetime.utcnow` or `time.time` outside `clock.py`.
  - Any PySide6 import in `domain/`, `services/`, `storage/`, `reports/model.py` or `reports/anonymise.py`.
  - Any `sqlite3` import in `ui/`.
  - Any import of `storage` or `services` from `domain/`.

  Each rule has a self-test on small fictitious snippets that it must catch.
- Check: `uv run pytest tests/meta/test_forbidden_apis.py`

**T0.5 — Data-location resolution** (M) · Depends on: T0.1
- Files: `src/cbrn_dashboard/paths.py`, `tests/test_paths.py`.
- Work:
  - Implement the D02 order: `--data-dir`, then `CBRN_DASHBOARD_DATA_DIR`, then `portable.ini` beside the executable, then `%LOCALAPPDATA%\cbrn-readiness-dashboard\`.
  - Return a result holding the path, its source, a writable flag and a list of warnings: network path (UNC or a mapped network drive) and OneDrive-synced folder (prefixes from `OneDrive`, `OneDriveCommercial` and `OneDriveConsumer`).
  - The writability probe and the network-drive lookup are injectable functions.
  - Create the folder if it is missing. Never fall back to another location silently.
  - Pure Python, no Qt.
- Accept:
  - every precedence branch resolves correctly;
  - the portable marker is honoured for a simulated frozen executable;
  - UNC and OneDrive paths produce the matching warnings;
  - a fake non-writable probe is reported as non-writable, not replaced by another location;
  - the real probe returns true for `tmp_path`.
- Check: `uv run pytest tests/test_paths.py`

**T0.6 — Translation framework and catalogue tests** (M) · Depends on: T0.1
- Files: `src/cbrn_dashboard/ui/shell/i18n.py`, `src/cbrn_dashboard/i18n/__init__.py`, `src/cbrn_dashboard/i18n/shell_pt_BR.ts`, `shell_en_US.ts`, `shell_es_ES.ts`, `scripts/i18n.py` (`update` and `compile` subcommands), `tests/conftest.py`, `tests/i18n/test_catalogues.py`, `tests/i18n/test_catalogues_in_sync.py`.
- Work:
  - The translator manager of §6: install and remove translators, load Qt base translations where present, set the default `QLocale`.
  - `tests/conftest.py` sets the offscreen platform before Qt is imported, points `CBRN_DASHBOARD_DATA_DIR` at a temporary folder for the whole session (autouse), compiles every `.ts` into a temporary `.qm` folder (session fixture), and provides the pseudo-locale catalogue builder.
- Accept:
  - checks 1–5 and 7 of §6 pass for the shell catalogue; check 6, the pseudo-locale walk, arrives with T1.9;
  - the manager loads each language and translates a known shell string;
  - an unknown language code is rejected.
- Check: `uv run pytest tests/i18n`

**T0.7 — Application bootstrap, empty main window and self-test** (M) · Depends on: T0.5, T0.6
- Files: `src/cbrn_dashboard/cli.py`, `app.py`, `selftest.py`, `ui/shell/main_window.py`, `__main__.py` (update), `i18n/shell_*.ts` (update), `tests/test_cli.py`, `tests/ui/test_main_window.py`, `tests/test_selftest.py`.
- Work:
  - Command-line options `--data-dir`, `--lang {pt-BR,en-US,es-ES}`, `--self-test` and `--version`; `--demo` comes in T1.7.
  - The main window has a translated title, an empty navigation list, a Language menu with three entries, a status bar showing the data folder, and Quit.
  - The self-test is a registry of checks — Python, Qt, paths, i18n in three languages, main window — that writes `selftest.json` to the data folder and exits 0 or 1.
- Accept:
  - The window opens offscreen with the translated title in each language.
  - Choosing a language in the menu retitles the window live.
  - The window closes without Qt warnings.
  - `main(["--self-test", "--data-dir", <tmp>])` returns 0, and the JSON lists every check as passed.
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
  - Drive PyInstaller through its Python API: onedir, windowed, no UPX, name `cbrn-dashboard`, the icon, and the compiled `.qm` files (from `scripts/i18n.py compile`) as data.
  - Exclude `QtNetwork`, `QtWebEngine*`, `QtQml`, `QtQuick`, `Qt3D*`, `QtMultimedia`, `QtBluetooth`, `QtPositioning`, `QtSql`, `numpy`, `matplotlib` and `tkinter`.
  - Output and work folders are parameters.
  - The CI `build` job (it needs `test`) runs `uv run pytest -m packaging` and uploads the zipped folder as an artefact kept for 14 days.
- Accept:
  - the build succeeds into `tmp_path`;
  - `cbrn-dashboard.exe --self-test --data-dir <tmp>`, run offscreen, exits 0 with every check passed;
  - the bundle contains the three shell `.qm` files and Qt's offscreen platform plugin;
  - the bundle contains no `Qt6Network.dll`, numpy, matplotlib or QtWebEngine;
  - the total size is printed.
- Check: `uv run pytest -m packaging tests/packaging/test_build.py`

#### Phase 1 — Foundations: storage, configuration, indicators, shell (MVP)

**T1.1 — Clock and date arithmetic** (S) · Depends on: T0.4
- Files: `src/cbrn_dashboard/clock.py`, `src/cbrn_dashboard/domain/dates.py`, `tests/domain/test_dates.py`.
- Accept:
  - a `Clock` interface with `SystemClock` and `FixedClock`;
  - adding months clamps to the month's end (31 January plus one month gives 28 or 29 February, leap years included);
  - the days between two dates are signed;
  - strict ISO date parsing rejects `2025-2-3`;
  - UTC timestamps are formatted with a trailing `Z`.
- Check: `uv run pytest tests/domain/test_dates.py`

**T1.2 — Database opening and SQLite version check** (S) · Depends on: T0.1
- Files: `src/cbrn_dashboard/storage/db.py`, `tests/storage/test_db.py`.
- Work:
  - `open_database(path, read_only=False)` applies the D06 settings: explicit transactions, foreign keys on, `journal_mode=DELETE`, `synchronous=FULL`, `secure_delete=ON`, and a busy timeout.
  - Read-only mode uses a `mode=ro` URI.
  - A `transaction()` context manager.
  - A start-up check for SQLite 3.37 or later, needed for `STRICT` tables.
- Accept:
  - foreign keys are enforced;
  - a read-only connection rejects writes with `ReadOnlyDatabaseError`;
  - a transaction commits on success and rolls back on an exception;
  - an injected older version number makes the check raise a clear error;
  - the pragmas read back with the expected values.
- Check: `uv run pytest tests/storage/test_db.py`

**T1.3 — Migration runner and core schema** (M) · Depends on: T1.2
- Files: `storage/migrate.py`, `storage/migrations/__init__.py`, `storage/migrations/0001_core.sql` (§5.2, including the `change_log` triggers), `storage/migrations/README.md`, `selftest.py` (add a "database" check), `tests/storage/test_migrate.py`.
- Accept:
  - A fresh database is brought to the latest `user_version`; running again changes nothing.
  - A database with a newer version raises `DatabaseTooNewError` and is left untouched.
  - A deliberately broken migration in a temporary migrations package rolls back and leaves the version unchanged.
  - A non-empty database is copied with the backup API before migrating. T7.1 later moves this helper into `storage/backup.py`.
  - Migrations are loaded through `importlib.resources`.
  - The README reserves 0002 personnel, 0003 infrastructure, 0004 exercises, 0005 budget, 0006 indicator targets and 0007 snapshots.
- Check: `uv run pytest tests/storage/test_migrate.py`

**T1.4 — Repository helpers with the append-only change log** (M) · Depends on: T1.3, T1.1
- Files: `src/cbrn_dashboard/storage/repository.py`, `tests/storage/test_repository.py`.
- Accept:
  - The insert, update and delete helpers each write exactly one `change_log` row in the same transaction. The row has the right `entity`, `entity_id`, `action`, `before_json` and `after_json`, the operator label, and a UTC time taken from the `Clock`.
  - A rollback removes both the change and its log row.
  - A direct `UPDATE` or `DELETE` on `change_log` raises, because of the triggers (D05).
- Check: `uv run pytest tests/storage/test_repository.py`

**T1.5 — Readiness configuration, placeholders and UI preferences** (M) · Depends on: T1.3
- Files: `domain/config.py`, `storage/settings_repo.py`, `src/cbrn_dashboard/prefs.py`, `app.py` (language from preferences), `tests/domain/test_config.py`, `tests/storage/test_settings_repo.py`, `tests/test_prefs.py`.
- Work:
  - `ReadinessConfig` holds:
    - P01–P07 with their `placeholder` flags;
    - the A02 level-hierarchy switch (off);
    - the A05 "degraded counts as available" switch (off);
    - optional validity months per PPE level (A04, not set);
    - the default currency (A08, BRL);
    - the small-count threshold (A11, 5);
    - the institution and unit names (D18, empty);
    - the operator label (D05).

    It is stored in the `setting` table.
  - `prefs.json` in the data folder holds the language, the "first-run notice shown" flag and the start-up summary toggle. It is written atomically.
- Accept:
  - the defaults and placeholder flags match §3.5 exactly;
  - invalid values (negative days, a threshold below 1) are rejected with error codes;
  - the configuration round-trips through the database;
  - confirming a placeholder clears its flag;
  - preferences round-trip, and a corrupt `prefs.json` falls back to the defaults with a warning;
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
  - `--demo` opens `<data>\demo\demo.sqlite3`. The real database is neither created nor modified (checked by its existence and modification time).
  - `app_meta.is_demo` is `1`.
  - The generator is seeded and deterministic: two runs give identical rows.
  - Every generated identifier starts with `DEMO` (D25).
  - Module generators register with one line each.
- Check: `uv run pytest tests/demo/test_demo_framework.py`

**T1.8 — Logging and crash handling without record contents** (S) · Depends on: T0.5, T0.7, T1.4
- Files: `src/cbrn_dashboard/logging_setup.py`, `app.py` (exception hook), `tests/test_logging.py`.
- Accept:
  - A rotating log is kept at `<data>\logs\app.log` (1 MB × 3).
  - An unhandled exception writes its traceback to the log and is reported through an injectable callback, which T1.9 wires to a translated error dialog. Nothing is uploaded.
  - In a scenario that writes a record with a distinctive fictitious identifier through the T1.4 helpers, the identifier does not appear in the log (D22).
- Check: `uv run pytest tests/test_logging.py`

**T1.9 — Shell: module registry, as-of date, read-only mode, banners and prompts** (M) · Depends on: T0.7, T1.5, T1.7
- Files: `ui/shell/registry.py`, `ui/shell/context.py`, `ui/shell/prompts.py`, `ui/shell/banners.py`, `ui/shell/main_window.py` (update), `i18n/shell_*.ts` (update), `tests/ui/test_shell.py`, `tests/ui/test_no_hardcoded_strings.py`.
- Work:
  - `AppContext` holds the services, the clock, the as-of date (default today, with a selector in the toolbar, D13), the read-only flag and the demo flag, and emits change signals.
  - A page registry, one line per module.
  - A prompts interface wrapping message boxes and file dialogs; tests substitute a fake. The T1.8 crash callback is wired to it.
  - A banner area for the demo banner (D25), the read-only banner, location warnings and the permanent preliminary notice (I06, P07).
  - The pseudo-locale walk (check 6 of §6) over every registered page.
- Accept:
  - a page registered in the test appears in the navigation;
  - changing the as-of date emits exactly one signal;
  - read-only mode disables every action registered as an edit;
  - the demo flag shows the demo banner;
  - the preliminary notice is always visible;
  - the pseudo-locale walk passes for the shell.
- Check: `uv run pytest tests/ui/test_shell.py tests/ui/test_no_hardcoded_strings.py`

**T1.10 — Locale formatting and parsing** (S) · Depends on: T0.6
- Files: `src/cbrn_dashboard/ui/shell/formatting.py`, `tests/ui/test_formatting.py`.
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
  - Deleting a staff member deletes their certificates, training records and degrees.
  - A course that is in use cannot be deleted.
- Check: `uv run pytest tests/storage/test_schema_personnel.py`

**T2.2 — Personnel rules and indicators** (M) · Depends on: T1.1, T1.5, T1.6 · Parallel with: T2.1
- Files: `domain/personnel.py`, `domain/registry.py` (one line), `tests/domain/test_personnel.py`.
- Work: pure functions over plain data objects. Every function takes the as-of date *d*.
  - A person is active when `active_from` ≤ *d* and either `active_until` is empty or *d* ≤ `active_until`.
  - A certificate is valid on *d* when `issued_on` ≤ *d* ≤ `valid_until`. For each person and level, only the latest certificate (by `valid_until`) counts.
  - A certificate is "expiring" when it is the latest one, valid on *d*, has `valid_until` ≤ *d* + P01, and is not marked `no_renewal` (D24).
  - "Retraining needed" follows A03. The function returns the list of staff identifiers for the retraining and expiring views (R36).
  - Level hierarchy (A02):
    - with the switch off, levels are counted independently;
    - with it on, a certificate also counts for the levels mapped as covered by it in Settings. The mapping stays empty until Q2 is answered.
  - Validity pre-fill (A04): the proposed `valid_until` is `issued_on` plus the level's validity months when they are configured; otherwise there is no proposal.
  - Indicators, as defined in §5.4:
    - `PERS_CERT_VALID`, `PERS_CERT_EXPIRING` and `PERS_RETRAINING_NEEDED`, with dimension level;
    - `PERS_DEGREE`, with dimensions level and status;
    - `PERS_TRAINING_12M`.
- Accept: table-driven tests with `FixedClock` show that:
  - a certificate whose `valid_until` equals the as-of date is still valid that day and counts as expiring;
  - inactive staff are never counted;
  - two certificates at the same level count once;
  - `no_renewal` certificates are left out of both "expiring" and "retraining needed";
  - A02 behaves as specified both off and on (with a test mapping);
  - the training window is (*d* − 12 months, *d*];
  - degrees are counted per level and status;
  - a past as-of date gives that past reading (I03).
- Check: `uv run pytest tests/domain/test_personnel.py`

**T2.3 — Personnel repository and service** (M) · Depends on: T2.1, T2.2, T1.4
- Files: `storage/personnel_repo.py`, `services/personnel.py`, `tests/services/test_personnel_service.py`.
- Work:
  - Create, read, update and delete staff members, certificates, training records, courses and degrees through the T1.4 helpers.
  - "Deactivate" and "delete" are separate actions. Deactivate sets `active_until` and keeps the history. Delete is for entry mistakes and removes the dependent rows too.
  - Validation returns error codes, never text: for example `VALID_UNTIL_BEFORE_ISSUED`, `DUPLICATE_IDENTIFIER`, `COURSE_IN_USE`.
  - Summaries and lists for an as-of date are built by loading rows and calling the T2.2 functions.
- Accept:
  - every write produces its `change_log` row;
  - a deactivated person keeps their records and drops out of the counts after `active_until`;
  - deleting a person removes their dependent rows;
  - on a fictitious fixture, the service summaries equal the domain results computed directly;
  - validation failures come back as codes.
- Check: `uv run pytest tests/services/test_personnel_service.py`

**T2.4 — Personnel page, dialogs and translations** (M) · Depends on: T2.3, T1.9, T1.10
- Files: `ui/personnel/page.py`, `ui/personnel/models.py`, `ui/personnel/dialogs.py`, `ui/personnel/labels.py`, `i18n/personnel_pt_BR.ts`, `i18n/personnel_en_US.ts`, `i18n/personnel_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_personnel_page.py`.
- Work:
  - A staff table with filters: active, level, needs retraining.
  - A detail view showing the person's certificates, training records and degrees.
  - One dialog per record type, with date pickers. The certificate dialog pre-fills `valid_until` from A04.
  - Summary counts per level for the as-of date.
  - A course-list editor.
  - A module settings section — the A02 mapping, the A04 validity months and the course list (A09) — that T6.1 places under Settings → Personnel.
  - Labels for PPE levels, degree levels and statuses, and error codes.
- Accept:
  - Adding a staff member and a certificate through the dialogs makes the row appear, with dates formatted for the current language.
  - A `valid_until` before `issued_on` shows the translated error.
  - Changing the as-of date updates the counts.
  - Read-only mode disables every edit.
  - The pseudo-locale walk passes on the page.
  - Every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_personnel_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T2.5 — Personnel demo generator** (S) · Depends on: T2.3, T1.7 · Parallel with: T2.4
- Files: `demo/personnel.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_personnel.py`.
- Accept: data is generated relative to the clock, and includes:
  - staff `DEMO-P001`, `DEMO-P002`, and so on;
  - at least one person in each state: valid, expiring within P01, expired, `no_renewal`, inactive;
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
  - `tag` is unique;
  - a type in use cannot be deleted;
  - deleting an asset deletes its status and maintenance events.
- Check: `uv run pytest tests/storage/test_schema_infrastructure.py`

**T3.2 — Infrastructure rules and indicators** (M) · Depends on: T1.1, T1.5, T1.6 · Parallel with: T3.1
- Files: `domain/infrastructure.py`, `domain/registry.py` (one line), `tests/domain/test_infrastructure.py`.
- Work: pure functions, each taking the as-of date *d*.
  - An asset is in service when `in_service_from` ≤ *d* and either `in_service_until` is empty or *d* ≤ `in_service_until`.
  - Its status on *d* is that of the latest status event with `effective_on` ≤ *d*. With no event, the status is "unknown": not available, and flagged as a data-quality issue.
  - "Available" means operational. If the A05 switch is on, degraded also counts as available.
  - The due date follows A06:
    - the `next_due_on` of the latest maintenance on or before *d*, if recorded;
    - otherwise the latest `performed_on` (or `in_service_from` when there is none) plus the asset's interval, or else its type's default interval;
    - otherwise "schedule unknown".
  - Maintenance recorded after *d* is ignored.
  - An asset is overdue when its due date is before *d*, and due soon when *d* ≤ due date ≤ *d* + P02.
  - The functions return lists by asset tag for the maintenance views (R36).
  - Indicators `INFRA_AVAILABLE` and `INFRA_MAINT_OVERDUE`, with dimension asset type (§5.4).
- Accept: table-driven tests with `FixedClock` cover:
  - status changes before, on and after *d*;
  - retired and not-yet-in-service assets being excluded;
  - the A05 switch both off and on;
  - every A06 branch (explicit next-due date, last maintenance plus interval, in-service date plus interval, asset override versus type default, unknown);
  - overdue and due-soon boundaries;
  - a past as-of date giving the past reading (I03).
- Check: `uv run pytest tests/domain/test_infrastructure.py`

**T3.3 — Infrastructure repository and service** (M) · Depends on: T3.1, T3.2, T1.4
- Files: `storage/infrastructure_repo.py`, `services/infrastructure.py`, `tests/services/test_infrastructure_service.py`.
- Work:
  - Creating an asset requires an initial status, which is recorded as a status event dated `in_service_from`.
  - Changing status adds a new event.
  - Recording maintenance adds a `maintenance_event`.
  - "Retire" (sets `in_service_until`) is separate from "delete" (for entry mistakes).
  - Asset types can be created and edited, with labels in three languages and a default interval. Built-in types can be deactivated but not deleted.
  - Error codes include `DUPLICATE_TAG`, `STATUS_DATE_TAKEN`, `TYPE_IN_USE` and `BUILT_IN_TYPE`.
- Accept:
  - every write produces its `change_log` row;
  - a new asset without an initial status is rejected;
  - on a fictitious fixture, the service availability and due lists equal the domain results;
  - deleting a built-in type returns `BUILT_IN_TYPE`.
- Check: `uv run pytest tests/services/test_infrastructure_service.py`

**T3.4 — Infrastructure page, dialogs and translations** (M) · Depends on: T3.3, T1.9, T1.10
- Files: `ui/infrastructure/page.py`, `ui/infrastructure/models.py`, `ui/infrastructure/dialogs.py`, `ui/infrastructure/labels.py`, `i18n/infrastructure_pt_BR.ts`, `i18n/infrastructure_en_US.ts`, `i18n/infrastructure_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_infrastructure_page.py`.
- Work:
  - An asset table grouped by type. For the as-of date it shows the current status, the last maintenance, the next due date and the overdue, due-soon and unknown-schedule flags.
  - Dialogs for an asset, a status change and a maintenance record, plus the history of each asset.
  - An availability summary per type.
  - A module settings section — the asset-type editor with labels in three languages and default intervals (A06), and the A05 switch — that T6.1 places under Settings → Infrastructure.
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
- Files: `scripts/gen_countries.py`, `src/cbrn_dashboard/resources/countries.json`, `src/cbrn_dashboard/resources/THIRD_PARTY_DATA.md`, `pyproject.toml` (a `tools` dependency group with Babel), `tests/test_countries.py`.
- Work:
  - Using Babel at development time only, generate the two-letter CLDR region codes. Leave out the codes that are not countries (`EU`, `EZ`, `UN`, `QO`, `ZZ`).
  - Each code gets its names in pt_BR, en_US and es_ES. The CLDR version is recorded in the JSON.
  - `THIRD_PARTY_DATA.md` carries the Unicode-3.0 notice.
- Accept:
  - codes are unique and consist of two uppercase letters;
  - every code has three non-empty names;
  - the JSON records the CLDR version;
  - the notice file exists and names the Unicode licence;
  - Babel is not a runtime dependency (it is absent from `[project.dependencies]`).
- Check: `uv run pytest tests/test_countries.py`

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
  - a past as-of date giving the past reading.
- Check: `uv run pytest tests/domain/test_exercises.py`

**T4.4 — Exercises repository and service** (M) · Depends on: T4.1, T4.2, T4.3, T1.4
- Files: `storage/exercises_repo.py`, `services/exercises.py`, `tests/services/test_exercises_service.py`.
- Work:
  - Editions can be created, edited and deleted, together with their country lists, results and metrics (labels in three languages, unit, scale, direction).
  - Country codes are checked against `countries.json`, loaded with `importlib.resources`.
  - A result is checked against its metric's scale.
  - Error codes include `DUPLICATE_CODE`, `UNKNOWN_COUNTRY`, `VALUE_OUT_OF_SCALE` and `METRIC_IN_USE`.
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
  - A module settings section — the metric editor (A07) — that T6.1 places under Settings → Exercises.
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
  - Create the tables `funding_source` and `budget_entry` as in §5.2.
  - Seed the built-in sources `DIRSA` and `OPCW_TRUST_FUND`, as named in L80 (D16). They have `built_in = 1` and empty label columns (their names come from `labels.py`).
- Accept:
  - both built-in sources exist after the migration;
  - a `currency` whose length is not 3 is rejected;
  - a source in use cannot be deleted.
- Check: `uv run pytest tests/storage/test_schema_budget.py`

**T5.2 — Budget rules and indicator** (S) · Depends on: T1.1, T1.6 · Parallel with: T5.1
- Files: `domain/budget.py`, `domain/registry.py` (one line), `tests/domain/test_budget.py`.
- Work: pure functions.
  - Totals are computed per (`fiscal_year`, source, currency). Allocated is the sum of the entered amounts, or "missing" when every amount is empty. Executed is the sum of executed amounts.
  - Execution rate = executed ÷ allocated. It is No data when allocated is missing or zero.
  - Amounts are never added across currencies (D15).
  - The fiscal year of a date is its calendar year (A08).
  - A multi-year table supports budget planning (R36).
  - Indicator `BUD_EXEC_RATE`, with dimensions source and currency, for the fiscal year of the as-of date (§5.4).
- Accept: table-driven tests cover:
  - totals across several entries;
  - a rate with zero and with missing allocated amounts;
  - two currencies kept apart;
  - the fiscal year at the 31 December / 1 January boundary;
  - integer minor-unit arithmetic with no floating-point error in the totals.
- Check: `uv run pytest tests/domain/test_budget.py`

**T5.3 — Budget repository and service** (S) · Depends on: T5.1, T5.2, T1.4
- Files: `storage/budget_repo.py`, `services/budget.py`, `tests/services/test_budget_service.py`.
- Work:
  - Budget entries can be created, edited and deleted. Funding sources can be created and edited with labels in three languages. Built-in sources can be deactivated but not deleted.
  - The service works in minor units only; parsing the amounts users type is the UI's job (T1.10).
  - Rejecting negative amounts is a design decision added to §3.5 by this task: corrections are made by editing the entry, and every edit is recorded in `change_log`.
  - Error codes include `NEGATIVE_AMOUNT`, `INVALID_CURRENCY` (anything other than three uppercase letters), `SOURCE_IN_USE` and `BUILT_IN_SOURCE`.
- Accept:
  - every write produces its `change_log` row;
  - each invalid case returns its code;
  - on a fictitious fixture, the service totals equal the domain results;
  - new entries use the configured default currency (A08).
- Check: `uv run pytest tests/services/test_budget_service.py`

**T5.4 — Budget page, dialogs and translations** (M) · Depends on: T5.3, T1.9, T1.10
- Files: `ui/budget/page.py`, `ui/budget/models.py`, `ui/budget/dialogs.py`, `ui/budget/labels.py`, `i18n/budget_pt_BR.ts`, `i18n/budget_en_US.ts`, `i18n/budget_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/ui/test_budget_page.py`.
- Work:
  - A year selector that defaults to the as-of date's fiscal year.
  - A summary table per source and currency, showing allocated, executed and execution rate.
  - A list of entries.
  - An entry dialog that takes the amount typed in the locale's format.
  - A module settings section — the funding-source editor and the default currency (A08) — that T6.1 places under Settings → Budget.
  - Labels for the built-in sources and the error codes.
- Accept:
  - an amount typed as `1.234,56` in pt-BR or es-ES, or as `1,234.56` in en-US, is stored as 123456 minor units and shown back in the locale's format;
  - the summary updates after each edit;
  - two currencies appear on separate rows;
  - read-only mode disables every edit;
  - the pseudo-locale walk passes;
  - every enum value and error code has a label in all three languages.
- Check: `uv run pytest tests/ui/test_budget_page.py tests/ui/test_no_hardcoded_strings.py tests/i18n`

**T5.5 — Budget demo generator** (S) · Depends on: T5.3, T1.7 · Parallel with: T5.4
- Files: `demo/budget.py`, `demo/__init__.py` (one line), `tests/demo/test_demo_budget.py`.
- Accept: the generated data includes:
  - entries for several fiscal years for both built-in sources;
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
    - The module sections delivered by T2.4, T3.4, T4.5 and T5.4, placed under Personnel, Infrastructure, Exercises and Budget.
    - Further sections registered by later tasks (T7.4 Backup, T8.7 Reports and Snapshots), one line each.
  - Every placeholder value shows the "placeholder — to be confirmed" badge (§3.5).
- Accept:
  - targets round-trip and every change writes a `change_log` row;
  - targets in the wrong order for the indicator's direction are rejected with `TARGET_ORDER`;
  - an indicator without a target evaluates to No target, and a disabled target behaves as if absent;
  - the placeholder badge shows until the value is confirmed or changed, and confirming clears it;
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
  - there is one certificate alert per person and level, and one maintenance alert per asset;
  - `no_renewal` suppresses certificate alerts (D24);
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
- Accept:
  - every alert kind, in each of the three languages, gives a non-empty message with every placeholder filled;
  - plural forms are correct for 1 and for 2 days;
  - the filters work;
  - activating an alert switches to the right page;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_alerts_page.py tests/ui/test_alert_labels.py tests/ui/test_no_hardcoded_strings.py`

**T6.4 — Chart adapter (Qt Charts)** (S) · Depends on: T1.9
- Files: `ui/shell/charts.py`, `selftest.py` (add the "chart" check), `tests/ui/test_charts.py`.
- Work:
  - Build bar and grouped-bar charts from plain chart data (categories, series, values, unit).
  - Render a chart to an image, for PDFs.
  - Use one colour-blind-safe palette (Okabe–Ito), defined as a constant.
  - With no data, show a translated "No data" text instead of an empty chart.
  - No module outside this file imports Qt Charts (D08).
- Accept:
  - the built chart's categories, series and values equal the input;
  - rendering offscreen gives a non-empty image of the requested size;
  - empty input gives the "No data" text;
  - the self-test "chart" check passes;
  - an AST check in the test confirms that `PySide6.QtCharts` is imported only in `ui/shell/charts.py`.

  No pixel comparisons are made.
- Check: `uv run pytest tests/ui/test_charts.py`

**T6.5 — Dashboard service and overview page** (M) · Depends on: T6.1, T6.2, T6.4
- Files: `services/dashboard.py`, `ui/dashboard/page.py`, `ui/dashboard/models.py`, `ui/dashboard/labels.py`, `i18n/dashboard_pt_BR.ts`, `i18n/dashboard_en_US.ts`, `i18n/dashboard_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/registry.py` (one line), `tests/services/test_dashboard_service.py`, `tests/ui/test_dashboard_page.py`.
- Work:
  - A Qt-free `DashboardData` for an as-of date holds:
    - one tile per indicator and dimension, with its value, status and target;
    - alert counts by severity;
    - chart data: staff with a valid certificate per level; availability per asset type; participants and countries per edition; allocated versus executed per source for the fiscal year.
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
  - At start-up, if alerts exist and the start-up summary preference (T1.5) is on, a summary banner appears with a button that opens the Alerts page. The preference defaults to on.
  - The counts are refreshed whenever the as-of date or the data changes.
- Accept:
  - with alerts, the badge and summary appear, and the button opens the Alerts page;
  - with no alerts, no summary appears;
  - with the preference off, no summary appears but the badge stays;
  - the counts update after the as-of date changes and after a data change (R05).
- Check: `uv run pytest tests/ui/test_startup_summary.py`

#### Phase 7 — Backup, restore and data protection (MVP)
This phase covers I02, R33 and D02–D04. It depends only on Phase 1 and T0.7, so it runs in parallel with Phases 2–6.

**T7.1 — Consistent local backups and rotation** (S) · Depends on: T1.3, T1.5
- Files: `storage/backup.py`, `services/backup.py`, `storage/migrate.py` (switch to the shared helper), `tests/storage/test_backup.py`.
- Work:
  - Copy the database with SQLite's online backup API into `<data>\backups\`. File names carry a UTC timestamp and the schema version.
  - Make a daily backup at the first start of each day.
  - The pre-migration backup from T1.3 moves to this helper.
  - Rotation keeps the newest P06 copies (7).
- Accept:
  - a copy taken while another connection holds an open write transaction still passes `PRAGMA integrity_check` and contains only committed data;
  - the daily backup is made once per day, however many times the app starts;
  - the pre-migration backup goes through the same helper;
  - rotation keeps exactly P06 files and deletes the oldest;
  - nothing is written outside the data folder.
- Check: `uv run pytest tests/storage/test_backup.py`

**T7.2 — Encrypted backup container** (M) · Depends on: T7.1
- Files: `pyproject.toml` (add `cryptography` as a runtime dependency), `storage/crypto_backup.py`, `selftest.py` (add the "encrypted backup" check), `tests/storage/test_crypto_backup.py`.
- Work:
  - The `.cbrnbak` format of D04:
    - a header with magic `CBRNBAK1`, the format version, the scrypt parameters (n = 2^15, r = 8, p = 1, with an explicit memory limit), a random salt, the app version and the schema version;
    - followed by a Fernet token holding the bytes of a consistent copy made with the T7.1 helper.
  - The key is derived with the standard library's `hashlib.scrypt`.
  - The service enforces the minimum passphrase length P05 (12 characters).
  - Errors: `WrongPassphraseError`, `CorruptBackupError`, `BackupTooNewError`.
- Accept:
  - a round trip returns a database identical to the source;
  - a wrong passphrase raises `WrongPassphraseError`;
  - a flipped byte or a truncated file raises `CorruptBackupError`;
  - an unknown format version, or a schema newer than the app, raises `BackupTooNewError`;
  - two backups of the same database differ, because each has its own salt;
  - a passphrase shorter than P05 is rejected;
  - the passphrase bytes appear neither in the output file nor anywhere in the data folder;
  - the self-test "encrypted backup" check passes.
- Check: `uv run pytest tests/storage/test_crypto_backup.py`

**T7.3 — Restore service** (M) · Depends on: T7.2
- Files: `services/restore.py`, `app.py` (empty `<data>\tmp\` at start-up), `tests/services/test_restore.py`.
- Work: the restore sequence of D04:
  1. Decrypt only into `<data>\tmp\`.
  2. Run `integrity_check`.
  3. Check the schema version.
  4. Migrate the temporary copy if it is older.
  5. Close the open connections.
  6. Keep a safety copy, `<db>.before-restore-<UTC timestamp>`.
  7. Swap the files atomically.
  8. Reopen.
  9. Write a `change_log` row with action `restore` in the restored database.
- Accept:
  - a backup made with an older schema is restored and migrated;
  - a wrong passphrase, a corrupt file, a failed integrity check or a too-new schema each leave the current database byte-identical;
  - the safety copy exists after a successful restore;
  - the decrypted temporary file is created only inside `<data>\tmp\` and removed after both success and failure;
  - leftovers in `<data>\tmp\` are removed at start-up;
  - the `restore` row exists.
- Check: `uv run pytest tests/services/test_restore.py`

**T7.4 — Backup and restore user interface** (S) · Depends on: T7.3, T1.9
- Files: `ui/backup/actions.py`, `ui/backup/dialogs.py`, `ui/backup/labels.py`, `i18n/backup_pt_BR.ts`, `i18n/backup_en_US.ts`, `i18n/backup_es_ES.ts`, `i18n/__init__.py` (one line), `ui/shell/main_window.py` (File menu entries), `tests/ui/test_backup_ui.py`.
- Work:
  - File menu entries: "Back up…", "Restore…" and "Open data folder", which opens the local folder in Explorer — a local action, not a network one.
  - The passphrase dialog asks for the passphrase twice, enforces P05 and warns that a lost passphrase cannot be recovered.
  - Restore asks for confirmation and reports the result.
  - A settings section for P05 and P06, registered for Settings → Backup. It appears once T6.1 exists.
  - Every dialog and file picker goes through the prompts interface.
- Accept, using the prompts fake:
  - mismatched or too-short passphrases show a translated error and write no file;
  - a successful backup writes the `.cbrnbak` file at the chosen path and reports success;
  - restore asks for confirmation, and cancelling changes nothing;
  - read-only mode disables Restore but still allows Back up;
  - the pseudo-locale walk passes on the dialogs.
- Check: `uv run pytest tests/ui/test_backup_ui.py tests/ui/test_no_hardcoded_strings.py`

**T7.5 — Read-only mode, location warnings and the first-run data-protection notice** (S) · Depends on: T0.5, T1.5, T1.9
- Files: `ui/shell/first_run.py`, `ui/shell/banners.py`, `ui/shell/main_window.py`, `app.py`, `docs/data-protection.md`, `i18n/shell_pt_BR.ts`, `i18n/shell_en_US.ts`, `i18n/shell_es_ES.ts`, `tests/ui/test_first_run_and_location.py`.
- Work:
  - Apply D02 at start-up:
    - a non-writable location with an existing database opens in read-only mode;
    - a non-writable location with no database shows an explanation and offers a choice of folder through the prompts interface.
  - Warning banners for network and OneDrive locations.
  - The first-run notice is shown once (a flag in `prefs.json`). It says where the data lives, that full-disk encryption is required by documentation (D03), and how backups work.
  - `docs/data-protection.md` documents the threats, controls and LGPD note of §7.
- Accept:
  - read-only mode shows the banner and disables every edit action;
  - with no database, the choice is offered and no file is created outside the folder finally chosen;
  - network and OneDrive paths (from injected probes) show their warnings;
  - the first-run notice appears exactly once;
  - `docs/data-protection.md` exists and names the default data folder;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_first_run_and_location.py tests/ui/test_no_hardcoded_strings.py`

#### Phase 8 — Reports, import/export, snapshots and validation export (v1.0)
This phase covers R11–R13, R29, R31 and R35.

**T8.1 — Readiness snapshots (migration 0007)** (M) · Depends on: T6.1, T6.5
- Files: `storage/migrations/0007_snapshots.sql`, `services/snapshots.py`, `ui/dashboard/page.py` (a "Record snapshot" action), `tests/services/test_snapshots.py`.
- Work:
  - Create `readiness_snapshot` and `readiness_snapshot_value` as in §5.2.
  - Recording a snapshot for an as-of date stores, for every indicator and dimension, the value, the status and the targets in force, together with the app version and a configuration hash (a hash of the configuration and the targets).
  - Origins:
    - `manual`;
    - `monthly`, taken at the first start in a calendar month (P04);
    - `report`, used by T8.7;
    - `retroactive`, computed from current data for a past as-of date and labelled as such.
- Accept:
  - a snapshot stores one value row per indicator and dimension;
  - the configuration hash changes when a target changes and not otherwise;
  - several starts in one month produce exactly one monthly snapshot;
  - an `UPDATE` on either snapshot table raises (trigger);
  - deleting a snapshot writes a `change_log` row;
  - "Record snapshot" is disabled in read-only mode.
- Check: `uv run pytest tests/services/test_snapshots.py`

**T8.2 — Validation export for the predictive-validity comparison** (S) · Depends on: T8.1, T4.4
- Files: `services/validation_export.py`, `tests/services/test_validation_export.py`.
- Work:
  - For each exercise edition, find the latest snapshot whose `as_of` is before the edition's `start_on`.
  - If there is none, the operator may ask for a `retroactive` reading as of the day before `start_on`; otherwise the edition's rows carry the reason code `NO_PRIOR_SNAPSHOT`.
  - Write two CSV files in the D04 format:
    - readings: edition code, kind, `start_on`, snapshot id, snapshot `as_of`, origin, indicator code, dimension, value, status;
    - results: edition code, metric code, value, respondents, scale.

  The statistical analysis is outside the app (§2.2).
- Accept:
  - with snapshots both before and after an edition, the right one is chosen;
  - retroactive readings are labelled with origin `retroactive`;
  - the reason code appears when no reading exists;
  - the files contain aggregates only, with no staff identifiers;
  - row order is deterministic.
- Check: `uv run pytest tests/services/test_validation_export.py`

**T8.3 — CSV export per module** (S) · Depends on: T2.3, T3.3, T4.4, T5.3
- Files: `storage/csv_io.py` (export), `services/export.py`, `tests/storage/test_csv_export.py`.
- Work:
  - One file per entity, with stable English column codes, in the D04 format: UTF-8 with BOM, `;` separator, ISO dates, `.` as decimal point.
  - Money is written in major units with a currency column, and converted exactly from minor units.
- Accept:
  - reading the exported files back gives the same rows as the database;
  - a field containing `;`, quotes and line breaks survives the round trip;
  - amounts survive exactly;
  - column codes match `docs/import-templates.md` (shared with T8.4).
- Check: `uv run pytest tests/storage/test_csv_export.py`

**T8.4 — CSV templates and import** (M) · Depends on: T8.3
- Files: `storage/csv_io.py` (import), `services/importer.py`, `docs/import-templates.md`, `tests/fixtures/csv/` (fictitious files), `tests/services/test_importer.py`.
- Work:
  - Header-only templates for each entity.
  - Import in a single transaction, with a dry run that changes nothing.
  - Errors are reported per row, column and code.
  - Natural keys:
    - staff: identifier;
    - certificate: identifier, level, `issued_on`;
    - asset: tag;
    - status event: tag, `effective_on`;
    - maintenance: tag, `performed_on`, kind;
    - edition: code;
    - country: edition code, country code;
    - result: edition code, metric code;
    - budget entry: `fiscal_year`, source code, currency, description.
  - Duplicates by natural key are rejected.
  - Every imported row writes a `change_log` row with action `import`.
- Accept:
  - a valid fixture imports with the expected counts;
  - a file with any invalid row writes nothing and lists every error with row, column and code;
  - both `;` and `,` separators are accepted, with or without a BOM;
  - duplicates are rejected with their code;
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
  - The anonymised variant keeps counts only. It drops identifiers, labels, notes, descriptions, references and the operator label. Personnel-derived counts from 1 to threshold − 1 are shown as "< threshold" (A11); zero is shown as 0.
- Accept:
  - on a fixture, the internal variant contains the expected sections and figures;
  - a scan of every string in the anonymised variant finds none of the fixture's identifiers, labels, notes or descriptions;
  - suppression applies to personnel counts only, not to infrastructure, exercise or budget figures;
  - the threshold comes from the configuration.
- Check: `uv run pytest tests/reports/test_report_model.py`

**T8.6 — PDF rendering** (M) · Depends on: T8.5, T6.4
- Files: `reports/pdf.py`, `i18n/reports_pt_BR.ts`, `i18n/reports_en_US.ts`, `i18n/reports_es_ES.ts`, `i18n/__init__.py` (one line), `selftest.py` (add the "pdf" check), `pyproject.toml` (pypdf in the `dev` group), `tests/reports/test_pdf.py`.
- Work:
  - Render the report document to an A4 PDF with Qt's text-document and PDF-writer classes (D09).
  - Include the title, page numbers, the preliminary notice in every page footer, and charts embedded through the T6.4 adapter.
  - The language is chosen per report.
- Accept:
  - the output parses with pypdf;
  - the pages are A4;
  - the extracted text contains the localized title in each of the three languages, and the preliminary notice on every page;
  - the anonymised PDF's text contains none of the fixture identifiers;
  - the self-test "pdf" check passes.
- Check: `uv run pytest tests/reports/test_pdf.py`

**T8.7 — Reports, snapshots and import/export user interface** (M) · Depends on: T8.2, T8.4, T8.6
- Files: `ui/reports/page.py`, `ui/reports/dialogs.py`, `ui/reports/labels.py`, `i18n/reports_pt_BR.ts`, `i18n/reports_en_US.ts`, `i18n/reports_es_ES.ts` (update), `ui/shell/registry.py` (one line), `tests/ui/test_reports_page.py`.
- Work:
  - A report dialog to choose the variant, language, as-of date and output path (through the prompts interface), with a "record snapshot" option that is ticked by default (P04, origin `report`).
  - A snapshot list where snapshots can be recorded and deleted.
  - The validation export.
  - CSV export, with a warning that the files contain internal data.
  - An import wizard: choose the entity and file, see the dry-run preview with its errors, confirm.
  - Settings sections for Reports (the A11 threshold) and Snapshots (P04), registered under Settings.
- Accept, using the prompts fake:
  - each action produces its file under `tmp_path`;
  - generating a report with the option ticked records a snapshot with origin `report`;
  - an import dry run shows the errors and writes nothing;
  - read-only mode disables import and snapshot recording, while reports and exports stay available;
  - the pseudo-locale walk passes.
- Check: `uv run pytest tests/ui/test_reports_page.py tests/ui/test_no_hardcoded_strings.py`

#### Phase 9 — Packaging, release and distribution
T9.2 and T9.3 can start any time after T0.9 and belong to the MVP. T9.5 can start any time after T0.8. T9.1 and T9.4 follow Phase 8.

**T9.1 — Final build script and bundle-content checks** (M) · Depends on: T0.9, T9.2, T8.6
- Files: `scripts/build_exe.py` (update), `tests/packaging/test_build.py` (extend).
- Work:
  - A Windows version resource is generated at build time from `__version__` into PyInstaller's work folder. It is never committed.
  - The excludes of T0.9 are kept.
  - The bundle receives the package data — every compiled `.qm`, `countries.json`, `THIRD_PARTY_DATA.md` and the `help/` files — plus the `licenses\` folder produced by T9.2.
  - The script prints the bundle size by top-level folder.
- Accept (`packaging` marker):
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
    - the Unicode/CLDR notice.
  - Write them into `licenses\`, with an index listing component, version and licence expression.
  - The allow-list test enforces the §4.2 list: MIT, BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0, LGPL-3.0 and GPL-3.0.
- Accept:
  - every runtime distribution has an index entry and a licence text;
  - the allow-list test passes on the real environment;
  - a fake distribution with an unknown or disallowed licence makes it fail;
  - the T0.9 build contains `licenses\` with the index.
- Check: `uv run pytest tests/scripts/test_collect_licenses.py tests/meta/test_dependency_licences.py` and `uv run pytest -m packaging tests/packaging/test_build.py`

**T9.3 — Release workflow: zip, checksums, provenance attestation, draft release** (M) · Depends on: T0.8, T0.9
- Files: `.github/workflows/release.yml`, `scripts/make_release_zip.py`, `tests/scripts/test_make_release_zip.py`, `tests/meta/test_workflows.py` (extend).
- Work:
  - The workflow triggers on tags `v*.*.*`.
  - Elevated permissions — `contents: write`, `id-token: write`, `attestations: write` — are granted only to the release job.
  - Steps:
    1. Pinned checkout and setup-uv; `uv sync --locked`.
    2. A step that checks the tag equals `v` + `__version__`.
    3. The default suite, then the packaging suite.
    4. The build.
    5. `make_release_zip.py`, which writes `cbrn-readiness-dashboard-<version>-win-x64.zip` with the top folder `cbrn-readiness-dashboard\`, entries in a fixed order with fixed timestamps, and `SHA256SUMS.txt` in the `<sha256>  <file name>` format.
    6. GitHub's build-provenance attestation of the zip.
    7. `gh release create --draft` with the zip and the checksum file.
  - The release body states that the executable is unsigned (D10), that the tool is preliminary and not institutionally validated (I06), how to verify the checksum, and which placeholders are still unconfirmed.
- Accept:
  - on a fake folder, the zip script produces the expected top folder and file list;
  - two runs produce byte-identical zips;
  - the checksum line verifies with `hashlib`;
  - the workflow test confirms: the tag trigger; every `uses:` pinned to a full SHA; elevated permissions scoped to the release job only; the attestation step; the version-check step; and that the release is created as a draft.
- Check: `uv run pytest tests/scripts/test_make_release_zip.py tests/meta/test_workflows.py`

**T9.4 — Release zip contents: first-run notes and the portable-mode example** (S) · Depends on: T9.3, T9.1
- Files: `packaging/README-first-run.pt-BR.txt`, `packaging/README-first-run.en-US.txt`, `packaging/README-first-run.es-ES.txt`, `packaging/portable.ini.example`, `scripts/make_release_zip.py` (include them at the folder root), `tests/scripts/test_make_release_zip.py` (extend), `tests/packaging/test_portable_mode.py`.
- Work:
  - The first-run notes are written from scratch in three languages and cover the steps of §8:
    - extract the whole zip first;
    - verify the checksum with `Get-FileHash`;
    - unblock the zip if needed;
    - SmartScreen "More info → Run anyway";
    - where the data lives;
    - portable mode;
    - the full-disk-encryption requirement (D03);
    - the preliminary status;
    - the licence and the source URL.
  - `portable.ini.example` explains in comments what portable mode does and the risk that copying the folder copies the data (D02).
- Accept:
  - the zip contains the three notes and the example at the folder root;
  - the three notes have the same section structure;
  - each note mentions `Get-FileHash` and `%LOCALAPPDATA%\cbrn-readiness-dashboard`.
  - Packaging test:
    1. Copy the built folder to `tmp_path` and rename the example to `portable.ini`.
    2. Clear `CBRN_DASHBOARD_DATA_DIR` and point `LOCALAPPDATA` at a temporary folder.
    3. Run `--self-test` without `--data-dir`.

    Data must be written to `.\data\` beside the executable, and nothing to the temporary `LOCALAPPDATA`.
- Check: `uv run pytest tests/scripts/test_make_release_zip.py` and `uv run pytest -m packaging tests/packaging/test_portable_mode.py`

**T9.5 — Dependency updates with Dependabot** (S) · Depends on: T0.8
- Files: `.github/dependabot.yml`, `tests/meta/test_workflows.py` (extend).
- Work:
  - Weekly update pull requests for GitHub Actions (Dependabot keeps the SHA pins) and for the uv lockfile.
  - Minor and patch updates are grouped.
  - Every update pull request runs CI, including the packaging job, before it can be merged.
- Accept: the test confirms that both ecosystems are configured with a schedule. A human confirms that the first Dependabot pull requests appear and run CI.
- Check: `uv run pytest tests/meta/test_workflows.py`

#### Phase 10 — Documentation, demo, accessibility and v1.0 (v1.0)
This phase covers R28, R32 and I06, plus D23 with T6.5. It closes v1.0.

**T10.1 — Complete demo dataset and demo walkthrough** (S) · Depends on: T2.5, T3.5, T4.6, T5.5, T6.5, T8.1
- Files: `demo/__init__.py` (orchestration), `tests/demo/test_demo_complete.py`, `tests/ui/test_demo_walkthrough.py`.
- Work:
  - The demo database receives illustrative targets, labelled in their descriptions as fictitious demo targets. They are never written to a real database and are not placeholders for one (P03 still applies to real data).
  - It also receives retroactive snapshots dated before the demo editions, so the validation export (T8.2) has content.
- Accept:
  - every registered page shows at least one row;
  - the dashboard shows at least one alert of every kind in §5.5;
  - the demo banner is visible on every page;
  - the validation export of the demo database produces rows;
  - after a demo run, a real database created in another folder has no targets and no snapshots.
- Check: `uv run pytest tests/demo/test_demo_complete.py tests/ui/test_demo_walkthrough.py`

**T10.2 — In-app help in three languages and the About dialog** (M) · Depends on: T9.2, T1.9
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
    - allow-listing by file hash for IT teams using AppLocker or WDAC;
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
- Accept: a walk over every registered page and dialog shows that:
  - every interactive widget has an accessible name or a buddy label;
  - every status display contains text;
  - every menu action has a mnemonic or a shortcut;
  - every page opens with `QT_SCALE_FACTOR=2` without Qt warnings;
  - the pseudo-locale walk still passes.
- Check: `uv run pytest tests/ui/test_accessibility.py tests/ui/test_no_hardcoded_strings.py`

**T10.5 — Release candidate and final build for v1.0** (S) · Depends on: every non-deferred task
- Files: `CHANGELOG.md`, `src/cbrn_dashboard/__init__.py` (version `1.0.0`), `docs/manual-test-script.pt-BR.md`, `PLAN.md` (update §3.5 and §12 with the answers received), `tests/meta/test_release_readiness.py`.
- Work:
  - The changelog entry for 1.0.0 lists every placeholder that is still unconfirmed.
  - The version is bumped.
  - The manual test script, in pt-BR for the committee, gives steps and expected results with the demo data for each page, the alerts, language switching, backup to removable media and restore, report generation, CSV import and the read-only mode.
  - Run the full default and packaging suites, then tag `v1.0.0`; T9.3 creates the draft release.
  - A person starts the executable on a clean Windows profile without admin rights, runs the manual test script, and then publishes the draft.
- Accept:
  - `CHANGELOG.md` has an entry for `__version__`;
  - `__version__` equals the installed metadata version;
  - the 1.0.0 entry lists exactly the placeholders still flagged in `domain/config.py`;
  - the manual test script names every registered page.
- Check: `uv run pytest tests/meta/test_release_readiness.py`, then `uv run pytest` and `uv run pytest -m packaging`

### 10.4 MVP cut, deferred work and sizing

**MVP v0.1** consists of Phases 0–7 (T0.1–T7.5) plus T9.2 (licence bundle) and T9.3 (release pipeline). It contains:
- all five modules of L74–L82, with data entry, editing, deactivation and deletion, and the change log;
- every indicator of §5.4, evaluated for any as-of date, with configurable targets (none by default);
- the alerts of §5.5, the dashboard with tiles, charts and table views, and the start-up summary;
- the trilingual interface with live switching;
- placeholders flagged in Settings;
- local storage in the profile, read-only handling, location warnings and the first-run notice;
- automatic local backups, encrypted manual backups and restore;
- the demo mode;
- the one-folder executable with self-test, bundled licences, checksums and a provenance attestation, released as a draft pre-release.

That is enough for the committee to start entering real data on their own machine and to review the indicators and placeholders.

**v1.0** adds:
- Phase 8 (T8.1–T8.7): snapshots, the validation export, CSV export and import, and PDF reports, internal and anonymised;
- T9.1 (final build and bundle checks), T9.4 (first-run notes and the portable example) and T9.5 (Dependabot);
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
| X9 | Switch from Qt Charts to Qt Graphs | Qt Charts deprecation | D08 |
| X10 | Breakdowns of exercise participants (for example by role or origin), still as counts only | Q7 | D20 |
| X11 | Dark and high-contrast themes beyond the OS default | field use | D23 |
| X12 | macOS and Linux builds | demand | §2.2 |

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
| 7 Backup and data protection | 5 | 3 | 2 | MVP |
| 8 Reports, import/export, snapshots | 7 | 2 | 5 | v1.0 |
| 9 Packaging and release | 5 | 2 | 3 | T9.2, T9.3 MVP; T9.1, T9.4, T9.5 v1.0 |
| 10 Documentation and v1.0 | 5 | 2 | 3 | v1.0 |
| **Total** | **68** | **32** | **36** | MVP 53 tasks (26 S, 27 M); v1.0 adds 15 (6 S, 9 M) |

Honest remarks on size:
- The MVP is about three quarters of the task count.
- The longest chain of tasks that must run one after another is roughly 20 tasks: Phase 0 → Phase 1 → the slowest module → Phase 6 → Phase 8 → T9.1/T9.4 → T10.5. Running modules and Phase 7 in parallel shortens the elapsed time, but not this chain.
- The UI tasks carry most of the effort and most of the translation work. Each UI task also adds translations in three languages, which the committee still has to review (Q14).
- Answers to §12 may add work. Most answers are applied in Settings without code: P01–P07, targets, A02, A04, A05, A06 intervals, A07 metrics, A09 courses and the A11 threshold. Answers that contradict A01, A03, A08, A10, A12 or A13, or that request X1–X6, need new tasks.
- No calendar estimate is given. Agent throughput and review time are unknown, and the institutional steps (§10.5) dominate the elapsed time.

### 10.5 Relation to the appendix timeline
The appendix describes the process as requirements gathering with the committee, incremental prototyping, tests with retroactive 2022–2025 data, and institutional homologation (L87), with an estimate of twelve to eighteen months for the whole process (L91). This plan fits into that process as follows.

- **Requirements gathering (R28).** The open questions of §12 are the agenda. The MVP is designed so the committee can answer most of them by changing Settings and reviewing the placeholders, rather than by waiting for code.
- **Incremental prototyping (R28).** MVP v0.1, any point releases, then v1.0. Each release is a draft GitHub release with checksums. Feedback goes into §3.5, §12 and new tasks.
- **Retroactive tests, 2022–2025 (R29).** On the committee's own machine, records are entered by hand or imported from CSV (T8.4, with templates matched to the existing records' structure — Q16). The indicators are then read for past as-of dates (I03), and retroactive snapshots (T8.1) record those readings. The data never enters the repository (F05).
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
| K02 | The unsigned executable is blocked or warned against: SmartScreen, Smart App Control, AppLocker/WDAC, antivirus false positives. | H / M | One-folder build without UPX (D01). Published SHA-256 checksums and provenance attestation (T9.3). Install guides in three languages, including allow-listing by file hash for IT teams (T10.3). Code signing stays deferred (X6) until Q13 is answered. | D01, D10, Q13 |
| K03 | Sensitive data leaves the machine through the network, cloud sync, unencrypted copies or external reports. | M / H | No network code, enforced by test (T0.4), and no Qt network or web libraries in the bundle (T9.1). Data lives in the profile, with warnings for OneDrive and network paths (D02, T7.5). Manual backups are encrypted (T7.2). External reports are anonymised with small-count suppression (T8.5). | F02, F05, §7 |
| K04 | Real data enters the public repository through commits, test fixtures, issues or screenshots. | M / H | Ignore rules and a hygiene test over tracked files (T0.3). Contribution rules, a pull-request checklist and an issue-template warning. Demo data only, with `DEMO` identifiers and a separate file (D25). Data lives outside the working copy by default (D02). | F05, T0.3 |
| K05 | The only copy of the data is lost: disk failure, corruption, a failed migration or a bad restore. | M / H | Rollback journal with `synchronous=FULL` (D06). Automatic daily and pre-migration backups (T7.1). Restore validates before swapping, keeps a safety copy and leaves the current database untouched on failure (T7.3). The documentation tells users to keep encrypted backups on separate media. | I02, D04 |
| K06 | A backup passphrase is forgotten, so the encrypted backup cannot be read. | M / M | The passphrase is entered twice, with a minimum length (P05) and an explicit warning that it cannot be recovered (T7.4). The automatic local backups in the protected profile do not depend on a passphrase (T7.1). | D04, Q11 |
| K07 | The workstation has no full-disk encryption, so a lost device exposes the database. | M / H | A first-run notice and the data-protection guide state the requirement (T7.5). Data is minimised (D17). Database encryption (X1) is held ready behind `open_database()` in case Q11 requires it. | D03, Q11 |
| K08 | Translations are poor, or the terminology is inconsistent across pt-BR, en-US and es-ES. | M / M | Completeness, sync, placeholder and pseudo-locale tests (§6). Terms in English source strings are kept stable. The committee reviews the terminology before v1.0 (Q14), and the review status is recorded in the changelog (T10.5). | D07, Q14 |
| K09 | Qt Charts is deprecated in favour of Qt Graphs. | M / L | All charts go through one adapter (D08, T6.4). Every chart has a table view (T6.5). Migration is deferred item X9. | D08 |
| K10 | Dependencies drift: PySide6, PyInstaller or Python changes break the build, or a dependency's licence changes. | M / M | `uv.lock` with hashes, pinned runner image and actions (T0.8). Dependabot pull requests run the packaging suite (T9.5). Frozen self-test in CI (T0.9, T9.1). The licence allow-list test fails on any disallowed or unknown licence (T9.2). | §4.2 |
| K11 | Scope creeps towards clinical or procedural content, which might import non-GPL text such as the WHO guide or internal documents. | M / H | Non-goal (§2.2) and design decision D19. Contribution rules and the pull-request checklist forbid it (T0.3). The help is written from scratch (T10.2). Anything clinical belongs to PTT 1, which is out of scope. | F06, D19 |
| K12 | The tool is read as institutionally validated, or its readings as an official readiness standard. | M / H | A permanent preliminary notice in the UI banner, every PDF page, the About dialog, the first-run notes and the release body (I06, P07). "No target" is the default status (D14). Indicator definitions are documented (T10.3). Snapshots record the configuration hash and app version (T8.1). Homologation stays outside the software (R30). | I06, Q15 |
| K13 | Retroactive readings are mistaken for readings taken at the time. | M / M | Snapshots record their origin (`retroactive`) and the time they were taken (T8.1). The validation export carries the origin of every reading (T8.2). | R29, R31 |
| K14 | The database is used from a network share, or by several people at once, and gets corrupted. | L / H | Network-path warning (D02, T7.5). Single-operator design (D05, A12). Shared use is deferred item X2 (Q12). | D02, D05 |
| K15 | The change log keeps personal data after the record itself has been deleted. | L / M | Data minimisation (D17). Retention is Q12; a redaction tool is deferred item X8. The behaviour is documented in the data-protection guide (T7.5). | D05, Q12 |
| K16 | Parallel coding agents conflict over migrations, catalogues or registries. | M / L | Reserved migration numbers (T1.3). One catalogue per area (D07). One-line registrations. Rebase and run the full suite before merging (§10.2). | §10.1, §10.2 |

---

## 12. Open questions for the author
"Committee" means the hospital's CBRN defence committee. Every question has a working answer in the app (§3.5) until it is answered. None of them blocks the MVP.

**Q1 — Indicators and targets.** Is the proposed indicator list (§5.4) right, including the design proposal `EX_DAYS_SINCE_LAST`? Which indicators make up the "padrão esperado de prontidão" (L82), and what warning and critical values apply to each — for example, a minimum number of staff with a valid level-A certificate?
- Answered by: the committee.
- Confirms: P03 and the indicator list. Enables the `INDICATOR_WARNING` and `INDICATOR_CRITICAL` alerts (R27).
- Until answered: no targets are set. Every indicator shows "No target" and raises no indicator alert.

**Q2 — PPE certificates and retraining.** Does each level (A, B, C) have a fixed validity period, and how long is it? Does a certificate at one level also count for other levels, and if so for which? What exactly makes retraining ("reciclagem") necessary: expiry only, or also elapsed time or hours? How many days before expiry should alerts start?
- Answered by: the committee.
- Confirms: A02, A03, A04 and P01 (90 days).
- Until answered: levels are counted independently, valid-until dates are entered per certificate, retraining means expired or expiring, and the warning window is 90 days.

**Q3 — Training and degrees.** Which kinds of training ("capacitação") should be recorded — that is, what goes on the course list? Should degrees in progress be recorded alongside completed ones?
- Answered by: the committee.
- Confirms: A09 and A10.
- Until answered: the course list is empty and editable, and degrees carry a completed / in-progress status.

**Q4 — Staff data and categories.** Which personal data may the app hold under the institution's reading of the LGPD? The plan proposes an internal code per person plus an optional short label, and no national ID numbers, birth dates, contact or health data. Should a professional category be recorded, and with which categories?
- Answered by: the committee.
- Confirms: D17 and the category list.
- Until answered: only the internal code, an optional label and a free, empty category list are available.

**Q5 — Beds and bays.** Does "leitos e baias disponíveis" (L76) mean installed units in working order, or units free at a given moment? Which status categories are needed, and does "degraded" count as available?
- Answered by: the committee.
- Confirms: A01 and A05. Tracking occupancy would need new tasks.
- Until answered: available means in service and operational; degraded counts as unavailable.

**Q6 — Equipment and maintenance.** Should "equipamentos de pressão negativa e filtragem" be one category or several? What maintenance interval applies to each type, and how many days in advance should maintenance alerts start?
- Answered by: the committee.
- Confirms: A06 and P02 (30 days), and the built-in type list.
- Until answered: one built-in type mirrors the appendix wording, intervals are not set ("schedule unknown"), and the warning window is 30 days.

**Q7 — Exercises.** Which aggregated evaluation results ("resultados agregados de avaliação", L78) should be recorded: metric names, scales and units? Besides the CBRAMED and EXBRAMED editions, should other courses or exercises be recorded? Is a total participant count enough, or are breakdowns needed?
- Answered by: the committee.
- Confirms: A07 and A13. Breakdowns would be deferred item X10.
- Until answered: the metric list is empty and user-defined, the kinds are CBRAMED, EXBRAMED and other, and only a total count is recorded.

**Q8 — Budget.** Which execution stages should be tracked? In which currencies are the DIRSA and OPCW Trust Fund amounts recorded, and is conversion needed? Is the fiscal year the calendar year? Are there other funding sources?
- Answered by: the committee.
- Confirms: A08. More stages or currency conversion would need new tasks.
- Until answered: allocated and executed amounts are tracked, the default currency is BRL, currencies are never mixed or converted, and the fiscal year is the calendar year.

**Q9 — Readiness reading and predictive validity (L87).** Is a single composite readiness score wanted, and if so with which formula and weights? How will the performance actually observed in the next EXBRAMED be measured and recorded? How often should the app record snapshots?
- Answered by: the thesis author, with the committee.
- Confirms: P04. A composite score would be deferred item X4.
- Until answered: no composite score is computed. The "reading" is the full set of indicator values in a snapshot. Snapshots are taken monthly and with every report.

**Q10 — Reports.** What should the internal report (for the committee, DIRSA and the Air Force Command) contain, and the aggregated, anonymised report for the OPCW Technical Secretariat? In which languages? Below which count should personnel figures be suppressed in the anonymised report? Are PDF and CSV enough, or is XLSX needed?
- Answered by: the committee.
- Confirms: A11 (threshold 5) and the report sections. XLSX would be deferred item X3.
- Until answered: the two PDF variants of T8.5 and T8.6 are produced in the chosen UI language, and personnel counts below 5 are suppressed.

**Q11 — Information security (L91).** Which institutional rules apply to this data? In particular: is encryption of the database file itself required, in addition to full-disk encryption of the workstation? Where may backups be stored? Is there a passphrase policy?
- Answered by: the committee.
- Confirms: R33, D03 and P05 (12 characters). Database encryption would be deferred item X1.
- Until answered: OS-level protection, data minimisation, encrypted manual backups and a 12-character minimum passphrase.

**Q12 — Users and history.** Will one person per installation maintain the data, or must several people edit the same data? May the change history record an operator name, and how long should the history be kept?
- Answered by: the committee.
- Confirms: A12 and D05. Shared use would be deferred item X2; a retention or redaction tool would be X8.
- Until answered: a single local operator, an optional operator label, and change history kept indefinitely.

**Q13 — Deployment.** How will the app be deployed on the hospital's machines? Is an unsigned executable delivered as a zip folder acceptable? Is a single `.exe` file mandatory? Is code signing expected?
- Answered by: the committee, with whoever manages those machines.
- Confirms: D01 and D10. A single file would be deferred item X5; signing would be X6.
- Until answered: a one-folder zip, unsigned, with checksums and a provenance attestation.

**Q14 — Terminology.** Can the committee review the interface terms in pt-BR, en-US and es-ES — for example the PPE level names, "baia", "reciclagem", and the Spanish and English equivalents of "prontidão"?
- Answered by: the committee.
- Confirms: the translation catalogues (§6).
- Until answered: draft translations are used, and the review status is recorded as pending in the changelog.

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

---

## 13. Definition of done for version 1.0
Version 1.0 is done when every item below can be verified.

1. **Tasks:** every task from T0.1 to T10.5 is merged. Deferred items X1–X12 are excluded.
2. **Default suite:** `uv run pytest` passes in CI on the pinned Windows image. This covers lint, types, guards, hygiene, translation completeness and sync, and the pseudo-locale walk. The CI coverage gate (at least 90% for `domain`, `storage` and `services`) passes.
3. **Packaging suite:** `uv run pytest -m packaging` passes in CI. The frozen self-test passes every check; the bundle-content checks pass (no Qt network or web libraries, no data files); the portable-mode test passes.
4. **CI is green** on the commit tagged `v1.0.0`.
5. **Release artefacts:** the release workflow produced `cbrn-readiness-dashboard-1.0.0-win-x64.zip`, `SHA256SUMS.txt`, a build-provenance attestation and a draft GitHub release. A person has verified the checksum with `Get-FileHash` before publishing.
6. **Three languages:**
   - pt-BR, en-US and es-ES are complete according to the automated tests;
   - the terminology review (Q14) is recorded in `CHANGELOG.md`, either as done or explicitly as pending;
   - the in-app help exists in all three languages with the same structure.
7. **Placeholders:** every placeholder of §3.5 is either confirmed by the committee or still flagged in Settings and listed in the changelog entry for 1.0.0 (T10.5 test).
8. **Preliminary notice:** it is present in the UI banner, on every PDF page, in the About dialog, in the first-run notes and in the release body (tests in T1.9, T8.6, T10.2, T9.4 and T9.3).
9. **Documentation:** all of these exist and pass their tests where tests apply:
   - `README.md`; `PLAN.md` (updated §3.5 and §12); `CONTRIBUTING.md`; `CHANGELOG.md`;
   - `docs/install.{pt-BR,en-US,es-ES}.md`, `docs/indicators.md`, `docs/architecture.md`, `docs/data-protection.md`, `docs/import-templates.md`, `docs/manual-test-script.pt-BR.md`;
   - the in-app help;
   - the `licenses\` folder in the bundle.
10. **Manual test:** a person has run `docs/manual-test-script.pt-BR.md` on the built zip, on a clean Windows profile without admin rights, and recorded the result in the changelog. The run includes: entering data in every module; switching languages; read-only mode; an encrypted backup to removable media and its restore; both PDF reports; a CSV import with a deliberate error.
11. **Offline:** source contains no network-capable modules (T0.4), and the bundle contains no Qt network or web libraries (T9.1). No telemetry, no update check.
12. **Licences:** the allow-list test passes, and the `licenses\` folder and the About dialog list every bundled component (T9.2, T10.2).
13. **Repository content:** the hygiene test passes, and a person has reviewed the tagged tree. It contains no real data, no database or backup files, no text from the WHO guide or from internal hospital documents, and no clinical content. All demo data is fictitious and uses `DEMO` identifiers.
14. **Out of scope:** institutional homologation (R30) and the result of the predictive-validity comparison (R31) are not part of this definition. v1.0 is handed over for institutional evaluation as a preliminary tool.
