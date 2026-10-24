"""Audio clip keys. Swift's Speaker computes the identical key (CONTRACTS.md, Audio hashing)."""
import hashlib
import re

from . import shared

_WS = re.compile(r"\s+")


def normalize(text):
    return _WS.sub(" ", text.strip())


def clip_key(text):
    return hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()


def for_cartesia(text):
    """Apply the pronunciation map (whole words only). Only the text sent to Cartesia changes; the key does not."""
    out = normalize(text)
    for src, dst in sorted(shared.pronunciation().items(), key=lambda kv: -len(kv[0])):
        if src == dst:
            continue
        out = re.sub(rf"\b{re.escape(src)}\b", dst, out)
    return out
