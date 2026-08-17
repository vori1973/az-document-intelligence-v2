"""
Normalization for Azure Document Intelligence raw results.

The ADI SDK's `as_dict()` returns the REST wire format, which is camelCase
(`pageNumber`, `boundingRegions`, `rowIndex`). Downstream activities read the
stored `adi-raw.json` with snake_case keys, which silently returns `None` for
every one of them.

That failure mode is invisible: callers pair the lookup with a default
(`or 1`, `or []`), so a missing key becomes a plausible-looking value instead
of an error. It shipped a whole index whose citations all claimed page 1.

Normalizing once, at the point the artifact is written, keeps every consumer
on a single convention instead of asking 17 call sites to remember which
casing this particular dict uses.
"""

from __future__ import annotations

import re
from typing import Any

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _to_snake(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def normalize_adi_dict(value: Any) -> Any:
    """Recursively convert camelCase keys to snake_case.

    Values are untouched — only mapping keys are rewritten — so content,
    polygons, and spans pass through unchanged.
    """
    if isinstance(value, dict):
        return {_to_snake(k): normalize_adi_dict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_adi_dict(v) for v in value]
    return value
