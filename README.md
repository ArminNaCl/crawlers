# Basalam → Sazito Product Exporter

Crawls seller profiles and category pages on Basalam and exports products to CSV files ready for bulk import into Sazito.

## Project structure

```
crawler/
├── main.py                     CLI entry point
├── requirements.txt            requests only
├── models.py                   Product / ProductVariant dataclasses
├── memory.py                   SQLite deduplication (cross-run memory)
├── crawlers/
│   ├── base.py                 Abstract BaseCrawler + exceptions
│   └── basalam.py              Basalam implementation
└── exporters/
    └── sazito_csv.py           Sazito 36-column CSV writer
```

## Setup

```bash
pip install requests
```

## Usage

```bash
# Crawl a vendor profile
python3 main.py --url https://basalam.com/valas_shop --output ./output

# Crawl a category page
python3 main.py --url "https://basalam.com/cat/appliances/%D9%BE%D9%86%DA%A9%D9%87-%D8%AF%D8%B3%D8%AA%DB%8C" --output ./output

# Second run on the same source — already-exported products are skipped automatically
python3 main.py --url https://basalam.com/valas_shop --output ./output2
# → Exported=0, Skipped=N

# Force full re-export ignoring memory
python3 main.py --url https://basalam.com/valas_shop --output ./output3 --no-skip
```

### All CLI options

| Flag | Default | Description |
|---|---|---|
| `--url` | required | Vendor profile or category URL |
| `--output` | `./output` | Directory to write CSV files into |
| `--db` | `~/.cache/product_exporter/memory.db` | SQLite memory database path |
| `--prefix` | `output` | Filename prefix for CSV files (`output_001.csv`, `output_002.csv`, …) |
| `--rate-limit` | `0.75` | Seconds to sleep between API calls |
| `--no-skip` | off | Re-export all products, ignoring memory |
| `--verbose` | off | Show DEBUG-level logs |

## Key behaviours

- **Inactive products** on Basalam are skipped at the listing level (no wasted detail-fetch calls)
- **Already-exported IDs** are stored in SQLite with `(source_site, source_id)` as the primary key — safe to add future sites without ID collisions
- **Variants** share the same `identifier` column value; all their rows are buffered and written atomically so they never straddle two files
- **CSV encoding** is `utf-8-sig` (BOM) so Excel opens Persian text correctly on Windows
- **File splitting** — new file is opened automatically when the current one approaches 5 MB (Sazito's import limit)
- **Images** — all full-resolution product images are included as comma-separated URLs in the `images` column
- **Products are imported as inactive** (`enabled=false`) with unlimited stock (`9999`)
- **SKUs** are auto-generated as `BS-{product_id}-{variant_index}`

## Adding a new site (Torob, Emalls, etc.)

1. Create `crawlers/torob.py` implementing `BaseCrawler` (see `crawlers/base.py` for the interface)
2. Add one line to `CRAWLER_REGISTRY` in `main.py`:
   ```python
   "torob.com": TorobCrawler,
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

- **Images in Sazito**: Sazito's bulk import does not process the `images` column to upload photos — their documentation states images cannot be bulk-imported. The URLs are included in the CSV for reference; images must be uploaded manually in the Sazito panel after import.
- **Memory database** is stored at `~/.cache/product_exporter/memory.db` by default and persists across runs and working directories.
- Videos from product listings are never included (filtered by file extension).
