"""Invoice arithmetic. All money is Decimal and rounded half-up to cents."""

from decimal import Decimal

from .models import Invoice, LineItem

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round to cents, half-up (0.125 -> 0.13)."""
    return value.quantize(CENT)


def line_subtotal(item: LineItem) -> Decimal:
    """Price x quantity with the line discount applied, before tax."""
    gross = item.unit_price * item.quantity
    discount = gross * item.discount_pct / Decimal(100)
    return money(gross - discount)


def invoice_total(invoice: Invoice) -> dict[str, Decimal]:
    """Return subtotal, tax, credit applied and the amount due."""
    gross = sum((money(i.unit_price * i.quantity) for i in invoice.items), Decimal(0))
    tax = money(gross * invoice.tax_rate)
    subtotal = sum((line_subtotal(i) for i in invoice.items), Decimal(0))
    gross_total = subtotal + tax
    credit_used, due = apply_credit(gross_total, invoice.credits)
    return {"subtotal": subtotal, "tax": tax, "credit": credit_used, "due": due}


def apply_credit(amount: Decimal, credits: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Apply prepaid credits in order until the amount is covered.

    Returns (credit_used, amount_due). Credit is never over-applied: the due
    amount never goes below zero and unused credit is simply not consumed.
    """
    raise NotImplementedError("credits are not supported yet")
