"""
Read the JSON log files for GET /admin/logs and the live stream.

- Scans newest-first across `app.log` and its rotated backups (`app.log.1` …) until enough
  entries match the filters, so filters apply to the whole history, not just the last N lines.
- One entry per JSON line. Lines that aren't log entries (legacy text tracebacks, stray prints)
  are folded into the entry they follow instead of showing up as separate rows.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from app.core.logger import LOG_FILE

LOG_FILE_PATH = Path(LOG_FILE)
MAX_SCAN_LINES = 200_000
_CHUNK = 64 * 1024

LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "WARN": 30, "ERROR": 40, "CRITICAL": 50}

# Pre-JSON text format: "<timestamp> - [LEVEL] - <logger> - <message>"
_LEGACY_LINE = re.compile(
    r"^(?P<timestamp>[^-]+?)\s+-\s+\[(?P<level>[A-Z]+)\]\s+-\s+(?P<logger>[^-]+?)\s+-\s+(?P<message>.*)$"
)


@dataclass
class LogFilters:
    contains: Optional[str] = None
    min_level: Optional[str] = None
    request_id: Optional[str] = None
    order_id: Optional[str] = None
    event: Optional[str] = None
    logger: Optional[str] = None

    def matches(self, entry: dict) -> bool:
        if self.min_level:
            if LEVEL_RANK.get(str(entry.get("level", "")).upper(), 0) < LEVEL_RANK.get(self.min_level.upper(), 0):
                return False
        if self.request_id and entry.get("request_id") != self.request_id:
            return False
        if self.order_id:
            # Older lines only mention the order in their text, so fall back to a text match.
            if entry.get("order_id") != self.order_id and self.order_id not in entry.get("raw", ""):
                return False
        if self.event and not str(entry.get("event") or "").startswith(self.event):
            return False
        if self.logger and not str(entry.get("logger") or "").startswith(self.logger):
            return False
        if self.contains and self.contains.lower() not in entry.get("raw", "").lower():
            return False
        return True


def log_files() -> list[Path]:
    """Current file first, then rotated backups newest → oldest."""
    files = [LOG_FILE_PATH] if LOG_FILE_PATH.exists() else []
    i = 1
    while True:
        p = Path(f"{LOG_FILE_PATH}.{i}")
        if not p.exists():
            break
        files.append(p)
        i += 1
    return files


def parse_line(line: str) -> Optional[dict]:
    """A log entry, or None when the line is a continuation of the previous entry."""
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "level" in data:
                ts = data.get("timestamp")
                # Older builds wrote "+00:00Z"; normalise to plain UTC "Z".
                if isinstance(ts, str) and ts.endswith("+00:00Z"):
                    data["timestamp"] = ts[: -len("+00:00Z")] + "Z"
                data["raw"] = stripped
                return data
        except ValueError:
            pass
    m = _LEGACY_LINE.match(stripped)
    if m:
        d = m.groupdict()
        return {
            "timestamp": d["timestamp"].strip(),
            "level": d["level"].strip(),
            "logger": d["logger"].strip(),
            "message": d["message"],
            "request_id": "-",
            "raw": stripped,
        }
    return None


def _attach_continuation(entry: dict, lines: list[str]) -> dict:
    text = "\n".join(lines)
    entry["stack_trace"] = (entry.get("stack_trace", "") + "\n" + text).strip("\n")
    entry["raw"] = entry["raw"] + "\n" + text
    return entry


def _reverse_lines(path: Path) -> Iterator[str]:
    """Lines of a file from last to first without reading it all into memory."""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        rest = b""
        while pos > 0:
            step = min(_CHUNK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step) + rest
            parts = chunk.split(b"\n")
            rest = parts[0]
            for part in reversed(parts[1:]):
                yield part.decode("utf-8", errors="replace")
        if rest:
            yield rest.decode("utf-8", errors="replace")


def read_entries(limit: int, filters: LogFilters) -> dict:
    """Newest `limit` matching entries, returned oldest → newest."""
    found: list[dict] = []
    scanned = 0
    pending: list[str] = []  # continuation lines seen (reading backwards) before their entry
    files = log_files()
    for path in files:
        for line in _reverse_lines(path):
            scanned += 1
            entry = parse_line(line)
            if entry is None:
                if line.strip():
                    pending.append(line.rstrip())
                continue
            if pending:
                entry = _attach_continuation(entry, list(reversed(pending)))
                pending = []
            if filters.matches(entry):
                found.append(entry)
                if len(found) >= limit:
                    break
            if scanned >= MAX_SCAN_LINES:
                break
        if len(found) >= limit or scanned >= MAX_SCAN_LINES:
            break
    found.reverse()
    return {
        "path": str(LOG_FILE_PATH.resolve()),
        "files": [p.name for p in files],
        "scanned_lines": scanned,
        "complete": scanned < MAX_SCAN_LINES,
        "count": len(found),
        "entries": found,
    }
