"""Parse luxury-watch dealer WhatsApp messages into structured listings."""

import re

BRANDS = {
    "rolex": "Rolex",
    "patek": "Patek Philippe",
    "ap": "Audemars Piguet",
    "audemars": "Audemars Piguet",
    "omega": "Omega",
    "cartier": "Cartier",
    "tudor": "Tudor",
}

# Reference numbers: digits with optional letters/dashes, e.g. 126610LN, 5711/1A, 15202ST
REF_RE = re.compile(r"\b(\d{4,6}[A-Z0-9/\-\.]*)\b")

# Currency symbol or ISO code followed by an amount.
CURRENCY_RE = re.compile(
    r"(?P<cur>\$|€|£|HKD|USD|EUR|GBP|SGD|CHF|JPY)\s*"
    r"(?P<amt>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k)?",
    re.IGNORECASE,
)

SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


def _detect_brand(text: str) -> str | None:
    for token in re.findall(r"[A-Za-z]+", text):
        brand = BRANDS.get(token.lower())
        if brand:
            return brand
    return None


def _detect_ref(text: str) -> str | None:
    # Strip the price portion first so amounts like 98,000 are not mistaken for refs.
    stripped = CURRENCY_RE.sub(" ", text)
    match = REF_RE.search(stripped)
    return match.group(1) if match else None


def _detect_price(text: str) -> tuple[float | None, str | None]:
    match = CURRENCY_RE.search(text)
    if not match:
        return None, None
    amount = float(match.group("amt").replace(",", ""))
    cur = match.group("cur").upper()
    currency = SYMBOLS.get(cur, cur)
    return amount, currency


def parse_listing(message: str) -> dict:
    """Return brand, ref, price and currency extracted from a dealer message."""
    text = " ".join(message.split())
    price, currency = _detect_price(text)
    return {
        "brand": _detect_brand(text),
        "ref": _detect_ref(text),
        "price": price,
        "currency": currency,
    }
