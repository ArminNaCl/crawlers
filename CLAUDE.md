# Claude Instructions for This Repo

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
- Register every new crawler in `CRAWLER_REGISTRY` in `main.py`
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
