"""Structured, persistent audit log for attribution decisions.

Append-only JSONL on disk (not print statements), so entries survive restarts
and accumulate across milestones for the README / GET /log demo.
"""

import json
import os
from datetime import datetime, timezone

LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.jsonl")


def utc_now() -> str:
    # ISO 8601 with a trailing Z, e.g. 2025-04-01T14:32:10.123456Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_all() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def log_entry(entry: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_log(limit: int = 50) -> list:
    return _read_all()[-limit:][::-1]  # most recent first


def update_entry(content_id: str, **fields) -> bool:
    """Update the audit entry for content_id in place, preserving its original
    decision fields. Returns True if a matching entry was found."""
    entries = _read_all()
    found = False
    for e in entries:
        if e.get("content_id") == content_id:
            e.update(fields)            # add/flip fields; original decision fields untouched
            found = True
    if found:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    return found
