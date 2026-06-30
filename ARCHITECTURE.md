# Architecture

## Overview

A tool for crawling Iranian e-commerce sites and exporting product data to Sazito-compatible CSV files for bulk import. It maintains a SQLite memory database to skip already-exported products across runs.

Two entry points are available:
- **CLI** (`main.py`) — for scripted or server-side use
- **Desktop GUI** (`gui.py`) — Flask + PyWebView app with a browser-based UI; auto-saves CSVs to `~/Downloads/EComCrawler/`

## Project Structure

```
crawler/
├── main.py                     CLI entry point, crawler detection, main loop
├── gui.py                      Desktop GUI entry point (Flask + PyWebView)
├── requirements.txt            Python dependencies
├── build.spec                  PyInstaller spec for Windows EXE
├── create_icon.py              Generates app icon assets
├── models.py                   Product / ProductVariant dataclasses
├── memory.py                   SQLite deduplication memory (cross-run)
├── crawlers/
│   ├── base.py                 Abstract BaseCrawler + shared exceptions
│   ├── basalam.py              Basalam (vendor + category, API-based)
│   ├── emalls.py               Emalls (shop + category, HTML scraping)
│   ├── snappshop.py            SnappShop (seller + category filter, reverse-engineered POST API)
│   └── shopino.py              Shopino (shop + category filter, public REST API)
├── exporters/
│   └── sazito_csv.py           Sazito 36-column CSV writer with file splitting
└── frontend/
    ├── index.html              GUI single-page app
    └── static/
        ├── script.js
        └── style.css
```

## Data Flow

### CLI (`main.py`)

```
CLI (--url, --output, ...)
  │
  ├── detect_crawler(url)           main.py        picks crawler by domain from CRAWLER_REGISTRY
  │
  ├── extract_vendor_id(url)        BaseCrawler    parses vendor slug or category path from URL
  │
  ├── iter_product_ids(source_id)   BaseCrawler    lazy generator — paginates listing API / HTML
  │     │
  │     └── memory.is_exported()   ExportMemory   skip IDs already in SQLite
  │
  ├── get_product_detail(id)        BaseCrawler    fetch detail → Product dataclass
  │
  ├── exporter.write_product()      SazitoCsvExporter  map Product → 36-col CSV row(s)
  │                                                    auto-split at 5 MB
  │
  └── memory.mark_exported()        ExportMemory   record (source_site, source_id) in SQLite
```

### Desktop GUI (`gui.py`)

```
Browser / PyWebView window
  │
  POST /api/extract  { link: "..." }
  │
  Flask (daemon thread, random localhost port)
  │
  _run_job(job_id, url)  ← one daemon thread per job, identified by UUID
  │
  [same crawler + exporter + memory pipeline as CLI]
  │
  CSVs copied to ~/Downloads/EComCrawler/<vendor_id>/
  Logs written to ~/Downloads/EComCrawler/ecomcrawler.log
  │
  GET /api/status/<job_id>  ← frontend polls every 2 s for progress
```

PyWebView wraps the Flask app in a native OS window (Edge/WebView2 on Windows, WebKit on macOS/Linux). Falls back to the system browser when PyWebView is not installed.

## Module Responsibilities

| File | Owns |
|---|---|
| `main.py` | CLI parsing, `CRAWLER_REGISTRY`, orchestration loop, progress reporting |
| `gui.py` | Flask API, PyWebView window, per-job daemon threads, file logging, auto-save to `~/Downloads/EComCrawler/` |
| `models.py` | `Product` and `ProductVariant` dataclasses — the shared data contract |
| `memory.py` | `ExportMemory`: SQLite open/close, `is_exported()`, `mark_exported()` |
| `crawlers/base.py` | `BaseCrawler` ABC, `ProductUnavailableError`, `CrawlerError` |
| `crawlers/basalam.py` | Basalam: search + detail API, vendor/category URL parsing, cat_bar filter, Rial→Toman |
| `crawlers/emalls.py` | Emalls: HTML scraping, `data-esrever` decoding, JSON-LD parsing, Rial→Toman |
| `crawlers/snappshop.py` | SnappShop: POST-based search API, seller + `category_chips` filter, Rial→Toman |
| `crawlers/shopino.py` | Shopino: public REST API, cursor pagination via `next` URL, prices already in Toman |
| `exporters/sazito_csv.py` | Column mapping, UTF-8-BOM encoding, file splitting at 5 MB, `Key=Value` attribute format |
| `frontend/` | Static SPA (HTML/JS/CSS) served by the GUI's Flask instance |

## API Endpoints

### Basalam

**Search / listing:**
```
GET https://search.basalam.com/ai-engine/api/v2.0/product/search
```

Vendor mode params:
```
filters.vendorIdentifier=<slug>   from=<offset>   size=24
```

Category mode params (reverse-engineered from Next.js bundle):
```
url=/cat/<parent>/<leaf>   slug=<leaf>   parentSlug=<parent>
q=   dynamicFacets=true   size=24   enableNavigations=true   adsImpressionDisable=false
```

**Product detail:**
```
GET https://core.basalam.com/v3/products/{product_id}
```

Response wrapped: `{"data": { ...product fields... }}`.
Images in `data.photos[]` (`original`, `lg`, `md` keys) and `data.photo`.
Variant attributes in `variant.properties[].{property.title, value.title}`.
Prices in Rial — divided by 10 to get Toman.
Optional `cat_bar` query param on vendor URLs filters by `categoryId` / `new_categoryId`.

### Emalls

HTML scraping — no public JSON API.

Product IDs are extracted from `data-esrever` attributes on listing pages (reversed URL paths):
```
raw (in HTML):  "03419762~di~هار-هار-حرط-تاملپید..."
reversed:       "/مشخصات_مانتو-...~id~26791430"
```
Product detail is parsed from JSON-LD (`<script type="application/ld+json">`) on each product page.
Pagination via `~page~N` URL segments (`~page~2`, `~page~3`, …).
Prices in Rial — divided by 10 to get Toman.

### SnappShop

**Search (POST):**
```
POST https://apix.snappshop.ir/search/v1
     ?lat=35.77331&lng=51.418591

Seller mode body:   { "vendor": "<slug>", "limit": 24, "skip": N, "category_chips": "<id>" }
Category mode body: { "category_slug": "<slug>", "limit": 24, "skip": N }
```

**Product detail:**
```
GET https://apix.snappshop.ir/products/v2/{product_id}
    ?lat=35.77331&lng=51.418591&seller_id=<vendor_slug>
```

Tehran coordinates are required in all requests (location-aware pricing API).
Product IDs parsed from `href` field in listing: `/product/snp-{id}?seller_id=...`.
Prices in Rial — divided by 10 to get Toman.

### Shopino

**Product listing (cursor pagination via `next` URL):**
```
GET https://api-go.shopino.app/api/v1/app/shops/{shop_id}/products/
    ?category=<id>
```

**Product detail:**
```
GET https://api-go.shopino.app/api/v1/app/products/{product_id}/
```

Only `in_stock=true` products are yielded from the listing endpoint.
Prices already in Toman — no conversion needed.

## Sazito CSV Format

36 columns, `utf-8-sig` encoding (BOM), `\r\n` line terminator.

| Column | Value |
|---|---|
| identifier | Auto-incrementing integer (groups all variant rows for one product) |
| product id | Empty (assigned by Sazito after import) |
| variant id | Empty |
| title | Product title |
| description | Plain text (HTML stripped) |
| url | Empty |
| enabled | `false` (products imported as inactive) |
| images | Comma-separated full-resolution image URLs |
| category | Populated by SnappShop; empty for others (map manually in Sazito panel) |
| sku | `BS-{id}-{n}` Basalam · `EM-{id}-0` Emalls · `SS-{id}-{n}` SnappShop · `SHO-{id}-{n}` Shopino |
| weight | Grams (Basalam only, from `net_weight`), or empty |
| price | Toman integer |
| discount price | Toman integer, or empty |
| stock quantity | `-1` (unlimited) for Basalam/Emalls/SnappShop; actual quantity for Shopino |
| type | `physical` |
| min purchase | `1` |
| variant sort index | 0-based variant index |
| variant 1–10 attributes | `Key=Value` strings, one per column |
| all other columns | Empty |

## SQLite Memory Schema

Default path: `~/.cache/product_exporter/memory.db`

```sql
CREATE TABLE IF NOT EXISTS exported_products (
    source_site  TEXT NOT NULL,
    vendor_id    TEXT NOT NULL DEFAULT '',
    source_id    TEXT NOT NULL,
    exported_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_site, vendor_id, source_id)
);
```

The three-part primary key means:
- Products from different sites never collide (e.g. Basalam `12345` vs Shopino `12345`)
- Products from different vendors/categories on the same site are tracked independently — re-running vendor B will not skip a product that was previously exported from vendor A
- Cancelling a job mid-run and re-running the same URL resumes from where it left off

Old DBs with the two-part key `(source_site, source_id)` are migrated automatically on first run.

## Adding a New Site

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full step-by-step guide.

Short version:
1. Create `crawlers/<site>.py`, implement `BaseCrawler`
2. Add one entry to `CRAWLER_REGISTRY` in `main.py` and one entry to `_REGISTRY` in `gui.py`
3. The crawler handles its own currency conversion, stock defaults, and attribute mapping
