"""邮箱分档。smtp 探测默认关闭，避免探测本身伤发信信誉。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from dns.exception import DNSException
from dns.resolver import NoAnswer, NXDOMAIN, resolve

from src.models.enums import EmailStatus

_ROLE_LOCALS = frozenset(
    {
        "info",
        "sales",
        "contact",
        "admin",
        "office",
        "hello",
        "support",
        "enquiry",
        "inquiry",
        "marketing",
        "service",
    }
)
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class EmailVerdict:
    status: EmailStatus
    is_role_based: bool


def is_role_based(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in _ROLE_LOCALS


def syntax_ok(email: str) -> bool:
    if len(email) > 320 or not _EMAIL.fullmatch(email):
        return False
    domain = email.split("@", 1)[1]
    return "." in domain and not domain.startswith(".") and not domain.endswith(".")


def domain_has_mx(domain: str) -> bool:
    try:
        answers = resolve(domain, "MX")
    except (NXDOMAIN, NoAnswer, DNSException):
        return False
    return len(list(answers)) > 0


def verify_email(
    email: str,
    mx_lookup: Callable[[str], bool] | None = None,
) -> EmailVerdict:
    """传入 mx_lookup 时用它代替真实 DNS，测试不访问网络。"""
    role = is_role_based(email) if "@" in email else False
    if not syntax_ok(email):
        return EmailVerdict(EmailStatus.INVALID, role)
    domain = email.split("@", 1)[1].lower()
    lookup = domain_has_mx if mx_lookup is None else mx_lookup
    has_mx = lookup(domain)
    if not has_mx:
        return EmailVerdict(EmailStatus.RISKY, role)
    return EmailVerdict(EmailStatus.UNKNOWN, role)
