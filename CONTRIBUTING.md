# Adding a New Crawler

## 1. Create the crawler file

Create `crawlers/<sitename>.py`. The file must define a class that inherits from `BaseCrawler`:

```python
from crawlers.base import BaseCrawler, ProductUnavailableError, CrawlerError
from models import Product, ProductVariant

class ExampleCrawler(BaseCrawler):

    site_name = "example"   # used as source_site key in the memory DB

    def extract_vendor_id(self, url: str) -> str:
        # Parse the URL and return a stable identifier for this vendor/shop.
        # Store any extra state you need (e.g. category path) as instance variables.
        ...

    def iter_product_ids(self, source_id: str):
        # Lazy generator. Yield one product ID (str) at a time.
        # Handle pagination internally. Respect self.rate_limit between pages.
        ...

    def get_product_detail(self, product_id: str) -> Product:
        # Fetch the product and return a Product dataclass.
        # Raise ProductUnavailableError if the product is deleted/inactive.
        # Raise CrawlerError for network/API errors after retries.
        ...
```

## 2. BaseCrawler interface

Defined in `crawlers/base.py`:

```python
class BaseCrawler(ABC):
    site_name: str                          # required class attribute

    def extract_vendor_id(self, url) -> str: ...
    def iter_product_ids(self, source_id) -> Iterator[str]: ...
    def get_product_detail(self, product_id) -> Product: ...
```

Exceptions:
- `ProductUnavailableError` — product is inactive/deleted, skip it without logging an error
- `CrawlerError` — unrecoverable API/network error, logged and counted as a failure

## 3. Each crawler owns its own conventions

Do not copy Basalam rules to a new crawler unless they happen to apply. Each crawler decides:

| Concern | Example (Basalam) | Your crawler |
|---|---|---|
| Currency | Rial ÷ 10 → Toman | Whatever the site uses |
| Unlimited stock | `-1` | Could be `0`, `9999`, or `None` |
| Attribute format | `Key=Value` strings in `variant.attributes` dict | Same dict, same format |

The `SazitoCsvExporter` writes `Key=Value` for every attribute in the dict — that part is fixed. The dict keys and values are your crawler's responsibility.

## 4. Register the crawler

In `main.py`, add one line to `CRAWLER_REGISTRY`:

```python
CRAWLER_REGISTRY = {
    "basalam.com": BasalamCrawler,
    "example.com": ExampleCrawler,   # ← add this
}
```

Import the class at the top of `main.py`.

## 5. Test it

```bash
python3 main.py --url "https://example.com/some_shop" --output ./test_out --verbose
```

Check:
- Products are listed and fetched without errors
- CSV columns look correct (open in Excel or LibreOffice with UTF-8-BOM)
- Re-running the same command skips all products (deduplication working)
- `--no-skip` forces a full re-export

## 6. Commit and open a merge request

```bash
git checkout -b feature/add-example-crawler
git add crawlers/example.py main.py
git commit -m "Add ExampleCrawler for example.com"
git push -u origin feature/add-example-crawler
gh pr create --title "Add ExampleCrawler for example.com"
```

Never commit directly to `main`. See [CLAUDE.md](CLAUDE.md) for git rules.
