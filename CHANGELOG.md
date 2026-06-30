# Changelog

## [0.7.0] — 2026-06-30

### Fixed

- Basalam: support both `?cat=N` and `?cat_bar=N` query params for vendor category filtering (both map to `new_categoryId` in the search API); removed leftover debug print statements that caused a crash
- Basalam + SnappShop: reverse extracted image list so the primary product image becomes the last entry in the CSV `images` column, which Sazito uses as the default display image

## [0.6.0] — 2026-06-29

### Added

- SnappShop category page crawling (`snappshop.ir/category/{slug}`)
  - Uses `category_slug` field in POST body to `apix.snappshop.ir/search/v1`
  - Same pagination and detail-fetch pipeline as seller mode
  - `min_price_vendor` selected when no specific seller is requested
  - API hard cap of ~264 products per category crawl (offset-based pagination fails past skip=252); crawler logs a warning and stops gracefully instead of crashing

### Fixed

- SnappShop: 422 responses now fail immediately without retrying (added to no-retry list)

## [0.5.0] — 2026-06-27

### Fixed

- Basalam vendor URLs with `?cat_bar=N` now correctly filter products by `categoryId` / `new_categoryId` from the search API response
- Replaced non-ASCII checkmark character in `create_icon.py` that caused Windows CI to fail

## [0.4.0] — 2026-06-26

### Changed

- GUI UI switched to a compact English layout
- Octopus app icon added
- Persistent log file written to `~/Downloads/EComCrawler/ecomcrawler.log` for every GUI session

## [0.3.0] — 2026-06-25

### Added

- Desktop GUI (`gui.py`) — Flask backend + PyWebView native window
  - Single URL input; job runs in a background thread
  - Live log stream visible in the browser/window UI
  - CSVs auto-saved to `~/Downloads/EComCrawler/<vendor_id>/` on completion
  - Falls back to system browser when PyWebView is not installed
- Windows EXE build pipeline via PyInstaller (`build.spec`) with GitHub Actions release workflow
- EComCrawler app branding and octopus logo

### Fixed

- SnappShop: OG image (`og:image` meta tag) is now always placed first in the images list

## [0.2.0] — 2026-06-24

### Added

- **EmallsCrawler** (`crawlers/emalls.py`)
  - Shop page crawling (`emalls.ir/Shop/{id}`)
  - Category page crawling with `~Category~{id}` URL format and optional `~tag~` filter
  - Product IDs extracted via `data-esrever` attribute decoding (reversed URL paths)
  - Product detail parsed from JSON-LD structured data on each product page
  - Auto-pagination via `~page~N` URL segments
  - Rial → Toman conversion (÷10)
  - SKU format: `EM-{product_id}-0`

- **SnappShopCrawler** (`crawlers/snappshop.py`)
  - Seller page crawling (`snappshop.ir/seller/{slug}`)
  - Optional `category_chips` query param for category filtering
  - Reverse-engineered POST-based search API (`apix.snappshop.ir/search/v1`)
  - Detail API requires Tehran lat/lng coordinates for location-aware pricing
  - Rial → Toman conversion (÷10)
  - SKU format: `SS-{product_id}-{variant_index}`

- **ShopinoCrawler** (`crawlers/shopino.py`)
  - Shop page crawling (`shopino.app/shops/{id}`)
  - Optional `category` query param for category filtering
  - Public REST API with cursor pagination via `next` URL field
  - Only `in_stock=true` products yielded from listing
  - Prices already in Toman — no conversion
  - SKU format: `SHO-{product_id}-{variant_index}`

- `CRAWLER_REGISTRY` in `main.py` updated with all three new sites

## [0.1.0] — 2026-06-22

### Added

- Basalam vendor profile crawling (`basalam.com/<shop>`)
- Basalam category page crawling (`basalam.com/cat/<parent>/<leaf>`)
- Sazito 36-column CSV export with automatic file splitting (≤5 MB per file)
- UTF-8-BOM encoding for correct Persian text rendering in Excel on Windows
- SQLite deduplication memory — skip already-exported products on re-runs
- Composite primary key `(source_site, source_id)` in memory DB to support multiple sites
- Pluggable `BaseCrawler` abstract base class with `CRAWLER_REGISTRY` pattern
- Price Rial → Toman conversion (÷10) in `BasalamCrawler`
- Full-resolution image URL collection from Basalam `photos[].original`
- Variant attributes extracted from `variant.properties` in `Key=Value` format
- Product-level attribute fallback when variant has no properties
- 3-retry with exponential backoff on network errors
- Configurable `--rate-limit` flag (default 0.75 s between API calls)
- `--no-skip` flag to force full re-export ignoring memory
- `--verbose` flag for DEBUG-level logging
- Products imported as inactive (`enabled=false`) with stock set to `-1` (unlimited)
- SKUs auto-generated as `BS-{product_id}-{variant_index}`
