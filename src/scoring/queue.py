"""每日队列。新客户和跟进分开截断，并记下被截掉的条数。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.logging_config import current_trace_id
from src.models.enums import LeadStage
from src.models.parties import Lead
from src.scoring.config import ScoringConfig

_log = structlog.get_logger("daily_queue")
_FOLLOW = frozenset(
    {LeadStage.CONTACTED, LeadStage.REPLIED, LeadStage.INQUIRY, LeadStage.QUOTING}
)
_EXCLUDED = frozenset({LeadStage.SUPPRESSED, LeadStage.NOT_INTERESTED, LeadStage.NURTURE})


@dataclass(frozen=True)
class QueueResult:
    items: list[Lead]
    truncated_count: int


def _confidence(lead: Lead) -> Decimal:
    raw = (lead.score_breakdown or {}).get("confidence", "0")
    return Decimal(str(raw))


def _total(lead: Lead) -> Decimal:
    raw = (lead.score_breakdown or {}).get("total", "0")
    return Decimal(str(raw))


def _window(lead: Lead) -> Decimal:
    bands = (lead.score_breakdown or {}).get("bands", {})
    if not isinstance(bands, dict):
        return Decimal(0)
    return Decimal(str(bands.get("window", "0")))


def _better(left: Lead, right: Lead) -> Lead:
    left_key = (_total(left), _window(left))
    right_key = (_total(right), _window(right))
    return left if left_key >= right_key else right


def _one_per_company(leads: list[Lead]) -> list[Lead]:
    chosen: dict[str, Lead] = {}
    for lead in leads:
        current = chosen.get(lead.company_id)
        chosen[lead.company_id] = lead if current is None else _better(current, lead)
    return list(chosen.values())


def _sort(leads: list[Lead]) -> list[Lead]:
    return sorted(leads, key=lambda lead: (_total(lead), _window(lead)), reverse=True)


def build_daily_queue(
    session: Session,
    owner: str,
    as_of: datetime,
    config: ScoringConfig,
) -> QueueResult:
    del as_of
    leads = list(session.scalars(select(Lead).where(Lead.owner == owner)).all())
    fresh: list[Lead] = []
    follow: list[Lead] = []
    for lead in leads:
        if lead.stage in _EXCLUDED or lead.auto_outreach_blocked:
            continue
        if _confidence(lead) < config.min_confidence:
            continue
        if lead.stage == LeadStage.SCORED:
            fresh.append(lead)
        elif lead.stage in _FOLLOW:
            follow.append(lead)
    fresh = _sort(_one_per_company(fresh))
    follow = _sort(_one_per_company(follow))
    new_taken = fresh[: config.new_customer_cap]
    room = max(config.daily_cap - len(new_taken), 0)
    follow_taken = follow[:room]
    items = (new_taken + follow_taken)[: config.daily_cap]
    eligible = len(fresh) + len(follow)
    truncated = max(eligible - len(items), 0)
    if truncated:
        _log.info(
            "queue_truncated",
            lead_id="",
            trace_id=current_trace_id(),
            owner=owner,
            truncated_count=truncated,
            daily_cap=config.daily_cap,
        )
    return QueueResult(items=items, truncated_count=truncated)
