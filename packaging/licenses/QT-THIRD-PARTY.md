# Third-party code inside Qt

Qt itself contains code from other projects, each under its own licence. The authoritative
list of those components and licences, for each Qt module, is Qt's documentation page
"Licenses Used in Qt":

https://doc.qt.io/qt-6/licenses-used-in-qt.html

The per-component attribution data (`qt_attribution.json` files) is part of the Qt source
release for the bundled version. The link to that source release is in `SOURCE-OFFER.md`.

## Known limitation

The PySide6 wheels that this bundle was built from ship no SBOM and no attribution files.
This bundle therefore carries the pointer above and not the attribution texts themselves.
This is a known limitation, recorded for the project owner.
