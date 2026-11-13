# OpenSSL

OpenSSL is included in the bundle in these places:

- inside CPython, in the `_ssl` and `_hashlib` extension modules;
- inside the `cryptography` wheel, once the encrypted-backup feature is part of the bundle.

OpenSSL 3.0 and later are licensed under Apache-2.0. The text is in `Apache-2.0.txt`. CPython's
copy of the OpenSSL notice is `python-build-standalone/LICENSE.openssl-3.txt`.

The application itself makes no network connections.
