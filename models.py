from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductVariant:
    variant_index: int
    sku: str
    price: int
    discount_price: Optional[int]
    stock: int
    weight: Optional[int]
    attributes: dict  # {attr_name: attr_value}, insertion-ordered, max 10 used


@dataclass
class Product:
    source_id: str
    title: str
    description: str
    url: str
    images: list
    category: str
    variants: list = field(default_factory=list)
    is_active: bool = True
