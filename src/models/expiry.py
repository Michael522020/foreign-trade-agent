"""报价过期扫描。只在这个任务里改状态，读取报价不会顺手把状态改成 EXPIRED。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.errors import ConstraintViolation, InvalidTransition
from src.logging_config import current_trace_id
from src.models.commercial import Quotation
from src.models.enums import QUOTATION_TERMINALS
from src.models.state_machine import QuotationEvent, transition

_log = structlog.get_logger("quotation_expiry")


@dataclass(frozen=True)
class ExpiryResult:
    expired_ids: list[str]
    skipped: list[tuple[str, str]]


def expire_due_quotations(session: Session, now: datetime) -> ExpiryResult:
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ConstraintViolation("now", "过期扫描的时间必须带时区", value=now)
    rows = session.scalars(select(Quotation)).all()
    expired: list[str] = []
    skipped: list[tuple[str, str]] = []
    for row in rows:
        if row.status in QUOTATION_TERMINALS or row.valid_until > now:
            continue
        lead_id = row.inquiry.lead_id if row.inquiry is not None else ""
        try:
            transition(row, QuotationEvent.EXPIRE)
        except (InvalidTransition, ConstraintViolation) as exc:
            skipped.append((row.id, str(exc)))
            _log.warning(
                "quotation_expire_skipped",
                lead_id=lead_id,
                trace_id=current_trace_id(),
                quotation_id=row.id,
                reason=str(exc),
            )
            continue
        expired.append(row.id)
    _log.info(
        "quotations_expired",
        lead_id="",
        trace_id=current_trace_id(),
        expired_count=len(expired),
        skipped_count=len(skipped),
    )
    return ExpiryResult(expired_ids=expired, skipped=skipped)
