# Project Roadmap

## Phase 1 — Basalam ✅ Done

- Vendor profile crawling (`basalam.com/<shop>`)
- Category page crawling (`basalam.com/cat/<parent>/<leaf>`)
- Sazito 36-column CSV export with automatic file splitting (≤5 MB)
- SQLite deduplication memory (skip already-exported products on re-runs)
- Rate limiting + 3-retry with exponential backoff
- `--no-skip` flag to force full re-export
- UTF-8-BOM encoding for Excel compatibility

## Phase 2 — Additional Sources

Target sites (in rough priority order):

| Site | Domain | Notes |
|---|---|---|
| ترب | torob.com | Price comparison — crawl by seller or product category |
| ایمالز | emalls.ir | |
| دیجی‌کالا | digikala.com | Largest Iranian e-commerce platform |
| دیوار | divar.ir | Classifieds — product model differs from shop sites |

Each new source:
- Gets its own file in `crawlers/` implementing `BaseCrawler`
- Defines its own currency conversion, stock defaults, and attribute mapping
- Is registered with one line in `CRAWLER_REGISTRY` in `main.py`
- Nothing else in the codebase changes

## Phase 3 — Desktop GUI

Simple Windows desktop app (Tkinter or PyQt5):
- URL input field
- Output directory picker
- Progress bar with product count
- Start / Stop button

Not in current scope — CLI is sufficient for v1.

## Phase 4 — Performance (multithreading)

Currently: product detail fetches are sequential (one at a time).

Plan:
- Use `concurrent.futures.ThreadPoolExecutor` to fetch multiple products in parallel
- Add `--workers N` flag (default `1` for safe single-threaded mode; recommended `3–5`)
- Thread-safety requirements:
  - SQLite writes: use a `threading.Lock` around `mark_exported()` and `is_exported()`
  - CSV writes: buffer entire product rows, acquire a lock before writing to file
  - Rate limiting: per-thread sleep (not global) to avoid thread starvation
- Expected speedup: 3–5× for large catalogs

## Known Limitations

- **Images**: Sazito's bulk import does not upload images from the `images` CSV column. URLs are stored for reference; images must be uploaded manually in the Sazito panel after import.
- **Categories**: The `category` CSV column is left empty — it must be mapped in the Sazito panel after import.
