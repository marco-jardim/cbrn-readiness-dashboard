# OpenSSL

OpenSSL is included in the bundle in these places:

- inside CPython, in the `_ssl` and `_hashlib` extension modules;
- inside the `cryptography` package, a runtime dependency of the application, which the
  encrypted backups use.

The two copies can have different versions. The licence index (`index.json`, `INDEX.md`) records
the version of the interpreter's OpenSSL and the version `cryptography` reports for its own
backend, when it reports one.

OpenSSL 3.0 and later are licensed under Apache-2.0. The text is in `Apache-2.0.txt`. CPython's
copy of the OpenSSL notice is `python-build-standalone/LICENSE.openssl-3.txt`.

The application itself makes no network connections.
