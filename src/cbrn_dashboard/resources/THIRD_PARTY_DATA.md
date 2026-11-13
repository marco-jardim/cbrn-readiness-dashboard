# Third-party data

## countries.json

`countries.json` holds country names in Brazilian Portuguese (`pt_BR`), US English (`en_US`) and
Spanish (Spain, `es_ES`). It is derived from the **Unicode Common Locale Data Repository
(CLDR)**, Copyright © Unicode, Inc., which is distributed under the **Unicode License v3**
(SPDX identifier `Unicode-3.0`). The licence is published at:

https://www.unicode.org/license.txt

The full licence text ships in the `licenses\` folder of the distributed bundle.

How the file was made:

- The names were extracted from CLDR with Babel at development time, by
  `scripts/gen_countries.py`. Babel is a development tool only; it is not shipped and is not a
  runtime dependency of the application.
- The CLDR version the names come from is recorded inside the JSON (field `cldr_version`), and
  the extraction tool and version in the field `source`.
- The list of codes is restricted to the officially assigned ISO 3166-1 alpha-2 codes. The ISO
  codes themselves are used only as plain identifiers; no ISO publication text is included.
  Region codes that CLDR has but that are not officially assigned countries (for example `XK`,
  `EU`, `UN`, `ZZ`) are left out.
