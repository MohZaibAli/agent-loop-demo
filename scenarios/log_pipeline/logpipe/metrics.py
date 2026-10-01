"""Aggregations over parsed log lines."""

from collections import defaultdict
from datetime import datetime

from .parser import LogLine


def window(lines: list[LogLine], start: datetime, end: datetime) -> list[LogLine]:
    """Lines with start <= ts < end (end is exclusive)."""
    return [l for l in lines if start <= l.ts < end]


def error_rates(lines: list[LogLine]) -> dict[str, float]:
    """Fraction of 5xx responses per service, 0.0 for services with no requests."""
    totals: dict[str, int] = defaultdict(int)
    errors: dict[str, int] = defaultdict(int)
    for line in lines:
        totals[line.service] += 1
        if line.is_error:
            errors[line.service] += 1
    return {svc: (errors[svc] / totals[svc] if totals[svc] else 0.0) for svc in totals}


def top_services(lines: list[LogLine], n: int = 3) -> list[tuple[str, float]]:
    """The n services with the highest error rate, worst first; ties by name."""
    rates = error_rates(lines)
    ranked = sorted(rates.items(), key=lambda kv: kv[1])
    return ranked[:n]
