"""发送前闸门。任何一项失败就拦截，检查抛错也拦截。这里不发送。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from src.compliance.config import GateConfig
from src.logging_config import current_trace_id
from src.models.base import new_id, utcnow
from src.models.compliance import ComplianceAudit, Interaction, Suppression
from src.models.enums import (
    ComplianceDecision,
    Direction,
    EmailStatus,
    InteractionOutcome,
    SuppressionReason,
)
from src.models.parties import Lead
from src.outreach.validate import ApprovedFact, body_has_link, find_unapproved_facts

_log = structlog.get_logger("send_gate")
GATE_VERSION = "2026-10-27"
_OPT_OUT = frozenset({SuppressionReason.UNSUBSCRIBED, SuppressionReason.COMPLAINED})


@dataclass(frozen=True)
class SendTask:
    task_id: str
    lead_id: str
    body: str
    is_first_touch: bool
    human_approved: bool


@dataclass(frozen=True)
class SendGateResult:
    allowed: bool
    blocked_reasons: list[str]
    warnings: list[str] = field(default_factory=list)


def _stop(code: str, warnings: list[str]) -> SendGateResult:
    return SendGateResult(allowed=False, blocked_reasons=[code], warnings=list(warnings))


def _window_start(now: datetime) -> datetime:
    return now - timedelta(days=7)


def _count(session: Session, statement: Select[int]) -> int:
    value = session.scalar(statement)
    if value is None:
        return 0
    return int(value)


def _suppression_hit(session: Session, lead: Lead) -> Suppression | None:
    contact = lead.contact
    company = lead.company
    if contact is None or company is None:
        return None
    clauses = []
    if contact.email:
        clauses.append(func.lower(Suppression.email) == contact.email.lower())
    if contact.phone:
        clauses.append(Suppression.phone == contact.phone)
    domain = (company.normalized_domain or company.domain or "").lower()
    if domain:
        clauses.append(Suppression.domain == domain)
    if not clauses:
        return None
    return session.scalars(select(Suppression).where(or_(*clauses)).limit(1)).first()


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal(0) if numerator == 0 else Decimal(1)
    return Decimal(numerator) / Decimal(denominator)


def _collect(session: Session, task: SendTask, ctx: GateConfig, facts: list[ApprovedFact], now: datetime) -> SendGateResult:
    lead = session.get(Lead, task.lead_id)
    if lead is None or lead.contact is None or lead.company is None:
        return _stop("LEAD_NOT_FOUND", [])
    contact = lead.contact
    company = lead.company
    warnings: list[str] = []
    hit = _suppression_hit(session, lead)
    if hit is not None:
        if hit.reason in _OPT_OUT:
            return _stop("PREVIOUSLY_OPTED_OUT", warnings)
        return _stop("IN_SUPPRESSION_LIST", warnings)
    opted = session.scalar(
        select(Interaction.id).where(
            Interaction.lead_id == lead.id,
            Interaction.outcome == InteractionOutcome.UNSUBSCRIBED.value,
        )
    )
    if opted is not None:
        return _stop("PREVIOUSLY_OPTED_OUT", warnings)
    if contact.email_status != EmailStatus.VERIFIED:
        return _stop("EMAIL_NOT_VERIFIED", warnings)
    domain = ""
    if contact.email and "@" in contact.email:
        domain = contact.email.split("@", 1)[1].lower()
    if domain in ctx.freemail_domains:
        warnings.append("FREEMAIL_ADDRESS")
    start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    sent_today = _count(
        session,
        select(func.count()).select_from(Interaction).where(
            Interaction.direction == Direction.OUTBOUND,
            Interaction.occurred_at >= start,
        ),
    )
    if sent_today >= ctx.daily_cap:
        return _stop("DAILY_QUOTA_EXCEEDED", warnings)
    if not ctx.auth_ready:
        return _stop("AUTH_NOT_READY", warnings)
    since = _window_start(now)
    sends = _count(
        session,
        select(func.count()).select_from(Interaction).where(
            Interaction.direction == Direction.OUTBOUND,
            Interaction.occurred_at >= since,
        ),
    )
    complaints = _count(
        session,
        select(func.count()).select_from(Suppression).where(
            Suppression.reason == SuppressionReason.COMPLAINED,
            Suppression.created_at >= since,
        ),
    )
    complaint_rate = _rate(complaints, sends)
    if complaint_rate >= ctx.complaint_block:
        return _stop("COMPLAINT_RATE_HIGH", warnings)
    if complaint_rate >= ctx.complaint_warn:
        warnings.append("COMPLAINT_RATE_HIGH")
    bounces = _count(
        session,
        select(func.count()).select_from(Suppression).where(
            Suppression.reason == SuppressionReason.HARD_BOUNCE,
            Suppression.created_at >= since,
        ),
    )
    if _rate(bounces, sends) >= ctx.bounce_block:
        return _stop("BOUNCE_RATE_HIGH", warnings)
    country = company.country.upper()
    if country in ctx.blocked_countries or (
        country in ctx.lia_required_countries and country not in ctx.lia_recorded_countries
    ):
        return _stop("JURISDICTION_RESTRICTED", warnings)
    if not ctx.sanction_list_loaded:
        return _stop("SANCTION_LIST_NOT_LOADED", warnings)
    if company.name.strip().casefold() in ctx.sanction_names:
        return _stop("SANCTIONED_ENTITY", warnings)
    if task.is_first_touch and body_has_link(task.body):
        warnings.append("FIRST_TOUCH_HAS_LINK")
    unapproved = find_unapproved_facts(task.body, facts)
    if unapproved:
        return _stop(f"UNAPPROVED_COMMERCIAL_TERM:{unapproved[0]}", warnings)
    if not task.human_approved:
        return _stop("NO_HUMAN_APPROVAL", warnings)
    return SendGateResult(allowed=True, blocked_reasons=[], warnings=warnings)


def _audit(session: Session, task: SendTask, ctx: GateConfig, result: SendGateResult) -> None:
    session.add(
        ComplianceAudit(
            id=new_id(),
            task_id=task.task_id,
            lead_id=task.lead_id,
            decision=ComplianceDecision.ALLOWED if result.allowed else ComplianceDecision.BLOCKED,
            blocked_reasons=list(result.blocked_reasons),
            gate_version=GATE_VERSION,
            config_hash=ctx.config_hash,
            checked_at=utcnow(),
        )
    )
    session.flush()


def send_gate(
    session: Session,
    task: SendTask,
    ctx: GateConfig,
    facts: list[ApprovedFact],
    now: datetime,
) -> SendGateResult:
    try:
        result = _collect(session, task, ctx, facts, now)
    except Exception as exc:
        _log.error(
            "gate_check_failed",
            lead_id=task.lead_id,
            trace_id=current_trace_id(),
            error=str(exc),
        )
        result = SendGateResult(allowed=False, blocked_reasons=["GATE_CHECK_ERROR"], warnings=[])
    if result.blocked_reasons == ["LEAD_NOT_FOUND"]:
        _log.error(
            "gate_audit_skipped",
            lead_id=task.lead_id,
            trace_id=current_trace_id(),
            error="线索不存在，无法写入审计",
        )
        return result
    try:
        _audit(session, task, ctx, result)
    except Exception as exc:
        _log.error(
            "gate_audit_failed",
            lead_id=task.lead_id,
            trace_id=current_trace_id(),
            error=str(exc),
        )
        return SendGateResult(allowed=False, blocked_reasons=["GATE_CHECK_ERROR"], warnings=[])
    _log.info(
        "gate_checked",
        lead_id=task.lead_id,
        trace_id=current_trace_id(),
        decision="allowed" if result.allowed else "blocked",
        blocked_reasons=result.blocked_reasons,
    )
    return result
