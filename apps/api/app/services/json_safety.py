from __future__ import annotations

import re
from typing import Any


_UNPAIRED_SURROGATE = re.compile(r"[\ud800-\udfff]")


def sanitize_json_value(value: Any) -> Any:
    """Replace invalid Unicode surrogate code points in decoded JSON values.

    Some G2B rows contain lone UTF-16 surrogate code points. Python's JSON
    decoder accepts them, but PostgreSQL/UTF-8 and payload hashing do not.
    Sanitizing once at the API boundary keeps the raw payload storable while
    preserving the rest of the row.
    """

    if isinstance(value, str):
        return _UNPAIRED_SURROGATE.sub("\ufffd", value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_json_value(key): sanitize_json_value(item)
            for key, item in value.items()
        }
    return value
