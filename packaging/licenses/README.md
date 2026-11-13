# Licences of the bundled software

This folder is part of the CBRN Readiness Dashboard bundle. It holds the licence texts and
notices of the software the bundle contains, and the offer of the corresponding source.

## How the folder is organised

- `index.json` and `INDEX.md` list every component with its version, the licence expression
  it declares, the licence this bundle uses (`chosen`) and the files in this folder that
  belong to it. The two files hold the same data: `index.json` is for programs (the About
  dialog reads it), `INDEX.md` is for people. For a declaration with `OR` (for example
  `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`), `chosen` is the alternative that was picked.
- One folder per Python package (named after the package, lower case) holds the licence files
  that package ships. A package that ships no usable licence text of its own gets the standard
  text of its chosen licence. The PySide6 packages ship only a pointer to Qt's commercial
  licence; that file is not copied here.
- `GPL-3.0.txt` is the text of this project's own licence, GPL-3.0. It also serves as the
  GPL-3.0 text for Qt Charts. `LGPL-3.0.txt` is the LGPL-3.0 text for Qt and the Qt for Python
  bindings. `Apache-2.0.txt` and `Unicode-3.0.txt` are the texts of those licences.
- `python-build-standalone/` holds the notices of the CPython distribution used for the build:
  CPython's own licence (which includes the PSF-2.0 text) and the notices of the libraries
  built into it (OpenSSL, SQLite, bzip2, liblzma, libffi, expat, mpdecimal, zlib).
- `pyinstaller/COPYING.txt` is PyInstaller's licence notice, including its bootloader exception.
- `QT-THIRD-PARTY-NOTICES.txt` holds the notices and licence texts of the third-party code
  inside Qt, for the bundled Qt version. `QT-THIRD-PARTY.md` explains it and also points to Qt's
  own list of licences.
- `OPENSSL.md` describes where OpenSSL is included.
- `MSVC-RUNTIME.md` describes the Microsoft Visual C++ runtime files in the bundle.
- `SOURCE-OFFER.md` names the source release of the bundled Qt and PySide6 version and
  contains the written offer of source.

## The licence of the bundle as a whole

The source code of the application is GPL-3.0-or-later. The bundle includes the Qt Charts
library, which Qt makes available under GPL-3.0; the bundle as a whole is therefore distributed
under GPL-3.0 (project plan, section 4.2). The Qt libraries are separate files in
`_internal\PySide6\` next to the executable.

These notices are informational. The licence texts in this folder are the authoritative terms.
