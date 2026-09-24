"""Loading, merging and writing data/draws.json and data/next.json."""
import json
import os
from pathlib import Path

SCHEMA_VERSION = 1
_VOLATILE_FIELDS = {"scraped_at"}


def load_draws(path):
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["draws"]


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dumps_draws(draws):
    """One draw per line: compact for a phone, and each new draw is a one-line diff."""
    ordered = sorted(draws, key=lambda d: (d["game"], d["draw_number"]))
    lines = ",\n".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in ordered)
    return f'{{"schema_version":{SCHEMA_VERSION},"draws":[\n{lines}\n]}}\n'


def dumps_next(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def merge_draw(draws, record):
    """Insert record, or replace the stored one for the same draw. True if anything changed."""
    key = (record["game"], record["draw_number"])
    for i, existing in enumerate(draws):
        if (existing["game"], existing["draw_number"]) == key:
            if _stable(existing) == _stable(record):
                return False
            draws[i] = record
            return True
    draws.append(record)
    return True


def write_if_changed(path, content):
    """Atomically replace path with content. False if it already held exactly that."""
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temp, path)
    return True


def _stable(record):
    return {k: v for k, v in record.items() if k not in _VOLATILE_FIELDS}
