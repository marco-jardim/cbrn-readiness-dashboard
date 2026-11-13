# Code signing policy

**Current status: the executable is unsigned.** This project has applied to the SignPath
Foundation open-source programme, but has not been accepted yet, and the release workflow signs
nothing until it is. Every release published so far (none, at the time of writing) and every
release made before acceptance carries no code-signing certificate. See the install guides in
`docs/` for what that means on a hospital computer.

The text below is the policy that will apply to signed releases from the moment the project is
accepted and signing is switched on.

## Who provides the signature

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

Windows shows the publisher of a signed executable as "SignPath Foundation": the certificate
belongs to the foundation, not to the maintainer of this project.

## What is signed

- Only `cbrn-dashboard.exe`, the executable built from this repository, is signed.
- The other files in the zip are not signed by this project: Qt and PySide6 libraries, the Python
  runtime, the Microsoft Visual C++ runtime and every `.dll` and `.pyd` file. They belong to other
  publishers; this project does not sign upstream binaries and keeps them as their publishers
  shipped them.
- The per-user installer (`cbrn-readiness-dashboard-<version>-win-x64-setup.exe`, made with Inno
  Setup after the signing step) is **not signed** and is not part of the SignPath request: the
  signing step runs before the installer exists, and the artifact configuration signs one file
  only. Windows SmartScreen may warn for the setup file even in a release where
  `cbrn-dashboard.exe` carries a signature. Signing the installer would need a second signing
  request and is not planned.
- The signed executable carries the product name "CBRN Readiness Dashboard" and the package
  version in its version resource. The signing request of each release states the same version.

## How a release is built and signed

1. A version tag (`v*.*.*`) starts the release workflow on GitHub-hosted runners
   ([`.github/workflows/release.yml`](.github/workflows/release.yml)). It runs the tests and builds
   the one-folder bundle once.
2. The workflow uploads that folder and sends it to SignPath from the same run. The
   [artifact configuration](.signpath/artifact-configurations/release.xml) lets SignPath sign
   `cbrn-dashboard.exe` and nothing else.
3. Every signing request is approved by hand in SignPath by the approver below. Nothing is signed
   without that approval.
4. The workflow checks that the signature is valid, then makes the zip, the checksum files and the
   build provenance attestation from the signed files and creates a **draft** release. A person
   publishes the draft after a smoke test.

## Team roles

This is a single-maintainer project, so one person holds every role.

- **Committers and reviewers:** [marco-jardim](https://github.com/marco-jardim)
- **Approvers:** [marco-jardim](https://github.com/marco-jardim)

## How to check a signature

Extract the zip, then either open the Properties of `cbrn-dashboard.exe` and look at the
"Digital Signatures" tab, or run in PowerShell:

```powershell
Get-AuthenticodeSignature .\cbrn-readiness-dashboard\cbrn-dashboard.exe
```

The status must be `Valid` and the signer certificate must be issued to "SignPath Foundation". A
signature shows who built the executable and that it was not changed afterwards. It does not show
that the program is safe or that its indicators are validated. The checksum files and the
attestation on the release page remain the way to verify the zip itself.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

The program has no network code: it keeps its data in a local database and never sends anything
anywhere. Signing does not change that.
