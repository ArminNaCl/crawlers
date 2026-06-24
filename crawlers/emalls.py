import json
import re
import time
import logging
from typing import Iterator
from urllib.parse import urlparse, unquote

import requests

from crawlers.base import BaseCrawler, ProductUnavailableError, CrawlerError
from models import Product, ProductVariant

log = logging.getLogger(__name__)

SHOP_URL  = "https://emalls.ir/Shop/{shop_id}"
BASE_URL  = "https://emalls.ir"
UNLIMITED_STOCK = -1

# Reversed product path format: /slug~id~12345
_ESREVER_RE  = re.compile(r"^(/\S+~id~(\d+))")
_JSONLD_RE   = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.DOTALL | re.I)
_META_DESC_RE = re.compile(r'<meta[^>]*name=["\']description["\'][^>]*content="([^"]+)"', re.I)


class EmallsCrawler(BaseCrawler):

    site_name = "emalls"

    def __init__(self, rate_limit: float = 0.75):
        self.rate_limit = rate_limit
        self._product_urls: dict = {}   # product_id → URL path, populated by iter_product_ids
        self._listing_url: str = ""     # set by extract_vendor_id, used by iter_product_ids
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Referer": "https://emalls.ir/",
        })

    # ------------------------------------------------------------------ #
    # BaseCrawler interface                                                #
    # ------------------------------------------------------------------ #

    def extract_vendor_id(self, url: str) -> str:
        # Decode percent-encoding so we can parse Persian slugs cleanly
        path = unquote(urlparse(url).path).strip("/")

        # Shape 1: /Shop/{shop_id}
        if path.lower().startswith("shop/"):
            shop_id = path.split("/")[1]
            self._listing_url = SHOP_URL.format(shop_id=shop_id)
            return shop_id

        # Shape 2: /slug~shop~{shop_id}   or   /slug~Category~{category_id}
        m = re.search(r"~(shop|category)~(\d+)", path, re.I)
        if m:
            vendor_id = m.group(2)
            self._listing_url = url   # use the original URL as-is
            return vendor_id

        raise ValueError(
            f"Cannot extract vendor ID from: {url}\n"
            "Expected formats:\n"
            "  https://emalls.ir/Shop/75118\n"
            "  https://emalls.ir/لیست-قیمت~shop~75118\n"
            "  https://emalls.ir/لیست-قیمت_کالا~Category~32333"
        )

    def iter_product_ids(self, vendor_id: str) -> Iterator[str]:
        html = self._get_html(self._listing_url)
        log.info("Shop page fetched — parsing product IDs")

        # data-esrever contains reversed product paths, e.g.:
        #   raw:      "03419762~di~هار-هار-حرط-تاملپید..."
        #   reversed: "/مشخصات_مانتو-...~id~26791430"
        esrevers = re.findall(r'data-esrever="([^"]+)"', html)
        seen: set = set()
        for raw in esrevers:
            reversed_val = raw[::-1]
            m = _ESREVER_RE.search(reversed_val)
            if not m:
                continue
            url_path, product_id = m.group(1), m.group(2)
            if product_id in seen:
                continue
            seen.add(product_id)
            self._product_urls[product_id] = url_path
            yield product_id
        # All products come from one page — no pagination sleep needed

        log.info("Found %d unique products", len(seen))

    def get_product_detail(self, product_id: str) -> Product:
        path = self._product_urls.get(product_id)
        if not path:
            raise CrawlerError(f"No URL cached for product {product_id} — call iter_product_ids first")

        html = self._get_html(BASE_URL + path)

        # Parse JSON-LD structured data
        m = _JSONLD_RE.search(html)
        if not m:
            raise ProductUnavailableError(f"No JSON-LD found for product {product_id}")

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise CrawlerError(f"Malformed JSON-LD for {product_id}: {e}") from e

        if data.get("@type") != "Product":
            raise ProductUnavailableError(f"JSON-LD is not a Product for {product_id}")

        offers = data.get("offers") or {}
        offer_count = self._to_int(offers.get("offerCount") or 0)
        if offer_count == 0:
            raise ProductUnavailableError(f"Product {product_id} has no active sellers")

        # Price: Emalls uses Rial (IRR) → divide by 10 for Toman
        price = self._to_int(offers.get("lowPrice") or 0) // 10

        # Description from meta tag (JSON-LD doesn't include it)
        desc_m = _META_DESC_RE.search(html)
        description = desc_m.group(1) if desc_m else ""

        images = []
        img = data.get("image")
        if img:
            images.append(img)

        title = data.get("name") or ""

        return Product(
            source_id=product_id,
            title=title,
            description=description,
            url=BASE_URL + path,
            images=images,
            category="",
            variants=[ProductVariant(
                variant_index=0,
                sku=f"EM-{product_id}-0",
                price=price,
                discount_price=None,
                stock=UNLIMITED_STOCK,
                weight=None,
                attributes={},
            )],
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_html(self, url: str, retries: int = 3) -> str:
        for attempt in range(retries):
            try:
                resp = self._session.get(url, timeout=20)
                resp.raise_for_status()
                return resp.text
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (404, 410) or attempt == retries - 1:
                    raise CrawlerError(f"HTTP {status} for {url}") from e
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise CrawlerError(f"Network error for {url}: {e}") from e
            backoff = 5 * (attempt + 1)
            log.warning("Retry %d/%d in %ds for %s", attempt + 1, retries, backoff, url)
            time.sleep(backoff)

    @staticmethod
    def _to_int(val) -> int:
        try:
            return int(float(str(val).replace(",", "").strip()))
        except (ValueError, TypeError):
            return 0
