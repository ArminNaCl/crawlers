from abc import ABC, abstractmethod
from typing import Iterator

from models import Product


class ProductUnavailableError(Exception):
    """Product exists on source but is inactive or removed."""


class CrawlerError(Exception):
    """HTTP or network error from a crawler."""


class BaseCrawler(ABC):

    @abstractmethod
    def extract_vendor_id(self, url: str) -> str:
        """Parse the vendor identifier from a profile URL."""
        ...

    @abstractmethod
    def iter_product_ids(self, vendor_id: str) -> Iterator[str]:
        """
        Yield product IDs for a given vendor.
        Paginates internally. Yields only products that appear active at the
        listing level (avoids wasting detail-fetch calls on obviously dead items).
        """
        ...

    @abstractmethod
    def get_product_detail(self, product_id: str) -> Product:
        """
        Fetch full product data for a single ID.
        Raises ProductUnavailableError if the product is inactive or deleted.
        """
        ...

    @property
    @abstractmethod
    def site_name(self) -> str:
        """Short identifier used as source_site key in memory (e.g. 'basalam')."""
        ...
