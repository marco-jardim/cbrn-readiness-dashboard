# Microsoft Visual C++ runtime

The bundle contains Microsoft Visual C++ runtime files. They come with the CPython distribution
or with the Python packages used for the build, and are redistributed unmodified. The list below
is written when the bundle is built, from the files that are really in it (names starting with
`vcruntime`, `msvcp` or `concrt`):

{{msvc_files}}

Microsoft's terms for redistributing these files are published at:

- https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
- https://learn.microsoft.com/en-us/cpp/windows/determining-which-dlls-to-redistribute

In the licence index (`index.json`, `INDEX.md`) this component carries the identifier
`LicenseRef-Microsoft-VC-Redist`, which is a local reference and not an SPDX licence
identifier.
