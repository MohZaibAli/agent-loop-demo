from decimal import Decimal as D

from invoices import Invoice, LineItem, apply_credit, invoice_total, line_subtotal


def test_line_subtotal_plain():
    assert line_subtotal(LineItem("widget", D("9.99"), 3)) == D("29.97")


def test_line_subtotal_discount_before_tax():
    assert line_subtotal(LineItem("widget", D("100.00"), 1, D("15"))) == D("85.00")


def test_rounding_half_up():
    # 0.125 must round to 0.13, not banker's 0.12
    assert line_subtotal(LineItem("tiny", D("0.125"), 1)) == D("0.13")


def test_invoice_total_tax_on_discounted_subtotal():
    inv = Invoice("A1", [LineItem("svc", D("200.00"), 1, D("50"))], tax_rate=D("0.10"))
    t = invoice_total(inv)
    assert t["subtotal"] == D("100.00")
    assert t["tax"] == D("10.00")
    assert t["due"] == D("110.00")


def test_invoice_multiple_lines():
    inv = Invoice("A2", [LineItem("a", D("10.00"), 2), LineItem("b", D("5.50"), 1, D("10"))], tax_rate=D("0.20"))
    t = invoice_total(inv)
    assert t["subtotal"] == D("24.95")
    assert t["tax"] == D("4.99")
    assert t["due"] == D("29.94")


def test_credit_partial():
    assert apply_credit(D("50.00"), [D("20.00")]) == (D("20.00"), D("30.00"))


def test_credit_never_over_applied():
    assert apply_credit(D("50.00"), [D("80.00")]) == (D("50.00"), D("0.00"))


def test_credit_in_order_stops_when_covered():
    used, due = apply_credit(D("30.00"), [D("10.00"), D("25.00"), D("99.00")])
    assert (used, due) == (D("30.00"), D("0.00"))


def test_invoice_total_with_credits():
    inv = Invoice("A3", [LineItem("a", D("100.00"))], tax_rate=D("0.20"), credits=[D("50.00"), D("100.00")])
    t = invoice_total(inv)
    assert t["credit"] == D("120.00")
    assert t["due"] == D("0.00")


def test_no_items():
    t = invoice_total(Invoice("empty"))
    assert t == {"subtotal": D("0"), "tax": D("0.00"), "credit": D("0.00"), "due": D("0.00")}
