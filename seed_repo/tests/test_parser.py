from listing_parser import parse_listing


def test_rolex_usd_symbol():
    r = parse_listing("Rolex 126610LN full set $14,500 shipped")
    assert r == {"brand": "Rolex", "ref": "126610LN", "price": 14500.0, "currency": "USD"}


def test_patek_eur_symbol():
    r = parse_listing("Patek 5711/1A-010 unworn €180,000")
    assert r["brand"] == "Patek Philippe"
    assert r["ref"] == "5711/1A-010"
    assert r["price"] == 180000.0
    assert r["currency"] == "EUR"


def test_ap_iso_code():
    r = parse_listing("AP 15202ST 2021 USD 95000 firm")
    assert r["brand"] == "Audemars Piguet"
    assert r["ref"] == "15202ST"
    assert (r["price"], r["currency"]) == (95000.0, "USD")


def test_hk_dollar_prefix():
    r = parse_listing("Rolex 126710BLRO HK$98,000 fullset")
    assert r["ref"] == "126710BLRO"
    assert r["price"] == 98000.0
    assert r["currency"] == "HKD"


def test_k_suffix():
    r = parse_listing("Tudor 79830RB HKD 85k")
    assert r["brand"] == "Tudor"
    assert r["price"] == 85000.0
    assert r["currency"] == "HKD"


def test_gbp_with_decimal():
    r = parse_listing("Omega 310.30.42.50.01.001 £5,250.50")
    assert r["brand"] == "Omega"
    assert r["price"] == 5250.5
    assert r["currency"] == "GBP"


def test_no_price():
    r = parse_listing("Cartier 4152 looking for offers")
    assert r["brand"] == "Cartier"
    assert r["ref"] == "4152"
    assert r["price"] is None
    assert r["currency"] is None


def test_whitespace_normalised():
    r = parse_listing("  Rolex   124300\n  SGD  12,800 ")
    assert r["ref"] == "124300"
    assert (r["price"], r["currency"]) == (12800.0, "SGD")
