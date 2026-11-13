CBRN Readiness Dashboard - first-run notes (English)
=====================================================

Read these notes before you start the program for the first time.
Draft text. The committee still has to review the wording (Q14).

1. What this is

   The CBRN Readiness Dashboard is a desktop tool for Windows. It works offline.
   It has no network code.

   Preliminary version — indicators not institutionally validated.

   Do not use the indicators for decisions that need a validated tool.

2. Before entering real data

   "Sensitive" is a working label of this project. It is not a formal classification.
   Do not enter real data yet. Wait until the institution has answered these questions:
   - Q19: the formal classification of the data.
   - Q4: personal data.
   - Q11: information security.
   - Q13: deployment.
   Until then, use the demo mode. Its data is fictitious:

      cbrn-dashboard.exe --demo

3. Extract the whole zip first

   Extract the whole zip to a folder. Then start cbrn-dashboard.exe from that folder.
   Do not start it from inside the zip preview of Explorer.
   It fails there, because the folder _internal\ is missing.

4. Verify the download

   Open PowerShell. Go to the folder with the zip. Run:

      Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256

   Compare the result with the line for the zip in SHA256SUMS.txt.
   Take SHA256SUMS.txt from the same release page as the zip.
   Optional: verify the build attestation with the GitHub CLI.

      gh attestation verify cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard

   This step needs network access. You do it. The program does not.

5. What the checks prove

   SHA256SUMS.txt on the same release page proves transfer integrity, not authenticity.
   The attestation proves where and how the build ran, not that the program is safe.

6. Unblock if needed

   Windows marks files that come from the internet (Mark-of-the-Web).
   Open the Properties of the zip. Tick "Unblock". Click OK.
   Do this BEFORE you extract the zip with the extractor of Windows.
   Otherwise the extracted files inherit the mark.
   Other extractors behave differently.

7. SmartScreen

   The executable is unsigned. SmartScreen may show "Windows protected your PC".
   Click "More info", then "Run anyway".
   Your organisation may forbid this. Then ask your IT team.

8. Locked-down machines

   AppLocker, WDAC or Smart App Control may block the program.
   With AppLocker or WDAC, extract the zip to a folder that IT allows.
   The manifest SHA256-FILES.txt on the release page lists the SHA-256 of every file of the folder,
   the .pyd and DLL files included. IT can check each extracted file against it.
   IT then creates its allow-listing rules from the verified folder, with its own policy tooling.
   The rules are per file and per release.
   Smart App Control has no bypass for a single file.

9. Where the data lives

   By default, the data is in:

      %LOCALAPPDATA%\cbrn-readiness-dashboard

   It holds the database, the backups, the logs and the preferences.
   The data stays there when you extract a new version to a new folder.
   If the new version has a database change to apply, the program first backs up the database
   and then migrates it, on the first start. Otherwise it migrates nothing.
   A database written by a newer version is refused.

10. Portable mode

   Rename portable.ini.example to portable.ini. Keep it next to cbrn-dashboard.exe.
   The data then goes to .\data\ beside the program.
   WARNING: copying the folder copies the data.

11. Protect the workstation

   This project's documentation requires full-disk encryption, for example BitLocker.
   The program cannot verify it.
   It does not protect files that you export to removable media.
   Several people can take turns on one machine only in one of two ways:
   - One shared Windows account.
   - The option --data-dir with a local folder that only the committee can open.
   With separate Windows accounts, each person gets a separate database.
   Make encrypted backups. Store them on separate media.
   A lost passphrase cannot be recovered.

12. Licence and source

   Licence: the project source is GPL-3.0-or-later; the bundle as a whole is GPL-3.0
   (see licenses\README.md). There is no warranty.
   Source code: https://github.com/marco-jardim/cbrn-readiness-dashboard
   The licence texts of third-party components are in the licenses\ folder.
