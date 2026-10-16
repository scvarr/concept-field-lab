"""Shared validation and snapshot encoding for the permanent graph."""
import json
import zlib
from datetime import datetime, timezone
from uuid import uuid4


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    pass


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(state):
    return zlib.compress(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def decode(payload):
    return json.loads(zlib.decompress(payload) if isinstance(payload, bytes) else payload)


def clean(value, name, required=False, limit=50000):
    if not isinstance(value, str) or len(value) > limit:
        raise Invalid(f"Некорректное поле «{name}» (предел {limit} символов).")
    value = value.strip()
    if required and not value:
        raise Invalid(f"Заполните поле «{name}».")
    return value


def fields(data):
    return {key: clean(data.get(key, ""), key, key == "label" and data.get("structure", "concept") != "combination" and data.get("designationOnly") is not True, 1000 if key in ("label", "kind") else 50000)
            for key in ("label", "kind", "notes", "alternatives", "source")}


def lookup(items, identity, what):
    for item in items:
        if item["id"] == identity:
            return item
    raise Invalid(f"Не найдено: {what}.")
