# Help

## Overview
<!-- topic: overview -->

This program records and evaluates the readiness data of a committee: personnel, infrastructure, exercises and budget. All data is kept in one database on this computer. The program has no network access.

The window has the list of pages on the left, a toolbar with the as-of date, banners at the top and a status bar at the bottom. The status bar shows the alert counts for the as-of date, when they can be read, and the data folder. The menus are File (back up, restore, open the data folder, quit), Language and Help.

In read-only mode a banner says so, and every action that changes data is switched off.

This guide only explains how the program works. It contains no clinical or procedural content.

## As-of date
<!-- topic: as_of -->

Every figure on the pages is calculated for the as-of date shown in the toolbar. At start-up it is today's date, and it stays fixed until you change it, even after midnight.

Choose another date in the date field (it has a calendar) to see the situation on that day, for example to look at the past. The Today button sets it back to the current date.

The indicators, the alerts, the status of PPE qualifications and assets and the budget execution all follow the as-of date. Changing the as-of date never changes stored data.

## Dashboard
<!-- topic: dashboard -->

The Dashboard shows one tile for each indicator, grouped by module: the value, its unit, the status and the thresholds in force. The status is always written as text, together with a shape and a colour, so that it can be read without relying on colour. "No target" means that no target is set for the indicator. "No data" means that there is nothing to calculate it from. The program does not combine the indicators into one overall score.

The page also shows the number of alerts by severity and some charts. Each chart has a "Show as table" switch that shows the same numbers as a table.

"Record snapshot" stores the readings of the as-of date (see Snapshots). It changes data, so it is switched off in read-only mode.

## Personnel
<!-- topic: personnel -->

The Personnel page lists the staff with filters, shows their status per PPE qualification level on the as-of date and counts the people per level. A PPE qualification is a practical qualification in donning and doffing the protective ensemble of a level, with a valid-until date. Select a person to see the PPE qualifications, the training records and the academic degrees.

People are identified by an internal code and an optional short label. Do not enter national ID numbers or other personal data: the program refuses an identifier that looks like a national ID number.

You can add, edit, deactivate and delete people, and add, edit and delete PPE qualifications, training records and degrees. "Set no renewal" marks that no renewal of a qualification is expected, and "Clear no renewal" undoes it. "Pseudonymise person" replaces the identifier and the free text with random codes and cannot be undone. Deleting a person also deletes their PPE qualifications, training records and degrees. Deleting and pseudonymising ask for confirmation first.

The list of training courses is kept in Settings.

## Infrastructure
<!-- topic: infrastructure -->

The Infrastructure page lists the assets by type and tag with their status on the as-of date, the last maintenance and the next due date. Flags, written as text, show maintenance that is overdue, maintenance that is due soon and assets whose maintenance schedule is unknown. The page also shows the availability per type and the history of the selected asset.

You can add, edit, retire and delete assets, change the status of an asset, record maintenance, and edit or delete entries of the history.

The asset types and the availability rule, which decides whether degraded units count as available, are kept in Settings.

### Stock (lots)
<!-- topic: infrastructure_stock -->

The page has two tabs. "Equipment and facilities (units)" holds the assets described above. "Stock (lots)" records what is kept in stock, by lot instead of unit by unit: antidotes, decontaminants, detectors, protective equipment and other items. A lot has no operational status and no maintenance. An item that needs both stock and unit-by-unit tracking is entered twice, once in each tab. The stock holds management data only: it has no fields for doses, indications or protocols, and the lot codes and notes must not contain clinical information.

Lots. A lot belongs to an item type (17 types come with the program, and you can add your own in Settings) and has a lot code that is unique within the type, an expiry date, a unit price with its currency, and notes. The expiry date, the price and the notes are optional, except that lots of antidotes and decontaminants need an expiry date. Quantities are whole units. A lot is created together with its first receipt: the date, the quantity (at least 1) and a reference. "Add lot", "Edit lot" and "Delete lot" work on the selected lot; deleting a lot also deletes its movements and asks for confirmation first.

Movements. Each movement has a date, a kind, a quantity above zero, a reference and a note. The kinds are Receipt, Issue (consumption), Disposal, Loss, Adjustment (increase) and Adjustment (decrease). A receipt and an increase add to the lot; the other kinds take away from it. An adjustment needs a note. "Record movement" adds a movement to the selected lot, and the movements of the selected lot are listed with the balance after each one. The last movement of a lot cannot be deleted: close a lot with a disposal or a loss.

Quantity on a date. The quantity of a lot is never stored. It is calculated as the sum of its movements dated on or before the as-of date, so changing the as-of date shows the stock of that day. The balance of a lot can never be negative on any date: the program refuses a new, edited or deleted movement, and an imported row, that would leave the lot below zero on some date, even a backdated one. A movement cannot be dated after today.

Status. Every lot shows one status, written as text with an icon and a colour:

- Not yet received: no movement is dated on or before the as-of date.
- Empty: nothing is on hand. Empty lots never raise an alert and are hidden unless you tick "Show empty lots".
- Expired: the expiry date is before the as-of date and the lot still has stock.
- Expiring soon: the lot expires within the warning period of the as-of date.
- Valid: the lot has no expiry date, or its expiry date has not passed. A lot is still valid on its expiry date.

The tab also shows a summary for each item type: the valid quantity, the quantity expired and still in stock, the quantity expiring soon, the minimum stock, whether the type is below it and the value of the valid stock. Values are shown per currency and are never added across currencies.

Type filter. The Type filter above the tabs lists "All types", the asset types and the stock item types. An asset type shows the first tab, and a stock item type shows this tab with only the lots of that type. "All types" filters nothing and keeps the tab you are on. Changing the tab by hand never changes the filter.

Settings. The minimum stock of each item type is set in the Settings section "Stock item types", and the warning period before an expiry is set in the Alerts settings. Both are placeholders until the committee confirms them.

Alerts. An expired lot that still has stock is critical, a lot expiring soon is a warning, and an item type whose valid quantity is below its minimum is critical. A type with no minimum is never below it. The Dashboard also shows tiles for the valid stock, the lots expiring soon, the expired lots still in stock and the item types below the minimum stock.

Adding, editing and deleting lots and movements change data, so they are switched off in read-only mode, while the tables stay readable.

## Antidotes and decontaminants
<!-- topic: antidotes -->

The Antidotes and decontaminants page shows the stock of the antidote and decontaminant item types, by lot, for the as-of date. It holds management data only: quantities, lots, expiry dates, prices and movements. It has no fields for doses, indications or protocols, and the lot codes and notes must not contain clinical information.

A type filter above the tabs limits the page to one item type. The page has three tabs:

- Lots and movements: a summary for each item type, the lots with their quantity, status and days to expiry, and the dated movements of the selected lot (receipts, issues, disposals, losses and adjustments). A lot is created with its first receipt, and the quantity on any date is the sum of the movements up to that date. The balance of a lot can never become negative.
- Expiry schedule: the lots that still have stock, grouped by period of expiry: expired, one period for each month of the horizon (6, 12 or 24 months), later, and without an expiry date.
- Alerts: the stock alerts of these item types for the as-of date. "Open record" selects the lot in the first tab, or sets the type filter for an alert about an item type.

Adding, editing and deleting lots and movements change data, so they are switched off in read-only mode. The expiry warning period and the minimum stock of each type are kept in Settings. The Dashboard has a shortcut to this page.

## Exercises
<!-- topic: exercises -->

The Exercises page lists the exercise editions, which can be filtered by kind, and below them the evaluation results of the selected edition.

An edition has a code, a kind, a start date and an end date, and it may have a number of participants. That number is only a count; never enter names.

A result is the value of one evaluation metric in one edition, and the value must lie inside the scale of the metric. You can add, edit and delete editions and results. The evaluation metrics are kept in Settings.

## Budget
<!-- topic: budget -->

The Budget page shows, for a fiscal year, a summary for each funding source and currency: the amount allocated, the amount executed up to the as-of date and the execution rate. Currencies are shown on separate rows and are never added together.

Below the summary are the entries of the year and, for the selected entry, its dated execution rows. You can add, edit and delete entries and executions.

The funding sources, the default currency and the pro-rating switch are kept in Settings.

## Alerts
<!-- topic: alerts -->

The Alerts page lists the alerts for the as-of date: the severity (critical, warning or information) as text and icon, the module, the subject, the due date and a message. You can filter the list by module and by severity.

Double-click an alert, press Enter on it or use "Open record" to go to the page of the record it refers to.

Alerts are never stored; they are calculated each time from the data and the as-of date. The page only reads data, so it also works in read-only mode.

The status bar shows the alert counts. At start-up a banner can summarise the warning and critical alerts, with a button that opens this page. The number of days before a PPE qualification expires or a maintenance is due that raises an alert is set in Settings.

Three kinds of alert come from the stock: a lot that has expired and still has stock (critical), a lot that expires within the warning period (warning) and an item type whose valid quantity is below its minimum stock (critical). "Open record" goes to the stock tab of Infrastructure, or to the Antidotes and decontaminants page for those item types. Empty lots never raise an alert.

## Reports
<!-- topic: reports -->

The Reports page offers:

- "Create report..." writes the PDF report of the as-of date, either internal or anonymised. The anonymised report contains counts only, and counts below a threshold are suppressed; the threshold is set in Settings. Every page of every report carries the preliminary notice, and a report made from the demo database is marked as fictitious.
- "Export CSV files..." writes the data of the modules as CSV files, one file per kind of data, into a folder that you choose.
- "Validation export..." writes the files for the validation of the indicators, built from the snapshots and the exercise editions. It can record retroactive snapshots for editions that have no earlier snapshot, and it tells you how many.
- "Import CSV file..." and "Write templates..." (see Import).
- The list of snapshots (see Snapshots).

The report, the CSV export and the validation export also work in read-only mode.

The files that you export are ordinary files. They contain internal data and are not protected by the program: keep them where only the intended people can read them.

## Import
<!-- topic: import -->

"Import CSV file..." on the Reports page reads a CSV file of one kind of data, for example to enter past records. "Write templates..." writes empty files, with the header row only, into a folder that you choose; fill them in or edit an export.

The file must be UTF-8, and the separator is a semicolon or a comma. Import one kind of data at a time, and import the lists that other records refer to first: the lists (courses, asset types, metrics, funding sources and stock item types), then the staff, the PPE qualifications, training records and degrees, the assets, their status and maintenance events, the exercise editions with their countries and results, the budget entries, the budget executions, then the stock lots and finally the stock movements. A stock lot file creates the lots without any quantity; the quantity comes from the movements, so import them next. Stock movements follow the same rules as on the screen: a row that would make the balance of a lot negative, or that is dated after today, is refused. Built-in stock item types are never imported.

A file is imported completely or not at all. If any row has a problem, nothing is written and the problems are reported. The import dialog lets you check a file first. Import only adds records: an existing record is never changed or merged. Importing is switched off in read-only mode.

## Snapshots
<!-- topic: snapshots -->

A snapshot stores the indicator readings and the configuration in force for one date, so that what was known then can be seen later. You can record one with "Record snapshot" on the Dashboard or on the Reports page. For a date in the past the program asks for confirmation first.

Snapshots are never changed or deleted. "Withdraw snapshot..." asks for a reason and marks the snapshot as withdrawn: it stays stored and is hidden unless you tick "Show withdrawn snapshots".

At start-up the program can record a snapshot once a month by itself. It does not do so in read-only mode, with demo data or when the computer clock looks wrong. The Snapshots section of Settings holds the switches.

Recording and withdrawing change data, so they are switched off in read-only mode.

## Backup and restore
<!-- topic: backup -->

The data is one SQLite file in the data folder, which the status bar shows. The program makes a plain copy of it once a day and a copy before each upgrade of the database, in the backups folder. These copies are as sensitive as the database, and they are on the same disk. Make encrypted backups by hand and keep them on separate media.

### Back up...
<!-- topic: backup_make -->

File, "Back up..." asks for the file to write and then for a passphrase twice. The passphrase needs at least 12 characters and must not be a common word. The program writes an encrypted backup file (.cbrnbak). The passphrase is never stored and cannot be recovered: without it the file cannot be opened.

Back up also works in read-only mode. A banner reminds you when the last encrypted backup is older than the configured number of days, or when none was ever made.

### Restore...
<!-- topic: backup_restore -->

File, "Restore..." replaces ALL current data with the content of a backup file. It asks you to confirm, and then for the passphrase. Before copying, the program makes a safety copy of the current data, and if the restore fails it puts the data back as it was. A backup of the demo database cannot be restored over a real database, and the other way round.

Restore is switched off in read-only mode. After a successful restore every page shows the restored data.

### Open data folder
<!-- topic: backup_folder -->

File, "Open data folder" shows the data folder in Windows Explorer. It only opens an existing local folder, never a network location.

## Settings
<!-- topic: settings -->

The Settings page has one tab for each group of settings and a box for each section:

- General: the language, an optional operator label that is recorded with each change, and the names of the institution and the unit.
- Alerts: the number of days before an expiry or a due date that raises an alert. This includes the field "Stock lots: warning before expiry (days)", the warning period before a stock lot expires (placeholder P11, 90 days until the committee confirms it).
- Targets: the indicator targets, which you can add, edit, enable or disable, and delete. Until a target is set, an indicator shows "No target".
- Personnel, Infrastructure, Exercises and Budget: the lists and rules of each module, as described on their pages.
- Infrastructure also holds the section "Stock item types": the 17 built-in item types and your own. For each type you can set the minimum stock, which is empty (no minimum) until you set it, and make the type active or inactive; a built-in type cannot be deleted, and the category of a type cannot change once it has lots. The minimum stock is placeholder P12: it carries the mark "Placeholder - to be confirmed" and a Confirm button, and it is kept only on this computer.
- Backup, Reports and Snapshots: the settings of backups, of reports and of snapshots.

Some values are placeholders that the committee still has to confirm. They carry the mark "Placeholder - to be confirmed" and a Confirm button.

## Privacy
<!-- topic: privacy -->

- The data stays on this computer, in the data folder. By default it is `%LOCALAPPDATA%\cbrn-readiness-dashboard`, and the status bar shows it. The program has no network code: no update check, no telemetry and no upload of any kind.
- Staff are identified by an internal code. The program holds no national ID numbers, birth dates, contact data or health data.
- The log holds event codes only, never the contents of records.
- The program cannot check whether the disk of this computer is encrypted. The documentation requires full-disk encryption, for example BitLocker. Files that you export or copy to removable media are not protected by the program.
- A banner warns when the data folder is on a network share or inside a folder synchronised by OneDrive.
- "Sensitive" is only a working label for data that stays on this computer; it is not a formal classification. Do not enter real data until the open questions Q19, Q4, Q11 and Q13 have been answered. Until then use only demo data, which carries a permanent DEMO banner.

## Preliminary status
<!-- topic: preliminary -->

The notice "Preliminary version — indicators not institutionally validated." is always shown at the top of the window. It is also on every page of every PDF report and in the About dialog.

It means that the indicators and their thresholds have not been validated by the institution. Values marked "Placeholder - to be confirmed" are provisional. Treat every figure as preliminary.
