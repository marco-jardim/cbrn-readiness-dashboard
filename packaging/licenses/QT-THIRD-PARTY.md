# Third-party code inside Qt

Qt itself contains code from other projects, each under its own licence (BSD, MIT, zlib,
FreeType and others). Those licences require the notice and licence text to accompany the
binaries. They are in this folder, in full:

- `QT-THIRD-PARTY-NOTICES.txt` holds one section for every component that the Qt source
  release of the bundled version documents (name, version, Qt repository and path, licence,
  copyright lines, licence text). Its header states the Qt version and the source tag. The
  file was generated from the `qt_attribution.json` files of the Qt repositories `qtbase`,
  `qtsvg`, `qtcharts`, `qtimageformats` and `qtvirtualkeyboard` at that tag, by
  `scripts/fetch_qt_attributions.py`; the bundle build refuses a file for another Qt version.
  Qt documents some components for platforms or tools that are not part of this application;
  they are listed too, so that none is missing.

As additional information, Qt's documentation page "Licenses Used in Qt" lists the same
components and licences for each Qt module:

https://doc.qt.io/qt-6/licenses-used-in-qt.html

The link to the Qt source release is in `SOURCE-OFFER.md`.
