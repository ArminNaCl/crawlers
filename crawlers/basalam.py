import re
import time
import logging
from typing import Iterator
from urllib.parse import urlparse, unquote, parse_qs

import requests

from crawlers.base import BaseCrawler, ProductUnavailableError, CrawlerError
from models import Product, ProductVariant

log = logging.getLogger(__name__)

SEARCH_URL = "https://search.basalam.com/ai-engine/api/v2.0/product/search"
DETAIL_URL = "https://core.basalam.com/v3/products/{product_id}"
PAGE_SIZE = 24
UNLIMITED_STOCK = -1
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_IMG_PATH_HINTS = {"/image/", "/images/", "/photo/", "/photos/", "/media/"}


class BasalamCrawler(BaseCrawler):

    site_name = "basalam"

    def __init__(self, rate_limit: float = 0.75):
        self.rate_limit = rate_limit
        self._url_type = "vendor"   # "vendor" or "category"
        self._category_url = ""     # decoded path, e.g. /cat/appliances/پنکه-دستی
        self._cat_bar_id = None     # cat_bar query param for vendor category filter
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Referer": "https://basalam.com/",
        })

    # ------------------------------------------------------------------ #
    # BaseCrawler interface                                                #
    # ------------------------------------------------------------------ #

    def extract_vendor_id(self, url: str) -> str:
        parsed = urlparse(url)
        # URL-decode each path segment individually
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        if not parts:
            raise ValueError(f"Cannot extract source ID from: {url}")

        if parts[0] == "cat":
            # Category URL: /cat/{parentSlug}/{leafSlug}
            self._url_type = "category"
            self._category_url = "/" + "/".join(parts)   # decoded, e.g. /cat/appliances/پنکه-دستی
            return parts[-1]                              # leaf slug returned as the "source_id"

        # Vendor profile URL: /{vendor_slug}[?cat_bar=N or ?cat=N]
        self._url_type = "vendor"
        self._category_url = ""
        qs = parse_qs(parsed.query)
        cat_filter = qs.get("cat_bar", qs.get("cat", [None]))[0]
        self._cat_bar_id = cat_filter if cat_filter else None
        return parts[-1]

    def iter_product_ids(self, source_id: str) -> Iterator[str]:
        if self._url_type == "category":
            yield from self._iter_category_product_ids(source_id)
        else:
            yield from self._iter_vendor_product_ids(source_id)

    def _iter_vendor_product_ids(self, vendor_id: str) -> Iterator[str]:
        offset = 0
        while True:
            params = {
                "filters.vendorIdentifier": vendor_id,
                "from": offset,
                "size": PAGE_SIZE,
            }
            data = self._get_json(SEARCH_URL, params=params)
            items = self._extract_hits(data)

            if not items:
                break

            for item in items:
                pid = self._item_id(item)
                if not pid:
                    continue
                if not self._item_active(item):
                    continue
                if self._cat_bar_id and not self._item_matches_cat_bar(item):
                    continue
                yield pid

            if len(items) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
            time.sleep(self.rate_limit)

    def _iter_category_product_ids(self, leaf_slug: str) -> Iterator[str]:
        # parent slug = second-to-last segment of the decoded category URL
        # e.g. /cat/appliances/پنکه-دستی  →  parent=appliances, slug=پنکه-دستی
        cat_parts = [p for p in self._category_url.split("/") if p]
        parent_slug = cat_parts[-2] if len(cat_parts) >= 3 else cat_parts[0]

        offset = 0
        total = None
        while True:
            params = {
                "url": self._category_url,
                "from": offset,
                "q": "",
                "dynamicFacets": "true",
                "size": PAGE_SIZE,
                "slug": leaf_slug,
                "parentSlug": parent_slug,
                "enableNavigations": "true",
                "adsImpressionDisable": "false",
            }
            data = self._get_json(SEARCH_URL, params=params)
            if total is None:
                total = data.get("meta", {}).get("count", 0)
                log.info("Category total products: %s", total)

            items = self._extract_hits(data)
            if not items:
                break

            for item in items:
                pid = self._item_id(item)
                if not pid:
                    continue
                if not self._item_active(item):
                    continue
                yield pid

            if len(items) < PAGE_SIZE:
                break

            offset += PAGE_SIZE
            time.sleep(self.rate_limit)

    def get_product_detail(self, product_id: str) -> Product:
        url = DETAIL_URL.format(product_id=product_id)
        data = self._get_json(url)
        return self._parse_product(data, product_id)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

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

    def _extract_hits(self, data: dict) -> list:
        """Handle the multiple shapes the search API may return."""
        # Shape 1: {"data": {"products": [...]}}
        if isinstance(data.get("data"), dict):
            inner = data["data"]
            for key in ("products", "items", "hits"):
                if isinstance(inner.get(key), list):
                    return inner[key]
        # Shape 2: {"hits": {"hits": [...]}}
        if isinstance(data.get("hits"), dict):
            return data["hits"].get("hits", [])
        # Shape 3: {"hits": [...]}
        if isinstance(data.get("hits"), list):
            return data["hits"]
        # Shape 4: {"products": [...]}
        if isinstance(data.get("products"), list):
            return data["products"]
        return []

    def _item_id(self, item: dict) -> str:
        for key in ("id", "_id", "productId", "product_id"):
            val = item.get(key)
            if val is not None:
                return str(val)
        # Sometimes the source item is nested under "_source"
        src = item.get("_source", {})
        for key in ("id", "productId"):
            val = src.get(key)
            if val is not None:
                return str(val)
        return ""

    def _item_matches_cat_bar(self, item: dict) -> bool:
        src = item.get("_source", item)
        target = str(self._cat_bar_id)
        for field in ("categoryId", "new_categoryId"):
            val = src.get(field)
            if val is not None and str(val) == target:
                return True
        return False

    def _item_active(self, item: dict) -> bool:
        src = item.get("_source", item)
        active = src.get("isActive", src.get("is_active", True))
        available = src.get("isAvailable", src.get("is_available", True))
        return bool(active) and bool(available)

    def _parse_product(self, data: dict, product_id: str) -> Product:
        # Many endpoints wrap response in {"data": {...}}
        item = data.get("data", data)
        if isinstance(item, list):
            item = item[0] if item else {}

        if not self._item_active(item):
            raise ProductUnavailableError(f"Product {product_id} is inactive")

        images = self._extract_images(item)
        variants = self._extract_variants(item, product_id)
        url = item.get("url") or item.get("link") or f"https://basalam.com/p/{product_id}"

        return Product(
            source_id=product_id,
            title=item.get("title") or item.get("name") or "",
            description=self._clean_html(item.get("description") or item.get("body") or ""),
            url=url,
            images=images,
            category="",
            variants=variants,
            is_active=True,
        )

    def _extract_images(self, item: dict) -> list:
        # Basalam v3 detail: "photos" is a list of dicts with "original", "xs", "sm", "md", "lg"
        # Also include the main "photo" dict if not already in the list
        raw = list(item.get("photos") or item.get("images") or item.get("media") or [])
        main_photo = item.get("photo")
        if isinstance(main_photo, dict):
            raw = [main_photo] + raw  # prepend so primary image comes first

        urls = []
        seen = set()
        for img in raw:
            if isinstance(img, dict):
                # prefer full-resolution; fall back to progressively smaller sizes
                url = (img.get("original") or img.get("url") or img.get("lg")
                       or img.get("md") or img.get("src") or img.get("link") or "")
            else:
                url = str(img)
            if url and url not in seen and self._is_image_url(url):
                urls.append(url)
                seen.add(url)
        return list(reversed(urls))

    def _is_image_url(self, url: str) -> bool:
        if not url:
            return False
        path = url.lower().split("?")[0]
        if any(path.endswith(ext) for ext in _IMG_EXTS):
            return True
        return any(hint in path for hint in _IMG_PATH_HINTS)

    def _extract_variants(self, item: dict, product_id: str) -> list:
        raw_variants = item.get("variants") or item.get("combinations") or []

        if not raw_variants:
            # Single-variant product — synthesize one from product-level fields
            return [self._make_variant(item, product_id, idx=0, variant_data={})]

        result = []
        for idx, v in enumerate(raw_variants):
            result.append(self._make_variant(item, product_id, idx=idx, variant_data=v))
        return result

    def _make_variant(self, item: dict, product_id: str, idx: int, variant_data: dict) -> ProductVariant:
        # Price: prefer variant-level, fall back to product-level; divide by 10 (Rial → Toman)
        price_raw = variant_data.get("price") or item.get("price") or 0
        price = self._to_int(price_raw) // 10

        discount_raw = (variant_data.get("discountPrice") or variant_data.get("discount_price")
                        or item.get("discountPrice") or item.get("discount_price"))
        discount = self._to_int(discount_raw) // 10 if discount_raw else None

        weight_raw = variant_data.get("weight") or item.get("net_weight") or item.get("weight")
        weight = self._to_int(weight_raw) if weight_raw else None

        attrs = self._extract_variant_attrs(variant_data, item)

        return ProductVariant(
            variant_index=idx,
            sku=f"BS-{product_id}-{idx}",
            price=price,
            discount_price=discount,
            stock=UNLIMITED_STOCK,
            weight=weight,
            attributes=attrs,
        )

    def _extract_variant_attrs(self, variant: dict, product: dict) -> dict:
        attrs = {}

        # Basalam v3: variant-level attrs are in "properties"
        # Structure: [{property: {title: "سایز"}, value: {title: "XL"}}]
        for prop in variant.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            key = prop.get("property", {}).get("title", "")
            val = prop.get("value", {}).get("title", "")
            if key and val and len(attrs) < 10:
                attrs[str(key)] = str(val)

        # Fallback: old-style "attributes" list [{title, value}] used by some endpoints
        if not attrs:
            for attr in variant.get("attributes") or []:
                if not isinstance(attr, dict):
                    continue
                key = attr.get("title") or attr.get("name") or attr.get("key") or ""
                val = attr.get("value") or attr.get("option") or attr.get("label") or ""
                if key and val and len(attrs) < 10:
                    attrs[str(key)] = str(val)

        # Add product-level attributes (material, color list, etc.) that are not already present
        # Structure: [{key: "رنگ", value: "..."}, ...]
        for attr in product.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            key = str(attr.get("key") or "")
            val = str(attr.get("value") or "")
            if key and val and key not in attrs and len(attrs) < 10:
                attrs[key] = val

        return attrs

    @staticmethod
    def _clean_html(text: str) -> str:
        clean = _HTML_TAG_RE.sub(" ", text)
        return " ".join(clean.split())

    @staticmethod
    def _to_int(val) -> int:
        try:
            return int(float(str(val).replace(",", "").strip()))
        except (ValueError, TypeError):
            return 0
