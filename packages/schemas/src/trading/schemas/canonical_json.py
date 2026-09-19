"""The frozen canonical encoder for hashed documents.

Some documents are hashed and the hash is stored: ``strategy_spec_hash`` sits on
every experiment row (§9), and ``snapshot_id`` *is* the hash of a manifest body
(D10). If the encoder that produced those hashes changes, every stored hash
becomes unreproducible — the same failure as changing bytes on disk, reached by
a different route.

So the encoder is frozen at M1 even though the documents it encodes are not.
``StrategySpec``'s field set is genuinely unknown until the DSL lands at M5, but
how a document becomes bytes is knowable now, and freezing it now is what lets
M5 change the field set without invalidating anything already hashed.

Float literals are rejected. A float is not reproducible across platforms in its
last bits, and a hash over one is not a hash at all. Rates and ratios are encoded
as exact rationals or scaled integers.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Final

#: Bump only when the encoding itself changes, which invalidates every stored
#: hash. Recorded in the contract lock so such a change cannot pass unnoticed.
ENCODER_VERSION: Final = 1


class CanonicalEncodingError(ValueError):
    """A value cannot be encoded reproducibly."""


def _canonicalize(value: Any, path: str = "$") -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalEncodingError(
            f"{path}: float {value!r} is not reproducible across platforms in its "
            "last bits, so a hash over it is not stable. Use an exact rational "
            "(numerator/denominator) or a scaled integer."
        )
    if isinstance(value, str):
        # NFC so two visually identical strings from different sources encode
        # identically; otherwise a hash depends on how a ticker was typed.
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {
            _canonicalize(key, f"{path}.{key}"): _canonicalize(item, f"{path}.{key}")
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise CanonicalEncodingError(f"{path}: {type(value).__name__} has no canonical encoding")


def encode(document: dict[str, Any]) -> str:
    """Render a document as canonical JSON.

    Keys sorted, no insignificant whitespace, UTF-8 NFC strings, floats
    rejected. Invariant under key reordering, whitespace and comments;
    sensitive to every semantic change.
    """
    return json.dumps(
        _canonicalize(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def document_hash(document: dict[str, Any]) -> str:
    """Hash a document through the frozen canonical encoding."""
    return hashlib.sha256(encode(document).encode("utf-8")).hexdigest()
