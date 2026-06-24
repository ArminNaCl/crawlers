import re
import time
import logging
from typing import Iterator
from urllib.parse import urlparse, parse_qs

import requests

from crawlers.base import BaseCrawler, ProductUnavailableError, CrawlerError
from models import Product, ProductVariant

log = logging.getLogger(__name__)

API_BASE     = "https://api-go.shopino.app/api/v1/app"
PRODUCTS_URL = f"{API_BASE}/shops/{{shop_id}}/products/"
DETAIL_URL   = f"{API_BASE}/products/{{product_id}}/"
WEB_BASE     = "https://shopino.app"
UNLIMITED_STOCK = -1

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class ShopinoCrawler(BaseCrawler):

    site_name = "shopino"

    def __init__(self, rate_limit: float = 0.75):
        self.rate_limit = rate_limit
        self._category_id: str = ""
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Origin": "https://shopino.app",
            "Referer": "https://shopino.app/",
        })

    # ------------------------------------------------------------------ #
    # BaseCrawler interface                                                #
    # ------------------------------------------------------------------ #

    def extract_vendor_id(self, url: str) -> str:
        parsed = urlparse(url)
        m = re.search(r"/shops/(\d+)", parsed.path)
        if m:
            shop_id = m.group(1)
            qs = parse_qs(parsed.query)
            self._category_id = qs.get("category", [""])[0]
            return shop_id

        raise ValueError(
            f"Cannot extract shop ID from: {url}\n"
            "Expected format: https://shopino.app/shops/1802"
        )

    def iter_product_ids(self, vendor_id: str) -> Iterator[str]:
        url = PRODUCTS_URL.format(shop_id=vendor_id)
        params: dict = {}
        if self._category_id:
            params["category"] = self._category_id

        page = 1
        total = 0

        while url:
            data = self._get_json(url, params=params)
            params = {}  # Only for the first request — subsequent pages via `next` URL

            results = data.get("results") or []
            if not results:
                break

            for p in results:
                if p.get("in_stock"):
                    yield str(p["id"])
                    total += 1

            log.info("Page %d: %d items (running total: %d)", page, len(results), total)
            url = data.get("next")
            if url:
                page += 1
                time.sleep(self.rate_limit)

        log.info("Found %d in-stock products", total)

    def get_product_detail(self, product_id: str) -> Product:
        url = DETAIL_URL.format(product_id=product_id)
        data = self._get_json(url)

        if not data.get("in_stock"):
            raise ProductUnavailableError(f"Product {product_id} is out of stock")

        title = data.get("title") or ""
        caption = data.get("caption") or ""
        description = " ".join(_HTML_TAG_RE.sub(" ", caption).split())

        images = [
            m["url"]
            for m in (data.get("medias") or [])
            if m.get("url") and not m.get("is_video")
        ]

        variants = self._extract_variants(data, product_id)
        if not variants:
            raise ProductUnavailableError(f"Product {product_id} has no available variants")

        return Product(
            source_id=product_id,
            title=title,
            description=description,
            url=f"{WEB_BASE}/product/{product_id}",
            images=images,
            category="",
            variants=variants,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _extract_variants(self, data: dict, product_id: str) -> list:
        variations = data.get("variations") or []
        result = []

        for idx, v in enumerate(variations):
            stock = v.get("stock_quantity") or 0
            if stock == 0:
                continue

            price = v.get("price") or data.get("price") or 0
            disc = v.get("discounted_price") or data.get("discounted_price") or 0

            attrs = {}
            for attr in (v.get("attributes") or []):
                name = attr.get("name", "")
                option = attr.get("option", "")
                if name and option:
                    attrs[name] = option

            result.append(ProductVariant(
                variant_index=idx,
                sku=f"SHO-{product_id}-{idx}",
                price=price,
                discount_price=disc if disc and disc < price else None,
                stock=stock,
                weight=None,
                attributes=dict(list(attrs.items())[:10]),
            ))

        # Fallback: no variations list — create one variant from the product-level price
        if not result and data.get("price"):
            price = data["price"]
            disc = data.get("discounted_price") or 0
            result.append(ProductVariant(
                variant_index=0,
                sku=f"SHO-{product_id}-0",
                price=price,
                discount_price=disc if disc and disc < price else None,
                stock=UNLIMITED_STOCK,
                weight=None,
                attributes={},
            ))

        return result

    def _get_json(self, url: str, params: dict = None, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                resp = self._session.get(url, params=params, timeout=20)
                resp.raise_for_status()
                return resp.json()
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
