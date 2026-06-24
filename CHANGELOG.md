# Changelog

## [0.1.0] — 2026-06-22

### Added

- Basalam vendor profile crawling (`basalam.com/<shop>`)
- Basalam category page crawling (`basalam.com/cat/<parent>/<leaf>`)
- Sazito 36-column CSV export with automatic file splitting (≤5 MB per file)
- UTF-8-BOM encoding for correct Persian text rendering in Excel on Windows
- SQLite deduplication memory — skip already-exported products on re-runs
- Composite primary key `(source_site, source_id)` in memory DB to support future sites
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
