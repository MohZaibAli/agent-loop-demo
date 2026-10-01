"""Parse one structured access-log line.

Format:  2024-05-01T12:00:00Z service=checkout status=502 ms=130
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

LINE_RE = re.compile(r"^(?P<ts>\S+)\s+(?P<fields>.*)$")
FIELD_RE = re.compile(r"(\w+)=(\S+)")


@dataclass(frozen=True)
class LogLine:
    ts: datetime
    service: str
    status: int
    ms: int

    @property
    def is_error(self) -> bool:
        return self.status >= 500


def parse_timestamp(raw: str) -> datetime:
    """ISO-8601; a trailing Z means UTC. Naive timestamps are treated as UTC."""
    ts = datetime.fromisoformat(raw.rstrip("Z"))
    return ts


def parse_line(line: str) -> LogLine | None:
    """Return a LogLine, or None for blank/malformed lines."""
    match = LINE_RE.match(line.strip())
    if not match:
        return None
    fields = dict(FIELD_RE.findall(match.group("fields")))
    try:
        return LogLine(
            ts=parse_timestamp(match.group("ts")),
            service=fields["service"],
            status=int(fields["status"]),
            ms=int(fields.get("ms", 0)),
        )
    except KeyError:
        return None
