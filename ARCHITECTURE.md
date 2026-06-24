# Architecture

## Overview

A command-line tool that crawls Iranian e-commerce sites (starting with Basalam) and exports product data to Sazito-compatible CSV files for bulk import. It maintains a SQLite memory database to skip already-exported products across runs.

## Project Structure

```
crawler/
├── main.py                     CLI entry point, crawler detection, main loop
├── requirements.txt            Python dependencies
├── models.py                   Product / ProductVariant dataclasses
├── memory.py                   SQLite deduplication memory (cross-run)
├── crawlers/
│   ├── base.py                 Abstract BaseCrawler + shared exceptions
│   └── basalam.py              Basalam implementation (vendor + category)
└── exporters/
    └── sazito_csv.py           Sazito 36-column CSV writer with file splitting
```

## Data Flow

```
CLI (--url, --output, ...)
  │
  ├── detect_crawler(url)           main.py        picks crawler by domain from CRAWLER_REGISTRY
  │
  ├── extract_vendor_id(url)        BaseCrawler    parses vendor slug or category path from URL
  │
  ├── iter_product_ids(source_id)   BaseCrawler    lazy generator — paginates listing API
  │     │
  │     └── memory.is_exported()   ExportMemory   skip IDs already in SQLite
  │
  ├── get_product_detail(id)        BaseCrawler    fetch detail API → Product dataclass
  │
  ├── exporter.write_product()      SazitoCsvExporter  map Product → 36-col CSV row(s)
  │                                                    auto-split at 5 MB
  │
  └── memory.mark_exported()        ExportMemory   record (source_site, source_id) in SQLite
```

## Module Responsibilities

| File | Owns |
|---|---|
| `main.py` | CLI parsing, `CRAWLER_REGISTRY`, orchestration loop, progress reporting |
| `models.py` | `Product` and `ProductVariant` dataclasses — the shared data contract |
| `memory.py` | `ExportMemory`: SQLite open/close, `is_exported()`, `mark_exported()` |
| `crawlers/base.py` | `BaseCrawler` ABC, `ProductUnavailableError`, `CrawlerError` |
| `crawlers/basalam.py` | All Basalam logic: API calls, pagination, price conversion, image/attribute extraction |
| `exporters/sazito_csv.py` | Column mapping, UTF-8-BOM encoding, file splitting, `Key=Value` attribute format |

## Basalam API Endpoints

**Search / listing:**
```
GET https://search.basalam.com/ai-engine/api/v2.0/product/search
```

Vendor mode params:
```
filters.vendorIdentifier=<slug>   from=<offset>   size=24
```

Category mode params (reverse-engineered from Next.js bundle, module 66135):
```
url=/cat/<parent>/<leaf>   slug=<leaf>   parentSlug=<parent>
q=   dynamicFacets=true   size=24   enableNavigations=true   adsImpressionDisable=false
```

**Product detail:**
```
GET https://core.basalam.com/v3/products/{product_id}
```

Response is wrapped: `{"data": { ...product fields... }}`.
Images are in `data.photos[]` (dicts with `original`, `lg`, `md` keys) and `data.photo`.
Variant attributes are in `variant.properties[].{property.title, value.title}`.
Prices are in Rial — divided by 10 to get Toman before writing to CSV.

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
| category | Empty (must be mapped manually in Sazito panel) |
| sku | `{SITE_PREFIX}-{source_id}-{variant_index}` |
| weight | Grams (from `net_weight`), or empty |
| price | Toman integer |
| discount price | Toman integer, or empty |
| stock quantity | Crawler-specific (Basalam: `-1` for unlimited) |
| type | `physical` |
| min purchase | `1` |
| variant sort index | 0-based variant index |
| variant 1–10 attributes | `Key=Value` strings, one per column |
| all other columns | Empty |

## SQLite Memory Schema

Default path: `~/.cache/product_exporter/memory.db`

```sql
CREATE TABLE IF NOT EXISTS exported_products (
    source_site TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    vendor_id   TEXT,
    exported_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source_site, source_id)
);
```

The composite primary key ensures that IDs from different sites never collide (e.g. Basalam product `12345` and a future Torob product `12345` are separate rows).

## Adding a New Site

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full step-by-step guide.

Short version:
1. Create `crawlers/<site>.py`, implement `BaseCrawler`
2. Add one entry to `CRAWLER_REGISTRY` in `main.py`
3. The crawler handles its own currency/stock/attribute rules
