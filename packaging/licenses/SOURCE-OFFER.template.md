# Source code and written offer

This file is generated from `SOURCE-OFFER.template.md` when the bundle is built.

## Where to get the source

The bundle was built with Qt {{qt_version}} and PySide6 {{pyside_version}}. The exact
corresponding source of those versions can be downloaded here:

- Qt {{qt_version}}: {{qt_source_url}}
- PySide6 {{pyside_version}}: {{pyside_source_url}}
- This application (source tag of this release, with the build scripts): {{project_source_url}}

The two archives of Qt and PySide6 are also attached to the GitHub release of this bundle, next
to the zip and the installer, as unmodified copies of the files above. The release workflow
checks them against SHA-256 values pinned in the repository before it attaches them, and
`SHA256SUMS.txt` of the release lists them.

## Every other Python package in the bundle

The versions of the Python packages in the bundle are fixed by `uv.lock` in the source tag
above. For each one, this is the source archive that `uv.lock` records, or a statement that it
records none (it lists only the built wheels of such a package):

{{package_sources}}

## Written offer

The project provides the source code of the Qt and PySide6 versions named above, of every Python
package listed in the section above, and of this application, on request. Requests go through
the issue tracker of the repository linked above. The offer is valid for at least three years
from the release date of this bundle. The source is provided for no more than the cost of
physically performing the distribution (GPL-3.0 section 6; LGPL-3.0).

## Replacing the Qt libraries

The Qt libraries are separate DLL files in `_internal\PySide6\` next to the executable and can
be replaced by the user with another build of the same Qt version.

The bundle is a one-folder build, not a single linked file. To produce a bundle again with other
libraries, check out the source tag above, change the locked versions (`uv.lock`) and build it
with `scripts/build_exe.py` as described in the repository.
