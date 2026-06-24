import argparse
import logging
import sys
import time
from urllib.parse import urlparse

from crawlers.base import ProductUnavailableError, CrawlerError
from crawlers.basalam import BasalamCrawler
from crawlers.emalls import EmallsCrawler
from crawlers.snappshop import SnappShopCrawler
from exporters.sazito_csv import SazitoCsvExporter
from memory import ExportMemory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Registry: map domain → crawler class.
# To add a new site, import its crawler and add one line here.
CRAWLER_REGISTRY = {
    "basalam.com":  BasalamCrawler,
    "emalls.ir":    EmallsCrawler,
    "snappshop.ir": SnappShopCrawler,
    # "torob.com": TorobCrawler,
    # "digikala.com": DigikalaCrawler,
    # "divar.ir": DivarCrawler,
}


def detect_crawler(url: str):
    host = urlparse(url).netloc.lower().lstrip("www.")
    for domain, cls in CRAWLER_REGISTRY.items():
        if host == domain or host.endswith("." + domain):
            return cls()
    supported = ", ".join(CRAWLER_REGISTRY)
    raise SystemExit(f"No crawler for '{host}'. Supported: {supported}")


def parse_args():
    p = argparse.ArgumentParser(
        prog="product-exporter",
        description="Export products from Iranian e-commerce sites to Sazito CSV format.",
    )
    p.add_argument("--url", required=True,
                   help="Vendor profile URL, e.g. https://basalam.com/valas_shop")
    p.add_argument("--output", default="./output",
                   help="Output directory for CSV files (default: ./output)")
    p.add_argument("--db", default=None,
                   help="SQLite memory DB path (default: ~/.cache/product_exporter/memory.db)")
    p.add_argument("--prefix", default="output",
                   help="CSV filename prefix (default: 'output')")
    p.add_argument("--rate-limit", type=float, default=0.75,
                   help="Seconds between API calls (default: 0.75)")
    p.add_argument("--no-skip", action="store_true",
                   help="Re-export all products, ignoring memory")
    p.add_argument("--verbose", action="store_true",
                   help="Show DEBUG-level logs")
    return p.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    crawler = detect_crawler(args.url)
    crawler.rate_limit = args.rate_limit
    source_site = crawler.site_name

    vendor_id = crawler.extract_vendor_id(args.url)
    log.info("Vendor: %s  |  Site: %s", vendor_id, source_site)

    db_kwargs = {"db_path": args.db} if args.db else {}
    stats = {"seen": 0, "skipped": 0, "exported": 0, "errors": 0}

    with ExportMemory(**db_kwargs) as memory, \
         SazitoCsvExporter(args.output, file_prefix=args.prefix) as exporter:

        for product_id in crawler.iter_product_ids(vendor_id):
            stats["seen"] += 1

            if not args.no_skip and memory.is_exported(source_site, product_id):
                log.debug("Skip (already exported): %s", product_id)
                stats["skipped"] += 1
                continue

            try:
                product = crawler.get_product_detail(product_id)
                time.sleep(args.rate_limit)
            except ProductUnavailableError as e:
                log.debug("Inactive/removed: %s — %s", product_id, e)
                stats["skipped"] += 1
                continue
            except CrawlerError as e:
                log.warning("Failed to fetch %s: %s", product_id, e)
                stats["errors"] += 1
                continue

            if not product.is_active:
                stats["skipped"] += 1
                continue

            exporter.write_product(product)
            memory.mark_exported(source_site, product_id, vendor_id)
            stats["exported"] += 1
            log.info("[%d] %s | %s", stats["exported"], product_id, product.title[:70])

    log.info(
        "Done — seen=%d  exported=%d  skipped=%d  errors=%d  files=%d",
        stats["seen"], stats["exported"], stats["skipped"],
        stats["errors"], exporter.files_written,
    )


if __name__ == "__main__":
    main()
