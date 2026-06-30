# Claude Instructions for This Repo

## Documentation — Read First, Update Always

**Before starting any task**, read these files to understand current state:
- `ARCHITECTURE.md` — module map, API endpoints, data flow
- `PLAN.md` — what is done and what is pending
- `README.md` — user-facing behaviour, CLI flags, site-specific notes
- `CHANGELOG.md` — version history

**After every code change** (fix or feature), update the docs before committing:

| What changed | Files to update |
|---|---|
| New crawler or new site support | `ARCHITECTURE.md` (structure, module table, API section) · `PLAN.md` (mark phase done or add entry) · `README.md` (usage examples, key behaviours, notes) · `CHANGELOG.md` (new version entry) |
| New CLI flag or GUI behaviour | `README.md` (flag table or GUI section) · `CHANGELOG.md` |
| Bug fix | `CHANGELOG.md` (under the correct version) |
| Structural refactor | `ARCHITECTURE.md` · `CHANGELOG.md` |

**CHANGELOG rules:**
- Add a new version block at the top (above the previous version)
- Use `### Added`, `### Changed`, or `### Fixed` subsections
- Version format: `## [X.Y.Z] — YYYY-MM-DD`
- Increment patch for fixes, minor for new features

**ARCHITECTURE.md rules:**
- Only update if the module structure, data flow, or an API endpoint actually changed
- Do not update for logic-only changes inside an existing module

## Git Workflow (strict — no exceptions)

- **Never commit directly to `main` or `master`**
- Always create a branch first:
  ```bash
  git checkout -b feature/short-description
  git checkout -b fix/short-description
  ```
- After finishing work, push the branch and open a merge request:
  ```bash
  git push -u origin feature/short-description
  gh pr create --title "..."
  ```
- Never force-push to any branch
- Commit messages: concise, imperative, explain what changed and why
- Before committing: verify the change works against a real URL (e.g. `python3 main.py --url https://basalam.com/valas_shop --output ./test_out`)

## Project Structure Rules

- New crawlers go in `crawlers/` and must subclass `BaseCrawler` from `crawlers/base.py`
- Register every new crawler in `CRAWLER_REGISTRY` in `main.py` and `_REGISTRY` in `gui.py`
- `exporters/sazito_csv.py` is site-agnostic — do not add site-specific logic there
- Keep `requirements.txt` minimal (only add packages that are actually needed)
- Each crawler is fully responsible for its own:
  - Currency conversion
  - Stock value representation
  - Attribute key/value mapping
  Do not assume another crawler's conventions apply to a new site.

## What Not To Do

- Do not add Basalam-specific logic outside of `crawlers/basalam.py`
- Do not add unnecessary abstraction, helper classes, or config files for hypothetical future needs
- Do not commit output CSV files, `.db` files, or `.env` files (covered by `.gitignore`)
