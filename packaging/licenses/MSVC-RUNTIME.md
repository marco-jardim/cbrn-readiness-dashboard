# Microsoft Visual C++ runtime

The bundle contains Microsoft Visual C++ runtime files. They come with the CPython distribution
or with the Python packages used for the build (PySide6 and shiboken6 each carry their own
copies). The list below is written when the bundle is built, from the files that are really in it
(names starting with `vcruntime`, `msvcp`, `concrt`, `ucrtbase` or `api-ms-win-`, in any letter
case):

{{msvc_files}}

## Licence

These files are Microsoft's, not this project's. Each one is a separate Microsoft component. It
is **not** covered by the GPL-3.0 that applies to this program. It is redistributed unmodified,
under Microsoft's redistribution terms for Visual Studio, as an unmodified copy of a file that
Microsoft permits to be copied and distributed with a program. Microsoft's terms say that you
may not modify these files, and the files in this bundle are not modified. The copyright and
other notices that are inside the files are kept. The people who receive this bundle receive
these files under Microsoft's terms and not under the GPL. Nothing in the GPL-3.0 gives rights
over them. No Microsoft trademark is used in the name of this program.

Microsoft's terms are published at:

- https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
- https://learn.microsoft.com/en-us/cpp/windows/determining-which-dlls-to-redistribute

## Universal CRT

The supported systems are Windows 10 (version 1809 or later) and Windows 11. The Universal C
Runtime (`ucrtbase.dll` and the `api-ms-win-*` files) is part of those systems, and Windows
always uses its own copy, even when an application ships one. For that reason the build removes
these files from the bundle, and this program redistributes no Windows SDK component. See
https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment

## Licence index

In the licence index (`index.json`, `INDEX.md`) this component carries the identifier
`LicenseRef-Microsoft-VC-Redist`, which is a local reference and not an SPDX licence
identifier.
