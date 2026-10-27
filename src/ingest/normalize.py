"""企业名归一化。只做确定性清洗，不做模糊合并。"""

from __future__ import annotations

import re

_SUFFIXES: tuple[str, ...] = (
    "company limited",
    "private limited",
    "pvt. ltd.",
    "pvt. ltd",
    "pvt ltd.",
    "pvt ltd",
    "co., ltd.",
    "co.,ltd.",
    "co., ltd",
    "co. ltd.",
    "co. ltd",
    "co ltd",
    "incorporated",
    "corporation",
    "limited",
    "ltd.",
    "ltd",
    "gmbh",
    "llc.",
    "llc",
    "inc.",
    "inc",
    "s.a.",
    "s.a",
    "corp.",
    "corp",
)


def _halfwidth(text: str) -> str:
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if code == 0x3000:
            chars.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(char)
    return "".join(chars)


def normalize_company_name(name: str) -> str:
    text = _halfwidth(name).lower().replace("’", "'")
    text = text.replace("&", " and ")
    text = text.replace("int'l", "international")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split(" ") if token]
    # 后缀可能由多个词组成，按原顺序拼回去再剥。
    joined = " ".join(tokens)
    changed = True
    while changed and joined:
        changed = False
        for suffix in _SUFFIXES:
            suffix_key = re.sub(r"[^a-z0-9]+", " ", suffix).strip()
            if joined == suffix_key or joined.endswith(" " + suffix_key):
                joined = joined[: -len(suffix_key)].strip()
                changed = True
                break
    return re.sub(r"\s+", " ", joined).strip()


def normalize_domain(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    text = re.sub(r"^https?://", "", text)
    text = text.split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    return text or None
