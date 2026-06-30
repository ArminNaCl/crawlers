import re
import time
import logging
from typing import Iterator
from urllib.parse import urlparse, parse_qs

import requests

from crawlers.base import BaseCrawler, ProductUnavailableError, CrawlerError
from models import Product, ProductVariant

log = logging.getLogger(__name__)

BASE_URL       = "https://snappshop.ir"
API_BASE       = "https://apix.snappshop.ir"
SEARCH_URL     = f"{API_BASE}/search/v1"
DETAIL_URL     = f"{API_BASE}/products/v2/{{product_id}}"
# Default Tehran coordinates required by the location-aware API
DEFAULT_LAT    = 35.77331
DEFAULT_LNG    = 51.418591
PAGE_SIZE      = 24
UNLIMITED_STOCK = -1

_TITLE_PREFIX_RE = re.compile(r"^خرید\s+و\s+قیمت\s+", re.UNICODE)
_HTML_TAG_RE     = re.compile(r"<[^>]+>")


class SnappShopCrawler(BaseCrawler):

    site_name = "snappshop"

    def __init__(self, rate_limit: float = 0.75):
        self.rate_limit = rate_limit
        self._url_type: str = "vendor"   # "vendor" or "category"
        self._vendor_slug: str = ""
        self._category_chips: str = ""
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Origin": "https://snappshop.ir",
            "Referer": "https://snappshop.ir/",
            "s-device": "WEB",
        })

    # ------------------------------------------------------------------ #
    # BaseCrawler interface                                                #
    # ------------------------------------------------------------------ #

    def extract_vendor_id(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]

        # /seller/{slug}  or  /seller/{slug}?category_chips=...
        if len(parts) >= 2 and parts[0].lower() == "seller":
            self._url_type = "vendor"
            self._vendor_slug = parts[1]
            qs = parse_qs(parsed.query)
            self._category_chips = qs.get("category_chips", [""])[0]
            return self._vendor_slug

        # /category/{slug}
        if len(parts) >= 2 and parts[0].lower() == "category":
            self._url_type = "category"
            self._vendor_slug = ""
            self._category_chips = ""
            return parts[1]

        raise ValueError(
            f"Cannot extract vendor ID from: {url}\n"
            "Expected formats:\n"
            "  https://snappshop.ir/seller/SLUG\n"
            "  https://snappshop.ir/category/SLUG"
        )

    def iter_product_ids(self, vendor_id: str) -> Iterator[str]:
        skip = 0
        total_pages = None
        page = 1

        while True:
            if self._url_type == "category":
                body: dict = {"category_slug": vendor_id, "limit": PAGE_SIZE}
            else:
                body = {"vendor": vendor_id, "limit": PAGE_SIZE}
                if self._category_chips:
                    body["category_chips"] = self._category_chips
            if skip > 0:
                body["skip"] = skip

            try:
                data = self._post_json(SEARCH_URL, body)
            except CrawlerError:
                if self._url_type == "category":
                    log.warning(
                        "SnappShop category API pagination limit reached at skip=%d "
                        "(API cap ~250 products per category). Stopping early.",
                        skip,
                    )
                    break
                raise
            structure = data.get("data", {}).get("structure", [])

            plp = next((s for s in structure if s.get("section_type") == "plp"), None)
            if not plp:
                break

            if total_pages is None:
                pag = plp.get("pagination", {})
                total_pages = pag.get("total_pages", 1)
                log.info("Total products: %s | Pages: %d", pag.get("total"), total_pages)

            items = plp.get("items", [])
            if not items:
                break

            for item in items:
                href = item.get("href", "")
                # href = "/product/snp-1031374112?seller_id=0W6W2g"
                numeric_id = self._parse_numeric_id(href)
                if numeric_id:
                    yield numeric_id

            log.info("Page %d/%d: %d items", page, total_pages, len(items))

            if page >= total_pages:
                break
            page += 1
            skip += PAGE_SIZE
            time.sleep(self.rate_limit)

    def get_product_detail(self, product_id: str) -> Product:
        url = DETAIL_URL.format(product_id=product_id)
        params = {
            "lat": DEFAULT_LAT,
            "lng": DEFAULT_LNG,
        }
        if self._vendor_slug:
            params["seller_id"] = self._vendor_slug

        data = self._get_json(url, params=params)
        item = data.get("data") or {}

        if not item:
            raise ProductUnavailableError(f"No data for product {product_id}")

        page_info = item.get("page", {}) or {}
        if page_info.get("is_deactive") or page_info.get("status_code") == 404:
            raise ProductUnavailableError(f"Product {product_id} is deactivated")

        title = self._extract_title(item)
        description = self._extract_description(item)
        images = self._extract_images(item, page_info)
        product_url = f"{BASE_URL}/product/snp-{product_id}"

        variants = self._extract_variants(item, product_id)
        if not variants:
            raise ProductUnavailableError(f"Product {product_id} has no available variants from this seller")

        category = self._extract_category(item)

        return Product(
            source_id=product_id,
            title=title,
            description=description,
            url=product_url,
            images=images,
            category=category,
            variants=variants,
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _extract_images(self, item: dict, page_info: dict) -> list:
        og_image = next(
            (m["content"] for m in (page_info.get("extra_meta") or [])
             if m.get("property") == "og:image" and m.get("content")),
            None,
        )
        gallery = [img["src"] for img in item.get("images", []) if img.get("src")]
        seen: set = set()
        result = []
        for url in ([og_image] if og_image else []) + gallery:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    def _extract_title(self, item: dict) -> str:
        # Prefer the first image alt tag — clean product name without SEO prefix
        images = item.get("images", [])
        if images and images[0].get("alt"):
            return images[0]["alt"]
        # Fall back to page title, stripping "خرید و قیمت " prefix
        page_title = item.get("page", {}).get("title", "")
        return _TITLE_PREFIX_RE.sub("", page_title).strip()

    def _extract_description(self, item: dict) -> str:
        raw = (item.get("content") or {}).get("description") or ""
        clean = _HTML_TAG_RE.sub(" ", raw)
        return " ".join(clean.split())

    def _extract_category(self, item: dict) -> str:
        cats = item.get("categories") or []
        if cats:
            return cats[-1].get("title") or cats[0].get("title") or ""
        return ""

    def _extract_variants(self, item: dict, product_id: str) -> list:
        variants_raw = item.get("variants") or []
        product_attrs = {
            a["title"]: a["value"]
            for a in (item.get("attributes") or [])
            if a.get("title") and a.get("value")
        }

        # configurable_attribute is a list of {id, title, value: {id, title, ...}}
        # representing the selected variant's configurable attrs (color, size, etc.)
        conf_attrs: dict = {}
        for ca in (item.get("configurable_attribute") or []):
            name = ca.get("title", "")
            val = (ca.get("value") or {}).get("title", "")
            if name and val:
                conf_attrs[name] = val

        result = []
        for idx, v in enumerate(variants_raw):
            vendor = self._find_seller_vendor(v)
            if not vendor:
                continue

            price_rial = self._to_int(vendor.get("price") or 0)
            special_rial = self._to_int(vendor.get("special_price") or 0)

            price = price_rial // 10
            discount_price = None
            if special_rial > 0 and special_rial < price_rial:
                discount_price = special_rial // 10

            attrs = {**product_attrs, **conf_attrs}

            result.append(ProductVariant(
                variant_index=idx,
                sku=f"SS-{product_id}-{idx}",
                price=price,
                discount_price=discount_price,
                stock=UNLIMITED_STOCK,
                weight=None,
                attributes=dict(list(attrs.items())[:10]),
            ))

        return result

    def _find_seller_vendor(self, variant: dict) -> dict | None:
        vendors = variant.get("vendor") or []
        if not vendors:
            return None
        if self._vendor_slug:
            match = next((v for v in vendors if v.get("vendor_id") == self._vendor_slug), None)
            if match:
                return match
        # Fall back to min_price_vendor or first vendor
        mv = variant.get("min_price_vendor")
        if mv:
            return mv
        return vendors[0] if vendors else None

    def _post_json(self, url: str, body: dict, retries: int = 3) -> dict:
        params = {"lat": DEFAULT_LAT, "lng": DEFAULT_LNG}
        for attempt in range(retries):
            try:
                resp = self._session.post(url, params=params, json=body, timeout=20)
                resp.raise_for_status()
                d = resp.json()
                if not d.get("status", True) and d.get("code"):
                    raise CrawlerError(f"API error {d['code']}: {d.get('message','')}")
                return d
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                if status in (404, 410, 422) or attempt == retries - 1:
                    raise CrawlerError(f"HTTP {status} for {url}") from e
            except CrawlerError:
                raise
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise CrawlerError(f"Network error for {url}: {e}") from e
            backoff = 5 * (attempt + 1)
            log.warning("Retry %d/%d in %ds for %s", attempt + 1, retries, backoff, url)
            time.sleep(backoff)

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
    def _parse_numeric_id(href: str) -> str:
        # href = "/product/snp-1031374112?seller_id=0W6W2g"
        m = re.search(r"/product/snp-(\d+)", href)
        return m.group(1) if m else ""

    @staticmethod
    def _to_int(val) -> int:
        try:
            return int(float(str(val).replace(",", "").strip()))
        except (ValueError, TypeError):
            return 0
