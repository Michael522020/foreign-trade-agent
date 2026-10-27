"""线索、询盘、报价的状态机。转移表只维护在本文件。"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Generic, TypeVar

import structlog

from src.errors import ConstraintViolation, InvalidTransition
from src.logging_config import current_trace_id
from src.models.enums import (
    HIGH_RISK_PAYMENT_TERMS,
    INQUIRY_TERMINALS,
    LEAD_TERMINALS,
    QUOTATION_TERMINALS,
    ContactRole,
    EmailStatus,
    InquiryStatus,
    LeadStage,
    PaymentTerms,
    QuotationStatus,
)

_log = structlog.get_logger("state_machine")
_E = TypeVar("_E", bound=Enum)
_SCORE_OPTIONAL = frozenset({LeadStage.RAW, LeadStage.ENRICHED, LeadStage.SUPPRESSED})


class LeadEvent(str, Enum):
    ENRICH = "ENRICH"
    SCORE = "SCORE"
    QUEUE = "QUEUE"
    CONTACT = "CONTACT"
    MARK_REPLIED = "MARK_REPLIED"
    MARK_BOUNCED = "MARK_BOUNCED"
    MARK_NOT_INTERESTED = "MARK_NOT_INTERESTED"
    NURTURE = "NURTURE"
    CONVERT_INQUIRY = "CONVERT_INQUIRY"
    START_QUOTING = "START_QUOTING"
    START_SAMPLE = "START_SAMPLE"
    START_NEGOTIATING = "START_NEGOTIATING"
    WIN = "WIN"
    LOSE = "LOSE"
    SUPPRESS = "SUPPRESS"


class InquiryEvent(str, Enum):
    TRIAGE = "TRIAGE"
    REQUEST_INFO = "REQUEST_INFO"
    ARCHIVE = "ARCHIVE"
    MARK_QUOTED = "MARK_QUOTED"
    SEND_SAMPLE = "SEND_SAMPLE"
    CONFIRM_ORDER = "CONFIRM_ORDER"
    CLOSE = "CLOSE"


class QuotationEvent(str, Enum):
    SUBMIT_REVIEW = "SUBMIT_REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SEND = "SEND"
    ACCEPT = "ACCEPT"
    EXPIRE = "EXPIRE"


class _Edge(Generic[_E]):
    def __init__(self, sources: frozenset[_E], target: _E) -> None:
        self.sources = sources
        self.target = target


def _edge(sources: frozenset[_E], target: _E) -> _Edge[_E]:
    return _Edge(sources, target)


def _lead_table() -> dict[LeadEvent, _Edge[LeadStage]]:
    active = frozenset(stage for stage in LeadStage if stage not in LEAD_TERMINALS)
    return {
        LeadEvent.ENRICH: _edge(frozenset({LeadStage.RAW}), LeadStage.ENRICHED),
        LeadEvent.SCORE: _edge(frozenset({LeadStage.ENRICHED}), LeadStage.SCORED),
        LeadEvent.QUEUE: _edge(frozenset({LeadStage.SCORED}), LeadStage.QUEUED),
        LeadEvent.CONTACT: _edge(frozenset({LeadStage.QUEUED}), LeadStage.CONTACTED),
        LeadEvent.MARK_REPLIED: _edge(frozenset({LeadStage.CONTACTED}), LeadStage.REPLIED),
        LeadEvent.MARK_BOUNCED: _edge(frozenset({LeadStage.CONTACTED}), LeadStage.BOUNCED),
        LeadEvent.MARK_NOT_INTERESTED: _edge(frozenset({LeadStage.REPLIED}), LeadStage.NOT_INTERESTED),
        LeadEvent.NURTURE: _edge(frozenset({LeadStage.REPLIED}), LeadStage.NURTURE),
        LeadEvent.CONVERT_INQUIRY: _edge(frozenset({LeadStage.REPLIED}), LeadStage.INQUIRY),
        LeadEvent.START_QUOTING: _edge(frozenset({LeadStage.INQUIRY}), LeadStage.QUOTING),
        LeadEvent.START_SAMPLE: _edge(frozenset({LeadStage.QUOTING}), LeadStage.SAMPLE),
        LeadEvent.START_NEGOTIATING: _edge(frozenset({LeadStage.SAMPLE}), LeadStage.NEGOTIATING),
        LeadEvent.WIN: _edge(frozenset({LeadStage.NEGOTIATING}), LeadStage.WON),
        LeadEvent.LOSE: _edge(frozenset({LeadStage.NEGOTIATING}), LeadStage.LOST),
        LeadEvent.SUPPRESS: _edge(active, LeadStage.SUPPRESSED),
    }


def _inquiry_table() -> dict[InquiryEvent, _Edge[InquiryStatus]]:
    return {
        InquiryEvent.TRIAGE: _edge(frozenset({InquiryStatus.NEW}), InquiryStatus.TRIAGED),
        InquiryEvent.REQUEST_INFO: _edge(frozenset({InquiryStatus.TRIAGED}), InquiryStatus.NEEDS_INFO),
        InquiryEvent.ARCHIVE: _edge(frozenset({InquiryStatus.TRIAGED}), InquiryStatus.ARCHIVED),
        InquiryEvent.MARK_QUOTED: _edge(frozenset({InquiryStatus.NEEDS_INFO}), InquiryStatus.QUOTED),
        InquiryEvent.SEND_SAMPLE: _edge(frozenset({InquiryStatus.QUOTED}), InquiryStatus.SAMPLE_SENT),
        InquiryEvent.CONFIRM_ORDER: _edge(frozenset({InquiryStatus.SAMPLE_SENT}), InquiryStatus.ORDER_CONFIRMED),
        InquiryEvent.CLOSE: _edge(frozenset({InquiryStatus.ORDER_CONFIRMED}), InquiryStatus.CLOSED),
    }


def _quotation_table() -> dict[QuotationEvent, _Edge[QuotationStatus]]:
    expirable = frozenset(
        {
            QuotationStatus.DRAFT,
            QuotationStatus.PENDING_REVIEW,
            QuotationStatus.APPROVED,
            QuotationStatus.SENT,
            QuotationStatus.ACCEPTED,
        }
    )
    return {
        QuotationEvent.SUBMIT_REVIEW: _edge(frozenset({QuotationStatus.DRAFT}), QuotationStatus.PENDING_REVIEW),
        QuotationEvent.APPROVE: _edge(frozenset({QuotationStatus.PENDING_REVIEW}), QuotationStatus.APPROVED),
        QuotationEvent.REJECT: _edge(frozenset({QuotationStatus.PENDING_REVIEW}), QuotationStatus.REJECTED),
        QuotationEvent.SEND: _edge(frozenset({QuotationStatus.APPROVED}), QuotationStatus.SENT),
        QuotationEvent.ACCEPT: _edge(frozenset({QuotationStatus.SENT}), QuotationStatus.ACCEPTED),
        QuotationEvent.EXPIRE: _edge(expirable, QuotationStatus.EXPIRED),
    }


_LEAD = _lead_table()
_INQUIRY = _inquiry_table()
_QUOTATION = _quotation_table()


def _allowed(edge: _Edge[_E]) -> list[str]:
    return sorted(item.value for item in edge.sources)


def _check(current: _E, edge: _Edge[_E], terminals: frozenset[_E]) -> None:
    allowed = _allowed(edge)
    if current in terminals or current not in edge.sources:
        raise InvalidTransition(current.value, edge.target.value, allowed)


def _coerce(enum_cls: type[_E], raw: object, field: str) -> _E:
    if isinstance(raw, enum_cls):
        return raw
    if isinstance(raw, str):
        try:
            return enum_cls(raw)
        except ValueError as exc:
            raise ConstraintViolation(field, "未知状态", value=raw) from exc
    raise TypeError(f"{field} 缺失或类型不对：{type(raw).__name__}")


def _record_id(entity: object) -> str | None:
    raw = getattr(entity, "id", None)
    return None if raw is None else str(raw)


def _lead_id_of(entity: object) -> str:
    own = getattr(entity, "lead_id", None)
    if own:
        return str(own)
    if getattr(entity, "stage", None) is not None:
        return str(getattr(entity, "id", "") or "")
    inquiry = getattr(entity, "inquiry", None)
    nested = getattr(inquiry, "lead_id", None) if inquiry is not None else None
    return str(nested or "")


def _emit_transition(entity: object, event: Enum, from_state: str, to_state: str) -> None:
    _log.info(
        "state_transition",
        lead_id=_lead_id_of(entity),
        trace_id=current_trace_id(),
        record_id=_record_id(entity) or "",
        transition_event=event.value,
        from_state=from_state,
        to_state=to_state,
    )


def _require_queueable(entity: object) -> None:
    record_id = _record_id(entity)
    contact = getattr(entity, "contact", None)
    if contact is None:
        raise ConstraintViolation(
            "contact",
            "进入 QUEUED 前必须能读取联系人",
            record_id=record_id,
        )
    raw_status = getattr(contact, "email_status", None)
    if not isinstance(raw_status, EmailStatus):
        raw_status = _coerce(EmailStatus, raw_status, "email_status")
    if raw_status != EmailStatus.VERIFIED:
        raise ConstraintViolation(
            "email_status",
            "未验证的邮箱不能进入 QUEUED",
            value=raw_status.value,
            record_id=record_id,
        )
    role = getattr(contact, "role", None)
    if not isinstance(role, ContactRole) or role == ContactRole.UNKNOWN:
        raise ConstraintViolation(
            "role",
            "联系人角色为空，不能进入 QUEUED",
            value=None if role is None else role.value,
            record_id=record_id,
        )


def assert_score_for_stage(
    stage: LeadStage,
    icp_score: object,
    record_id: str | None,
) -> None:
    if icp_score is not None and (
        isinstance(icp_score, bool)
        or not isinstance(icp_score, int)
        or not 0 <= icp_score <= 100
    ):
        raise ConstraintViolation(
            "icp_score",
            "icp_score 必须在 0 到 100 之间",
            value=icp_score,
            record_id=record_id,
        )
    if stage not in _SCORE_OPTIONAL and icp_score is None:
        raise ConstraintViolation(
            "icp_score",
            f"状态 {stage.value} 必须已有 icp_score",
            record_id=record_id,
        )


def assert_initial_state(kind: str, state: Enum) -> None:
    expected_value = {
        "lead": LeadStage.RAW.value,
        "inquiry": InquiryStatus.NEW.value,
        "quotation": QuotationStatus.DRAFT.value,
    }[kind]
    if state.value != expected_value:
        raise InvalidTransition(
            "（新建）",
            state.value,
            [expected_value],
            reason=f"新建记录的初始状态必须是 {expected_value}，收到 {state.value}",
        )


def _targets(table: Mapping[Any, _Edge[_E]], current: _E) -> frozenset[_E]:
    return frozenset(edge.target for edge in table.values() if current in edge.sources)


def _sources(table: Mapping[Any, _Edge[_E]], target: _E) -> list[str]:
    found: set[str] = set()
    for edge in table.values():
        if edge.target == target:
            found.update(item.value for item in edge.sources)
    return sorted(found)


def assert_lead_stage_change(old: LeadStage, new: LeadStage) -> None:
    if old != new and (new not in _targets(_LEAD, old) or old in LEAD_TERMINALS):
        raise InvalidTransition(old.value, new.value, _sources(_LEAD, new))


def assert_entering_queued(entity: object, new: LeadStage, old: LeadStage) -> None:
    if new == LeadStage.QUEUED and old != LeadStage.QUEUED:
        _require_queueable(entity)


def assert_inquiry_status_change(old: InquiryStatus, new: InquiryStatus) -> None:
    if old != new and (new not in _targets(_INQUIRY, old) or old in INQUIRY_TERMINALS):
        raise InvalidTransition(old.value, new.value, _sources(_INQUIRY, new))


def assert_quotation_status_change(
    old: QuotationStatus,
    new: QuotationStatus,
    payment_terms: PaymentTerms,
) -> None:
    if old == new:
        return
    if payment_terms in HIGH_RISK_PAYMENT_TERMS and new != QuotationStatus.DRAFT:
        raise InvalidTransition(
            old.value,
            new.value,
            [],
            reason=f"付款条件 {payment_terms.value} 不允许报价离开 DRAFT（尝试进入 {new.value}）",
        )
    if new not in _targets(_QUOTATION, old) or old in QUOTATION_TERMINALS:
        raise InvalidTransition(old.value, new.value, _sources(_QUOTATION, new))


def _block_high_risk(current: QuotationStatus, payment: PaymentTerms, target: QuotationStatus) -> None:
    if payment in HIGH_RISK_PAYMENT_TERMS and target != QuotationStatus.DRAFT:
        raise InvalidTransition(
            current.value,
            target.value,
            [],
            reason=f"付款条件 {payment.value} 不允许报价离开 DRAFT（尝试进入 {target.value}）",
        )


def _apply_lead(entity: object, event: LeadEvent) -> None:
    current = _coerce(LeadStage, getattr(entity, "stage", None), "stage")
    edge = _LEAD[event]
    if event in {LeadEvent.MARK_NOT_INTERESTED, LeadEvent.NURTURE} and current != LeadStage.REPLIED:
        raise InvalidTransition(
            current.value,
            edge.target.value,
            [LeadStage.REPLIED.value],
            reason="必须先有回复，才能标为无兴趣或培育",
        )
    _check(current, edge, LEAD_TERMINALS)
    if event == LeadEvent.SCORE:
        assert_score_for_stage(
            LeadStage.SCORED,
            getattr(entity, "icp_score", None),
            _record_id(entity),
        )
    if event == LeadEvent.QUEUE:
        _require_queueable(entity)
    setattr(entity, "stage", edge.target)
    _emit_transition(entity, event, current.value, edge.target.value)


def _apply_inquiry(entity: object, event: InquiryEvent) -> None:
    if not hasattr(entity, "status") or hasattr(entity, "payment_terms"):
        raise TypeError("InquiryEvent 只能用于询盘")
    current = _coerce(InquiryStatus, getattr(entity, "status", None), "status")
    edge = _INQUIRY[event]
    if event == InquiryEvent.MARK_QUOTED and current != InquiryStatus.NEEDS_INFO:
        missing = getattr(entity, "missing_info", None)
        complete = isinstance(missing, list) and len(missing) == 0
        reason = (
            "五要素齐全也必须先进入 NEEDS_INFO，不能直接报价"
            if complete
            else "报价前必须处于 NEEDS_INFO"
        )
        raise InvalidTransition(
            current.value,
            edge.target.value,
            [InquiryStatus.NEEDS_INFO.value],
            reason=reason,
        )
    _check(current, edge, INQUIRY_TERMINALS)
    setattr(entity, "status", edge.target)
    _emit_transition(entity, event, current.value, edge.target.value)


def _apply_quotation(entity: object, event: QuotationEvent) -> None:
    if not hasattr(entity, "payment_terms"):
        raise TypeError("QuotationEvent 只能用于报价")
    current = _coerce(QuotationStatus, getattr(entity, "status", None), "status")
    payment = _coerce(PaymentTerms, getattr(entity, "payment_terms", None), "payment_terms")
    edge = _QUOTATION[event]
    _check(current, edge, QUOTATION_TERMINALS)
    _block_high_risk(current, payment, edge.target)
    setattr(entity, "status", edge.target)
    _emit_transition(entity, event, current.value, edge.target.value)


def transition(entity: object, event: LeadEvent | InquiryEvent | QuotationEvent) -> None:
    """把实体推进一个事件。非法转移抛 InvalidTransition，不修改原状态。"""
    if isinstance(event, LeadEvent):
        _apply_lead(entity, event)
        return
    if isinstance(event, InquiryEvent):
        _apply_inquiry(entity, event)
        return
    if isinstance(event, QuotationEvent):
        _apply_quotation(entity, event)
        return
    raise TypeError(f"未知事件类型：{type(event).__name__}")
