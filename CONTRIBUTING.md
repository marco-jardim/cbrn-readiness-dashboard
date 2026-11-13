# Contributing

Thank you for helping. This project handles readiness information for a hospital setting, so a
few rules matter more than usual. Please read them before you open an issue or a pull request.

## Development commands

```text
uv sync --locked --all-groups      # install the locked environment
uv run pytest                      # the default suite (must pass before every commit)
uv run pytest -m packaging         # build-dependent checks; run when you add a self-test
                                   # check or a bundled resource
```

## Rules

### 1. No real data, anywhere

- Never put real data in code, tests, fixtures, issues, pull requests, logs or screenshots.
  That includes real names, identifiers, figures from records or from a thesis, and real
  database or backup files.
- Fixtures and demo data are fictitious. Demo identifiers start with `DEMO`.
- Never read or write a real data folder from code or tests.
- Database, journal, backup, log and compiled-catalogue files are ignored by `.gitignore`, and
  `tests/meta/test_repo_hygiene.py` fails if one is tracked, whatever its name.

### 2. Content and licensing

- No text from the WHO guide or from any internal document of any institution.
- No clinical content. The dashboard shows readiness status; it does not tell anyone how to
  treat or decontaminate a patient.
- Help texts and documentation are written from scratch.

### 3. Committee answers stay out of the repository

Questions put to the committee are tracked, but their answers are not.

- The repository, the changelog, issues and pull requests record **only the status** of a
  question: *open*, *answered and applied locally*, or *answered and implemented in task Tn*.
  They never record the content of an answer.
- Answers, thresholds, security rules, deployment constraints, retention rules and institution
  names live in a private document **outside** the repository.
- Real targets are entered in Settings at run time. They never become defaults in code.

### 4. Code conventions

- Every `.py` file starts with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Layering: `domain/` and `services/` stay free of Qt. The UI reaches data only through
  `services/`. Modal dialogs and file pickers go through the prompts interface, so tests can
  replace them.
- Time: use `Clock` / `FixedClock`. Never call the wall clock directly.
- Tests write files only under `tmp_path`.
- No source folder may have a name that an ignore rule matches (for example `build`, `dist`,
  `lib`, `var`, `data`, `logs`, `tmp`, `backups`). The hygiene test fails if any file under
  `src`, `tests`, `docs`, `packaging` or `scripts` is ignored.
- Do not add a file larger than 1 MB.

### 5. Translations travel with the code

Every new user-visible string is added to its area's three catalogues (pt-BR, es-ES, en-US) in
the same commit, using `uv run python scripts/i18n.py update`, and then translated. pt-BR and
es-ES messages stay marked unfinished until the committee reviews them. Messages must not be
empty and must keep all placeholders.

### 6. Commits and pull requests

- One task per commit or pull request.
- The commit message starts with the task id, for example `T2.3: add backup service`.
- Do not add AI co-author lines or "Generated with ..." lines.
- A task is done only when its own check and the whole default suite (`uv run pytest`) pass. A
  task that breaks another task's test is not done.
- A rule the plan does not state is declared in `domain/config.py` with a `placeholder` flag,
  and the same commit records it in `PLAN.md`.

## Dependency updates

Dependabot opens weekly pull requests for GitHub Actions and for the uv lockfile.

- Every such pull request runs CI, including the packaging job, and is merged only when green.
- For an actions update, the reviewer checks that the new commit SHA belongs to the tagged
  release named in the trailing `# vX.Y.Z` comment. Dependabot can leave that comment stale.
- The PySide6 upper bound (`<6.13`) is deliberate while Windows 10 is a target. It is revisited
  at the yearly stack review, and Dependabot is told not to go past it.
- A dependency whose licence changes is caught by the dependency-licence allow-list test.

## Reporting problems

Use the bug report template. **Do not paste real data, screenshots of real data, database files
or backups.** Describe the problem with fictitious values instead.
