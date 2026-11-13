# CBRN Readiness Dashboard {{version}}

**Preliminary version — indicators not institutionally validated.**

This is a Windows desktop program that helps a hospital look at its own CBRN readiness. The
indicators it shows are not yet validated by any institution; do not use them for decisions that
need a validated tool.

## The program is unsigned

The executable (`cbrn-dashboard.exe`) and the files next to it are **unsigned**: they carry no
code-signing certificate. Depending on how a computer is set up, Windows may react to that:

- **Microsoft Defender SmartScreen** may show "Windows protected your PC" the first time the
  program is started. The user can choose "More info" and then "Run anyway", unless the
  organisation forbids it.
- **Smart App Control** may block the program outright, because it only allows signed or
  well-known software.
- **AppLocker** or **Windows Defender Application Control (WDAC)** policies may refuse to run
  it, or its DLL and `.pyd` files, until an administrator allows them.

IT teams that allow-list by file hash can use the per-file manifest `SHA256-FILES.txt` attached to
this release. It lists the SHA-256 of every file inside the `cbrn-readiness-dashboard` folder of
the zip, DLL and `.pyd` files included.

## Verify the download

1. Compute the hash of the zip in PowerShell:

   ```powershell
   Get-FileHash .\{{zip_name}} -Algorithm SHA256
   ```

2. Compare it with the line for the zip in `SHA256SUMS.txt`, attached to this release. The
   expected value is:

   ```text
   {{sha256}}
   ```

3. Optionally, if you have the GitHub CLI, verify the build attestation:

   ```powershell
   gh attestation verify {{zip_name}} --repo marco-jardim/cbrn-readiness-dashboard
   ```

What these checks prove, and what they do not:

- `SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity. Anyone
  who could change the zip on this page could change that file too.
- The attestation proves where and how the build ran, not that the program is safe.

## Placeholders still flagged

Some values in the program are placeholders that still have to be confirmed. The ones that are
still flagged in the code in this release:

{{flagged_placeholders}}

## Source code and licences

This project is licensed under GPL-3.0-or-later. The source code that matches this release is the
tag [`v{{version}}`]({{source_tag_url}}).

The zip bundles Qt {{qt_version}} and PySide6 {{pyside_version}}. Qt's core libraries and the
PySide6 bindings are licensed under LGPL-3.0-only; Qt Charts is licensed under GPL-3.0-only. The
exact matching source releases are here:

- Qt {{qt_version}}: {{qt_source_url}}
- PySide6 {{pyside_version}}: {{pyside_source_url}}

The texts of the third-party licences are in the `licenses\` folder of the zip.

**Written offer.** For at least three years from the date of this release, this project will
provide, to anyone who asks through the issue tracker of this repository, the complete
corresponding source code of the Qt and PySide6 versions bundled in this release, for no more than
the cost of physically performing the distribution (GPL-3.0 section 6, LGPL-3.0).
