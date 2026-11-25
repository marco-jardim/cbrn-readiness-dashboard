# CBRN Readiness Dashboard {{version}}

This is a Windows desktop program that helps a hospital look at its own CBRN readiness.

<!-- installer:start -->
## Installer (recommended)

Download **`{{installer_name}}`**, check it (below) and run it. It installs the program **for your
Windows user only**, so no administrator rights are needed: the program goes to
`%LOCALAPPDATA%\Programs\CBRN Readiness Dashboard`, and a Start-menu shortcut is created. The
setup can also ask for an all-users install (it then needs an administrator), for example for IT
teams. To upgrade, run the setup of the newer version. To remove the program, use Settings > Apps
> Installed apps: the uninstaller keeps your data in `%LOCALAPPDATA%\cbrn-readiness-dashboard`.
The setup is available in Brazilian Portuguese, English and Spanish.

The setup program is **not signed**, and neither is the installed program unless the notes below
say so: Microsoft Defender SmartScreen shows "Windows protected your PC" for it as well ("More
info", then "Run anyway", unless your organisation forbids it). The installer is built by the
release workflow with [Inno Setup](https://jrsoftware.org/isinfo.php) (Inno Setup licence:
permissive, see its `license.txt`); the program inside it is the same tested bundle as in the zip.

Prefer the zip if you need the portable mode or want to extract the program to a folder of your
own choice: see the install guides in `docs/`.

Hash of the setup (also in `SHA256SUMS.txt`):

```text
{{installer_sha256}}
```

```powershell
Get-FileHash .\{{installer_name}} -Algorithm SHA256
gh attestation verify {{installer_name}} --repo marco-jardim/cbrn-readiness-dashboard
```
<!-- installer:end -->

<!-- signing-notice:start -->
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
<!-- signing-notice:end -->

The per-file manifest `SHA256-FILES.txt` attached to this release lists the SHA-256 of every file
inside the `cbrn-readiness-dashboard` folder of the zip, DLL and `.pyd` files included. IT teams
can use it to verify each extracted file, and then create their allow-listing rules from the
verified folder with the policy tooling of their own organisation.

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

Placeholders still flagged in the code in this release: {{flagged_placeholders}}.

<!-- source-archives:start -->
## Source code of Qt and PySide6 (LGPL-3.0)

The program in this release bundles Qt {{qt_version}} and PySide6 {{pyside_version}}, which are
licensed under LGPL-3.0-only. The source archives of exactly these versions are attached to this
release, next to the binary:

{{source_archives}}

They are unmodified copies of the archives published at download.qt.io (the links are in the
next section). The release workflow downloads them on every release and checks them against the
size and the SHA-256 pinned in the repository (`packaging/source-archives.json`) before it
attaches them; the same hashes are in `SHA256SUMS.txt`. They are Qt's files, not build outputs of
this project, so they carry no build attestation. The written offer in `licenses\SOURCE-OFFER.md`
(in the zip and in the installed program) remains valid.
<!-- source-archives:end -->

## Source code and licences

This project is licensed under GPL-3.0-or-later. The source code that matches this release is the
tag [`v{{version}}`]({{source_tag_url}}).

The zip bundles Qt {{qt_version}} and PySide6 {{pyside_version}}. Qt's core libraries and the
PySide6 bindings are licensed under LGPL-3.0-only; Qt Charts is licensed under GPL-3.0-only. The
exact matching source releases are here:

- Qt {{qt_version}}: {{qt_source_url}}
- PySide6 {{pyside_version}}: {{pyside_source_url}}

The texts of the third-party licences are in the `licenses\` folder of the zip. Its
`SOURCE-OFFER.md` lists the source archive that `uv.lock` records for every other Python package
in the zip, and says so where `uv.lock` records none.

**Written offer.** For at least three years from the date of this release, this project will
provide, to anyone who asks through the issue tracker of this repository, the complete
corresponding source code of the Qt and PySide6 versions bundled in this release and of every
other Python package locked in `uv.lock` of the tag above, for no more than the cost of
physically performing the distribution (GPL-3.0 section 6, LGPL-3.0).

**Relinking.** The zip is a one-folder build. To produce it again with other libraries, check out
the tag above, change the locked versions in `uv.lock` and build with `scripts/build_exe.py`.
