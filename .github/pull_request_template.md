## Task

Task id (for example `T2.3`):

## Summary

<!-- What changed and why. Use fictitious values only. -->

## Checklist

- [ ] One task in this pull request; every commit message starts with the task id.
- [ ] No AI co-author lines and no "Generated with ..." lines in any commit.
- [ ] No real data in code, tests, fixtures, screenshots or this description (demo identifiers
      start with `DEMO`).
- [ ] No database, journal, backup (`.cbrnbak`) or compiled catalogue (`.qm`) file is added.
- [ ] No text from the WHO guide or from any internal document, and no clinical content.
- [ ] **Committee answers:** nothing in this pull request (code, `PLAN.md`, changelog, comments,
      description) records the content of a committee answer, a threshold, a security rule, a
      deployment constraint, a retention rule or an institution name. Only the status of a
      question appears (open / answered and applied locally / answered and implemented in
      task Tn). Real targets are entered in Settings and are not code defaults.
- [ ] Every new `.py` file starts with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- [ ] Every new user-visible string is in the three catalogues and translated.
- [ ] `domain/` and `services/` stay Qt-free; the UI reaches data only through `services/`.
- [ ] `Clock` is used instead of the wall clock; tests write only under `tmp_path`.
- [ ] No source folder has a name matched by an ignore rule.
- [ ] `uv run pytest` passes (and `uv run pytest -m packaging` if a self-test check or bundled
      resource was added).
