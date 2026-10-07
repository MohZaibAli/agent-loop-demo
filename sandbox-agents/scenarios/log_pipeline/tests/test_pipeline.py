from datetime import datetime, timezone

from logpipe import error_rates, parse_line, top_services, window

RAW = """
2024-05-01T12:00:00Z service=checkout status=200 ms=120
2024-05-01T12:00:05Z service=checkout status=502 ms=900
2024-05-01T12:00:10Z service=search status=200 ms=40
2024-05-01T12:00:15+00:00 service=search status=503 ms=1200
2024-05-01T12:00:20Z service=search status=500 ms=1100
2024-05-01T12:00:25Z service=auth status=200 ms=15
2024-05-01T12:00:30Z service=auth status=404 ms=20
2024-05-01T12:01:00Z service=billing status=201 ms=80
"""
LINES = [l for l in (parse_line(r) for r in RAW.splitlines()) if l]
UTC = timezone.utc


def test_parse_basic_line():
    line = parse_line("2024-05-01T12:00:00Z service=checkout status=200 ms=120")
    assert line.service == "checkout" and line.status == 200 and line.ms == 120


def test_parse_z_suffix_is_utc():
    line = parse_line("2024-05-01T12:00:00Z service=a status=200")
    assert line.ts == datetime(2024, 5, 1, 12, 0, tzinfo=UTC)
    assert line.ts.tzinfo is not None


def test_parse_malformed_returns_none():
    assert parse_line("garbage line without fields") is None
    assert parse_line("") is None
    assert parse_line("2024-05-01T12:00:00Z service=a status=notanumber") is None


def test_parse_skips_bad_lines_in_batch():
    raw = RAW.splitlines() + ["garbage line without fields", "   "]
    assert len([l for l in (parse_line(r) for r in raw) if l]) == 8


def test_window_end_exclusive():
    start = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)
    end = datetime(2024, 5, 1, 12, 0, 20, tzinfo=UTC)
    got = window(LINES, start, end)
    assert [l.status for l in got] == [200, 502, 200, 503]


def test_error_rates():
    rates = error_rates(LINES)
    assert rates["checkout"] == 0.5
    assert rates["search"] == 2 / 3
    assert rates["auth"] == 0.0  # 404 is not a server error
    assert rates["billing"] == 0.0


def test_error_rates_empty_input():
    assert error_rates([]) == {}


def test_top_services_worst_first():
    assert top_services(LINES, 2) == [("search", 2 / 3), ("checkout", 0.5)]


def test_top_services_ties_by_name():
    top = top_services(LINES, 4)
    assert top[2:] == [("auth", 0.0), ("billing", 0.0)]
