# Iranian E-Commerce → Sazito Product Exporter

Crawls seller profiles and category pages from Iranian e-commerce sites and exports products to CSV files ready for bulk import into Sazito.

**Supported sites:** Basalam, Emalls, SnappShop, Shopino

## Project structure

```
crawler/
├── main.py                     CLI entry point
├── requirements.txt            dependencies
├── models.py                   Product / ProductVariant dataclasses
├── memory.py                   SQLite deduplication (cross-run memory)
├── crawlers/
│   ├── base.py                 Abstract BaseCrawler + exceptions
│   ├── basalam.py              Basalam implementation (API)
│   ├── emalls.py               Emalls implementation (HTML scraping)
│   ├── snappshop.py            SnappShop implementation (reverse-engineered API)
│   └── shopino.py              Shopino implementation (public REST API)
└── exporters/
    └── sazito_csv.py           Sazito 36-column CSV writer
```

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Basalam — vendor profile
python3 main.py --url https://basalam.com/valas_shop --output ./output

# Basalam — category page
python3 main.py --url "https://basalam.com/cat/appliances/%D9%BE%D9%86%DA%A9%D9%87-%D8%AF%D8%B3%D8%AA%DB%8C" --output ./output

# Emalls — shop page
python3 main.py --url https://emalls.ir/Shop/75118 --output ./output

# Emalls — category page (paginated automatically)
python3 main.py --url "https://emalls.ir/لیست-قیمت_پیراهن-دخترانه~Category~32333" --output ./output

# Emalls — category with tag filter
python3 main.py --url "https://emalls.ir/لیست-قیمت~Category~32333~tag~maserati-girls-shirt" --output ./output

# SnappShop — seller page with category filter
python3 main.py --url "https://snappshop.ir/seller/0W6W2g?category_chips=g3vvnD" --output ./output

# Shopino — shop page (all products)
python3 main.py --url "https://shopino.app/shops/1802" --output ./output

# Shopino — shop page with category filter
python3 main.py --url "https://shopino.app/shops/1802?category=173" --output ./output

# Second run on the same source — already-exported products are skipped automatically
python3 main.py --url https://basalam.com/valas_shop --output ./output2
# → Exported=0, Skipped=N

# Force full re-export ignoring memory
python3 main.py --url https://basalam.com/valas_shop --output ./output3 --no-skip

# Slower rate limit to be polite to the server
python3 main.py --url https://emalls.ir/Shop/75118 --output ./output --rate-limit 1.5 --verbose
```

### All CLI options

| Flag | Default | Description |
|---|---|---|
| `--url` | required | Vendor profile or category URL (any supported site) |
| `--output` | `./output` | Directory to write CSV files into |
| `--db` | `~/.cache/product_exporter/memory.db` | SQLite memory database path |
| `--prefix` | `output` | Filename prefix for CSV files (`output_001.csv`, `output_002.csv`, …) |
| `--rate-limit` | `0.75` | Seconds to sleep between requests |
| `--no-skip` | off | Re-export all products, ignoring memory |
| `--verbose` | off | Show DEBUG-level logs |

## Key behaviours

- **Multi-site** — one CLI, multiple sites. The correct crawler is selected automatically from the URL domain.
- **Pagination** — category pages with many products are fetched page by page (Emalls uses `~page~N` URL segments; Basalam uses offset-based API pagination).
- **Inactive products** are skipped (no wasted detail-fetch calls)
- **Already-exported IDs** are stored in SQLite with `(source_site, source_id)` as the primary key — safe across multiple sites without ID collisions
- **Variants** share the same `identifier` column value; all their rows are buffered and written atomically so they never straddle two files
- **CSV encoding** is `utf-8-sig` (BOM) so Excel opens Persian text correctly on Windows
- **File splitting** — new file is opened automatically when the current one approaches 5 MB (Sazito's import limit)
- **Images** — full-resolution product images are included as comma-separated URLs in the `images` column
- **Products are imported as inactive** (`enabled=false`) with unlimited stock
- **SKUs** are auto-generated: `BS-{id}-{variant}` for Basalam, `EM-{id}-0` for Emalls, `SS-{id}-{variant}` for SnappShop, `SHO-{id}-{variant}` for Shopino
- **Shopino prices** are already in Toman — no conversion needed

## Adding a new site

1. Create `crawlers/newsite.py` implementing `BaseCrawler` (see `crawlers/base.py` for the interface)
2. Add one line to `CRAWLER_REGISTRY` in `main.py`:
   ```python
   "newsite.com": NewSiteCrawler,
   ```

Everything else (memory, CSV export, CLI) works unchanged.

## CSV format (Sazito bulk import)

36 columns in exact order required by Sazito:

```
identifier, product id, variant id, title, description, url, enabled, images, category,
variant commercial asset link, variant image id, sku, weight, price, discount price,
stock quantity, type, min purchase, max purchase, variant sort index,
seo title, seo description, seo keywords, seo redirect, seo canonical, seo index,
variant 1 attributes … variant 10 attributes
```

## Notes

- **Images in Sazito**: Sazito's bulk import does not process the `images` column to upload photos. The URLs are included for reference; images must be uploaded manually in the Sazito panel after import.
- **Emalls prices** are stored in Rial (IRR) on the site and are automatically divided by 10 to convert to Toman before export.
- **Memory database** is stored at `~/.cache/product_exporter/memory.db` by default and persists across runs and working directories.
- Videos from product listings are never included (filtered by file extension).
