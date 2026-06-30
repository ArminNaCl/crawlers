# Project Roadmap

## Phase 1 — Basalam ✅ Done

- Vendor profile crawling (`basalam.com/<shop>`)
- Category page crawling (`basalam.com/cat/<parent>/<leaf>`)
- Sazito 36-column CSV export with automatic file splitting (≤5 MB)
- SQLite deduplication memory (skip already-exported products on re-runs)
- Rate limiting + 3-retry with exponential backoff
- `--no-skip` flag to force full re-export
- UTF-8-BOM encoding for Excel compatibility

## Phase 2 — Additional Sources ✅ Done

| Site | Domain | Status |
|---|---|---|
| ایمالز | emalls.ir | ✅ Done — HTML scraping, JSON-LD detail, shop + category pages |
| اسنپ‌شاپ | snappshop.ir | ✅ Done — reverse-engineered POST API, seller + category_chips filter, category pages |
| شاپینو | shopino.app | ✅ Done — public REST API, cursor pagination, shop + category filter |
| ترب | torob.com | Not started |
| دیجی‌کالا | digikala.com | Not started |
| دیوار | divar.ir | Not started |

Each new source:
- Gets its own file in `crawlers/` implementing `BaseCrawler`
- Defines its own currency conversion, stock defaults, and attribute mapping
- Is registered with one line in `CRAWLER_REGISTRY` in `main.py` and `_REGISTRY` in `gui.py`
- Nothing else in the codebase changes

## Phase 3 — Desktop GUI ✅ Done

Flask + PyWebView desktop app (EComCrawler):
- URL input field — paste any supported site URL
- Start button — job runs in a background thread; frontend polls for progress
- Live log stream visible in the UI
- CSVs auto-saved to `~/Downloads/EComCrawler/<vendor_id>/`
- Log file at `~/Downloads/EComCrawler/ecomcrawler.log`
- PyWebView native window (Edge/WebView2 on Windows, WebKit on macOS/Linux); falls back to system browser
- Windows EXE built via PyInstaller (`build.spec`)
- GitHub Actions release pipeline for automated EXE distribution

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
- **Categories**: The `category` CSV column is populated by SnappShop only. For all other sites it is left empty and must be mapped in the Sazito panel after import.
