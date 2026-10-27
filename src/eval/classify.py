"""黄金集上的可重复分类。这不是业务结论，只给回归算代价。"""

from __future__ import annotations

import re

_LABELS = ("REAL_RFQ", "PRICE_PROBE", "COMPETITOR_PROBE", "SPAM_BLAST", "SAMPLE_REQUEST")


def classify_text(text: str) -> str:
    lowered = text.lower()
    if "competitor" in lowered or "your supplier" in lowered or "成本" in text:
        return "COMPETITOR_PROBE"
    if "sample only" in lowered or "just a sample" in lowered:
        return "SAMPLE_REQUEST"
    if "dear sir" in lowered and "and also" in lowered:
        return "SPAM_BLAST"
    has_qty = re.search(r"\d+\s*(pcs|kg|sets)", lowered) is not None
    has_place = any(token in lowered for token in ("hamburg", "port", "destination"))
    has_time = re.search(r"\d+\s*days", lowered) is not None
    if has_qty and has_place and has_time:
        return "REAL_RFQ"
    if "price" in lowered or "how much" in lowered:
        return "PRICE_PROBE"
    return "SPAM_BLAST"


def known_label(label: str) -> bool:
    return label in _LABELS
