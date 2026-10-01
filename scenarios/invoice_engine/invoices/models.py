from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class LineItem:
    description: str
    unit_price: Decimal
    quantity: int = 1
    discount_pct: Decimal = Decimal("0")  # percentage off this line, before tax


@dataclass
class Invoice:
    number: str
    items: list[LineItem] = field(default_factory=list)
    tax_rate: Decimal = Decimal("0.20")
    credits: list[Decimal] = field(default_factory=list)  # prepaid credits applied to the total
