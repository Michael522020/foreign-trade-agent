"""开发信校验。未授权的数字、认证和链接都不能进 outbox。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNITS = r"pcs|days|kg|percent|usd"
_FACT = re.compile(rf"(?i)(?<![A-Za-z0-9])(\d+(?:\.\d+)?)[ \t]+({_UNITS})\b")
_LINK = re.compile(r"https?://", re.IGNORECASE)
_CE = re.compile(
    r"(?i)\bCE\b.{0,40}\b(certified|zertifiziert|certificado)\b"
    r"|\b(certified|zertifiziert|certificado)\b.{0,40}\bCE\b"
)
_FORBIDDEN_SUBJECT = ("free", "guarantee")

REJECTED_UNAPPROVED_FACT = "REJECTED_UNAPPROVED_FACT"
REJECTED_TOO_LONG = "REJECTED_TOO_LONG"
REJECTED_TOO_SHORT = "REJECTED_TOO_SHORT"
REJECTED_FIRST_TOUCH_LINK = "REJECTED_FIRST_TOUCH_LINK"
REJECTED_UNAPPROVED_CERT = "REJECTED_UNAPPROVED_CERT"
REJECTED_SUBJECT = "REJECTED_SUBJECT"


@dataclass(frozen=True)
class ApprovedFact:
    value: str
    unit: str
    src: str


def word_count(text: str) -> int:
    return len(text.split())


def drop_last_sentence(body: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", body.strip())
    if len(parts) <= 1:
        return body
    return " ".join(parts[:-1]).strip()


def _subject_reasons(subject: str) -> list[str]:
    words = subject.split()
    reasons: list[str] = []
    if len(words) > 6 or not words:
        reasons.append(REJECTED_SUBJECT)
    lowered = subject.lower()
    if lowered.startswith("re:") or lowered.startswith("fwd:"):
        reasons.append(REJECTED_SUBJECT)
    if any(token in lowered for token in _FORBIDDEN_SUBJECT):
        reasons.append(REJECTED_SUBJECT)
    if "!" in subject:
        reasons.append(REJECTED_SUBJECT)
    letters = [char for char in subject if char.isalpha()]
    if len(letters) > 3 and all(char.isupper() for char in letters):
        reasons.append(REJECTED_SUBJECT)
    return reasons


def collect_reasons(
    subject: str,
    body: str,
    facts: list[ApprovedFact],
    *,
    first_touch: bool,
    cert_allowed: bool,
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(_subject_reasons(subject))
    count = word_count(body)
    if count < 75:
        reasons.append(REJECTED_TOO_SHORT)
    if count > 125:
        reasons.append(REJECTED_TOO_LONG)
    if first_touch and _LINK.search(body):
        reasons.append(REJECTED_FIRST_TOUCH_LINK)
    if _CE.search(body) and not cert_allowed:
        reasons.append(REJECTED_UNAPPROVED_CERT)
    allowed = {(fact.value, fact.unit.lower()) for fact in facts}
    for match in _FACT.finditer(body):
        value = match.group(1)
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        unit = match.group(2).lower()
        if (value, unit) not in allowed:
            reasons.append(f"{REJECTED_UNAPPROVED_FACT}:{value} {unit}")
    return list(dict.fromkeys(reasons))


def validate_with_one_compress(
    subject: str,
    body: str,
    facts: list[ApprovedFact],
    *,
    first_touch: bool,
    cert_allowed: bool,
) -> tuple[str, list[str]]:
    reasons = collect_reasons(
        subject, body, facts, first_touch=first_touch, cert_allowed=cert_allowed
    )
    if REJECTED_TOO_LONG not in reasons:
        return body, reasons
    shortened = drop_last_sentence(body)
    if shortened == body:
        return body, reasons
    reasons = collect_reasons(
        subject, shortened, facts, first_touch=first_touch, cert_allowed=cert_allowed
    )
    return shortened, reasons
