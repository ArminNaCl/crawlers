import csv
import os
from pathlib import Path

from models import Product, ProductVariant

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_VARIANT_ATTRS = 10

COLUMNS = [
    "identifier",
    "product id",
    "variant id",
    "title",
    "description",
    "url",
    "enabled",
    "images",
    "category",
    "variant commercial asset link",
    "variant image id",
    "sku",
    "weight",
    "price",
    "discount price",
    "stock quantity",
    "type",
    "min purchase",
    "max purchase",
    "variant sort index",
    "seo title",
    "seo description",
    "seo keywords",
    "seo redirect",
    "seo canonical",
    "seo index",
] + [f"variant {i} attributes" for i in range(1, MAX_VARIANT_ATTRS + 1)]


class SazitoCsvExporter:

    def __init__(self, output_dir: str, file_prefix: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file_prefix = file_prefix

        self._file_index = 1
        self._identifier_counter = 1
        self._current_file = None
        self._current_writer = None
        self._current_size = 0
        self.files_written = 0

        self._open_new_file()

    def _open_new_file(self):
        if self._current_file:
            self._current_file.close()
        name = f"{self.file_prefix}_{self._file_index:03d}.csv"
        path = self.output_dir / name
        # utf-8-sig writes BOM so Excel renders Persian text correctly
        self._current_file = open(path, "w", newline="", encoding="utf-8-sig")
        self._current_writer = csv.DictWriter(
            self._current_file,
            fieldnames=COLUMNS,
            extrasaction="ignore",
            lineterminator="\r\n",
            restval="",
        )
        self._current_writer.writeheader()
        self._current_file.flush()
        self._current_size = self._current_file.tell()
        self._file_index += 1
        self.files_written += 1

    def write_product(self, product: Product):
        identifier = self._identifier_counter
        self._identifier_counter += 1

        rows = [self._build_row(product, v, identifier) for v in product.variants]

        # Estimate size (rough: average 800 bytes per row) to decide if we should
        # roll over before writing so all variant rows land in the same file.
        estimated = len(rows) * 800
        if self._current_size + estimated >= MAX_FILE_BYTES:
            self._open_new_file()

        for row in rows:
            self._current_writer.writerow(row)

        self._current_file.flush()
        self._current_size = self._current_file.tell()

        # If we've gone over after writing, next product will trigger a new file.
        # This can only happen when a product's rows themselves exceed 5 MB (very
        # unlikely), so we don't force another roll here.

    def _build_row(self, product: Product, variant: ProductVariant, identifier: int) -> dict:
        row = {
            "identifier": identifier,
            "product id": "",
            "variant id": "",
            "title": product.title,
            "description": product.description,
            "url": "",
            "enabled": "false",
            "images": ",".join(product.images),
            "category": product.category,
            "variant commercial asset link": "",
            "variant image id": "",
            "sku": variant.sku,
            "weight": variant.weight if variant.weight is not None else "",
            "price": variant.price,
            "discount price": variant.discount_price if variant.discount_price is not None else "",
            "stock quantity": variant.stock,
            "type": "physical",
            "min purchase": 1,
            "max purchase": "",
            "variant sort index": variant.variant_index,
            "seo title": "",
            "seo description": "",
            "seo keywords": "",
            "seo redirect": "",
            "seo canonical": "",
            "seo index": "",
        }

        attr_items = list(variant.attributes.items())[:MAX_VARIANT_ATTRS]
        for i, (key, value) in enumerate(attr_items, start=1):
            row[f"variant {i} attributes"] = f"{key}={value}"

        return row

    def close(self):
        if self._current_file:
            self._current_file.close()
            self._current_file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
