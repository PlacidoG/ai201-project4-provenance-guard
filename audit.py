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


def log_entry(entry: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_log(limit: int = 50) -> list:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    return entries[-limit:][::-1]  # most recent first
