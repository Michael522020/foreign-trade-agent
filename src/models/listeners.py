"""ORM 入口校验。绕过 transition() 直接改状态，这里也会拒绝。"""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy import event, inspect
from sqlalchemy.orm import Mapper

from src.errors import ConstraintViolation
from src.models.base import new_id, utcnow
from src.models.catalog import Certification, Product
from src.models.commercial import Inquiry, Quotation
from src.models.compliance import Interaction, Suppression
from src.models.cost import parse_cost, snapshot_cost
from src.models.enums import InquiryStatus, InteractionOutcome, LeadStage, QuotationStatus
from src.models.parties import Company, Contact, Lead
from src.models.schemas import CompanyIn, ContactIn, QuotationIn, SuppressionIn, reject_validation
from src.models.state_machine import (
    assert_entering_queued,
    assert_initial_state,
    assert_inquiry_status_change,
    assert_lead_stage_change,
    assert_quotation_status_change,
    assert_score_for_stage,
)

_E = TypeVar("_E", bound=Enum)
_UNCHANGED = object()
_REGISTERED = False


def _enum(enum_cls: type[_E], raw: object, field: str) -> _E:
    if isinstance(raw, enum_cls):
        return raw
    if isinstance(raw, str):
        try:
            return enum_cls(raw)
        except ValueError as exc:
            raise ConstraintViolation(field, "未知状态", value=raw) from exc
    raise ConstraintViolation(field, "状态缺失", value=raw)


def _old(target: object, name: str) -> object:
    inspected = inspect(target)
    if inspected is None or not hasattr(inspected, "attrs"):
        record_id = getattr(target, "id", None)
        raise ConstraintViolation(
            name,
            "无法检查对象状态，已拒绝写入",
            record_id=None if record_id is None else str(record_id),
        )
    history = inspected.attrs[name].history
    if not history.has_changes():
        return _UNCHANGED
    if not history.deleted:
        record_id = getattr(target, "id", None)
        raise ConstraintViolation(
            name,
            "无法读取变更前的状态，已拒绝写入",
            record_id=None if record_id is None else str(record_id),
        )
    return history.deleted[0]


def _require(value: object, field: str, record_id: str | None) -> None:
    if value is None or value == "":
        raise ConstraintViolation(field, "不能为空", record_id=record_id)


def _lead_insert(mapper: Mapper[Lead], connection: object, target: Lead) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    now = utcnow()
    if target.created_at is None:
        target.created_at = now
    if target.updated_at is None:
        target.updated_at = target.created_at
    if target.stage is None:
        target.stage = LeadStage.RAW
    assert_initial_state("lead", target.stage)
    assert_score_for_stage(target.stage, target.icp_score, target.id)
    _require(target.company_id, "company_id", target.id)
    _require(target.contact_id, "contact_id", target.id)


def _lead_update(mapper: Mapper[Lead], connection: object, target: Lead) -> None:
    del mapper, connection
    previous = _old(target, "stage")
    if previous is not _UNCHANGED:
        old_stage = _enum(LeadStage, previous, "stage")
        new_stage = _enum(LeadStage, target.stage, "stage")
        assert_lead_stage_change(old_stage, new_stage)
        assert_entering_queued(target, new_stage, old_stage)
    assert_score_for_stage(target.stage, target.icp_score, target.id)
    target.updated_at = utcnow()


def _company_write(mapper: Mapper[Company], connection: object, target: Company) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    try:
        parsed = CompanyIn.model_validate(
            {
                "name": target.name,
                "country": target.country,
                "buyer_type": target.buyer_type,
                "source": target.source,
                "source_url": target.source_url,
                "collected_at": target.collected_at,
                "hs_codes": list(target.hs_codes or []),
                "domain": target.domain,
                "website": target.website,
                "employee_band": target.employee_band,
                "annual_revenue_band": target.annual_revenue_band,
            }
        )
    except ValidationError as exc:
        reject_validation(exc, record_id=target.id)
    target.country = parsed.country
    target.domain = parsed.domain
    target.website = parsed.website
    target.hs_codes = parsed.hs_codes
    target.employee_band = None if parsed.employee_band is None else parsed.employee_band.value
    target.annual_revenue_band = (
        None if parsed.annual_revenue_band is None else parsed.annual_revenue_band.value
    )


def _contact_write(mapper: Mapper[Contact], connection: object, target: Contact) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    if target.whatsapp_consent is None:
        target.whatsapp_consent = False
    try:
        parsed = ContactIn.model_validate(
            {
                "company_id": target.company_id,
                "full_name": target.full_name,
                "email": target.email,
                "email_status": target.email_status,
                "contact_channel": None if target.contact_channel is None else target.contact_channel.value,
                "source": target.source,
                "source_url": target.source_url,
                "collected_at": target.collected_at,
                "role": target.role,
                "phone": target.phone,
                "phone_e164": target.phone_e164,
                "whatsapp_consent": target.whatsapp_consent,
                "linkedin_url": target.linkedin_url,
                "language": target.language,
                "timezone": target.timezone,
                "last_contacted_at": target.last_contacted_at,
            }
        )
    except ValidationError as exc:
        reject_validation(exc, record_id=target.id)
    target.email = None if parsed.email is None else str(parsed.email)
    target.phone_e164 = parsed.phone_e164
    target.language = parsed.language
    target.timezone = parsed.timezone
    target.linkedin_url = parsed.linkedin_url
    target.whatsapp_consent = parsed.whatsapp_consent


def _quotation_write(mapper: Mapper[Quotation], connection: object, target: Quotation) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    if target.created_at is None:
        target.created_at = utcnow()
    if target.status is None:
        target.status = QuotationStatus.DRAFT
    raw_cost = target.cost_breakdown
    cost_input: object = parse_cost(raw_cost) if isinstance(raw_cost, dict) else raw_cost
    try:
        parsed = QuotationIn.model_validate(
            {
                "inquiry_id": target.inquiry_id,
                "customer_id": target.customer_id,
                "product_sku": target.product_sku,
                "quantity": target.quantity,
                "incoterm": target.incoterm,
                "destination_port": target.destination_port,
                "payment_terms": target.payment_terms,
                "unit_price": target.unit_price,
                "currency": target.currency,
                "cost_breakdown": cost_input,
                "fx_rate": target.fx_rate,
                "fx_rate_source": target.fx_rate_source,
                "fx_rate_at": target.fx_rate_at,
                "valid_until": target.valid_until,
                "created_at": target.created_at,
            }
        )
    except ValidationError as exc:
        reject_validation(exc, record_id=target.id)
    target.destination_port = parsed.destination_port
    target.currency = parsed.currency
    target.cost_breakdown = snapshot_cost(parsed.cost_breakdown)


def _quotation_insert(mapper: Mapper[Quotation], connection: object, target: Quotation) -> None:
    _quotation_write(mapper, connection, target)
    assert_initial_state("quotation", target.status)


def _quotation_update(mapper: Mapper[Quotation], connection: object, target: Quotation) -> None:
    _quotation_write(mapper, connection, target)
    previous = _old(target, "status")
    if previous is _UNCHANGED:
        return
    assert_quotation_status_change(
        _enum(QuotationStatus, previous, "status"),
        _enum(QuotationStatus, target.status, "status"),
        target.payment_terms,
    )


def _inquiry_fields(target: Inquiry) -> None:
    _require(target.lead_id, "lead_id", target.id)
    _require(target.raw_text, "raw_text", target.id)
    _require(target.channel, "channel", target.id)
    _require(target.inquiry_type, "inquiry_type", target.id)
    _require(target.received_at, "received_at", target.id)


def _inquiry_insert(mapper: Mapper[Inquiry], connection: object, target: Inquiry) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    if target.status is None:
        target.status = InquiryStatus.NEW
    if target.missing_info is None:
        target.missing_info = []
    _inquiry_fields(target)
    assert_initial_state("inquiry", target.status)


def _inquiry_update(mapper: Mapper[Inquiry], connection: object, target: Inquiry) -> None:
    del mapper, connection
    _inquiry_fields(target)
    previous = _old(target, "status")
    if previous is _UNCHANGED:
        return
    assert_inquiry_status_change(
        _enum(InquiryStatus, previous, "status"),
        _enum(InquiryStatus, target.status, "status"),
    )


def _cert_write(mapper: Mapper[Certification], connection: object, target: Certification) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    _require(target.cert_no, "cert_no", target.id)
    _require(target.document_ref, "document_ref", target.id)
    if target.valid_from is None or target.valid_to is None:
        raise ConstraintViolation("valid_to", "认证有效期不能为空", record_id=target.id)
    if target.valid_to < target.valid_from:
        raise ConstraintViolation(
            "valid_to",
            "认证有效期结束不能早于开始",
            value=target.valid_to.isoformat(),
            record_id=target.id,
        )


def _product_write(mapper: Mapper[Product], connection: object, target: Product) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    _require(target.sku, "sku", target.id)
    _require(target.name_en, "name_en", target.id)
    if target.hs_code is None or not str(target.hs_code).isdigit():
        raise ConstraintViolation(
            "hs_code",
            "HS 编码必须是数字",
            value=target.hs_code,
            record_id=target.id,
        )
    if target.moq_default is not None and target.moq_default <= 0:
        raise ConstraintViolation(
            "moq_default",
            "默认起订量必须大于 0",
            value=target.moq_default,
            record_id=target.id,
        )


def _suppression_write(mapper: Mapper[Suppression], connection: object, target: Suppression) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    if target.created_at is None:
        target.created_at = utcnow()
    try:
        parsed = SuppressionIn.model_validate(
            {
                "email": target.email,
                "phone": target.phone,
                "domain": target.domain,
                "reason": target.reason,
                "scope": target.scope,
                "created_at": target.created_at,
            }
        )
    except ValidationError as exc:
        reject_validation(exc, record_id=target.id)
    target.email = None if parsed.email is None else str(parsed.email)
    target.domain = parsed.domain


def _interaction_write(mapper: Mapper[Interaction], connection: object, target: Interaction) -> None:
    del mapper, connection
    if not target.id:
        target.id = new_id()
    if target.outcome is None or target.outcome == "":
        target.outcome = None
        return
    raw = target.outcome.value if isinstance(target.outcome, InteractionOutcome) else target.outcome
    try:
        parsed = InteractionOutcome(raw)
    except ValueError as exc:
        raise ConstraintViolation(
            "outcome",
            "交互结果不在约定取值内",
            value=raw,
            record_id=target.id,
        ) from exc
    target.outcome = parsed.value


def register_listeners() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Lead, "before_insert", _lead_insert)
    event.listen(Lead, "before_update", _lead_update)
    event.listen(Company, "before_insert", _company_write)
    event.listen(Company, "before_update", _company_write)
    event.listen(Contact, "before_insert", _contact_write)
    event.listen(Contact, "before_update", _contact_write)
    event.listen(Quotation, "before_insert", _quotation_insert)
    event.listen(Quotation, "before_update", _quotation_update)
    event.listen(Inquiry, "before_insert", _inquiry_insert)
    event.listen(Inquiry, "before_update", _inquiry_update)
    event.listen(Certification, "before_insert", _cert_write)
    event.listen(Certification, "before_update", _cert_write)
    event.listen(Product, "before_insert", _product_write)
    event.listen(Product, "before_update", _product_write)
    event.listen(Suppression, "before_insert", _suppression_write)
    event.listen(Suppression, "before_update", _suppression_write)
    event.listen(Interaction, "before_insert", _interaction_write)
    event.listen(Interaction, "before_update", _interaction_write)
    _REGISTERED = True
