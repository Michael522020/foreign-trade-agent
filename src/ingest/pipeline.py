"""入库。抑制检查发生在写 Company 之前。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

import structlog
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.ingest.email_verify import verify_email
from src.ingest.records import IngestReport, NormalizedRecord, QuarantineRow, ShipmentDraft
from src.ingest.tables import CustomsShipment, IngestDrop, IngestLedger, MergeCandidate, QuarantineItem
from src.logging_config import current_trace_id
from src.models.base import new_id, utcnow
from src.models.compliance import Suppression
from src.models.enums import LeadStage
from src.models.parties import Company, Contact, Lead

_log = structlog.get_logger("ingest")


def ingest_path(
    session: Session,
    adapter: object,
    path: object,
    *,
    mx_lookup: Callable[[str], bool] | None = None,
    dry_run: bool = False,
) -> IngestReport:
    parse = getattr(adapter, "parse", None)
    normalize = getattr(adapter, "normalize", None)
    source_name = getattr(adapter, "source_name", None)
    if not callable(parse) or not callable(normalize) or not isinstance(source_name, str):
        raise TypeError("adapter 必须提供 source_name、parse、normalize")
    rows = parse(path)
    if not isinstance(rows, list):
        raise TypeError("parse 必须返回列表")
    report = IngestReport(parsed=len(rows))
    for raw in rows:
        try:
            normalized = normalize(raw)
        except QuarantineRow as exc:
            report.quarantined += 1
            _quarantine(session, source_name, raw, exc.reason)
            continue
        if not isinstance(normalized, NormalizedRecord):
            raise TypeError("normalize 必须返回 NormalizedRecord")
        if normalized.email:
            verdict = verify_email(normalized.email, mx_lookup)
            normalized.email_status = verdict.status
            normalized.is_role_based = verdict.is_role_based
        if _is_suppressed(session, normalized):
            report.suppressed += 1
            session.add(
                IngestDrop(
                    id=new_id(),
                    source=source_name,
                    idempotency_key=normalized.idempotency_key,
                    drop_reason="SUPPRESSED",
                    detail=normalized.email or normalized.domain or normalized.phone or "",
                    created_at=utcnow(),
                )
            )
            _log.info(
                "ingest_dropped",
                lead_id="",
                trace_id=current_trace_id(),
                drop_reason="SUPPRESSED",
                source=source_name,
            )
            continue
        report.passed += 1
        if _seen(session, normalized.idempotency_key):
            report.deduped += 1
            continue
        _store(session, normalized, report)
    session.flush()
    if dry_run:
        session.rollback()
    return report


def _quarantine(session: Session, source: str, raw: object, reason: str) -> None:
    row_number = int(getattr(raw, "row_number", 0))
    payload = getattr(raw, "values", {})
    if not isinstance(payload, dict):
        payload = {}
    session.add(
        QuarantineItem(
            id=new_id(),
            source=source,
            row_number=row_number,
            reason=reason,
            payload={str(key): str(value) for key, value in payload.items()},
            created_at=utcnow(),
        )
    )
    _log.info(
        "ingest_quarantine",
        lead_id="",
        trace_id=current_trace_id(),
        source=source,
        row_number=row_number,
        reason=reason,
    )


def _is_suppressed(session: Session, rec: NormalizedRecord) -> bool:
    clauses = []
    if rec.email:
        clauses.append(Suppression.email == rec.email.lower())
    if rec.phone:
        clauses.append(Suppression.phone == rec.phone)
    if rec.domain:
        clauses.append(Suppression.domain == rec.domain.lower())
    if not clauses:
        return False
    found = session.scalar(select(Suppression.id).where(or_(*clauses)).limit(1))
    return found is not None


def _seen(session: Session, key: str) -> bool:
    found = session.scalar(select(IngestLedger.id).where(IngestLedger.idempotency_key == key))
    return found is not None


def _store(session: Session, rec: NormalizedRecord, report: IngestReport) -> None:
    company = _match_company(session, rec)
    if company is None:
        weak = _match_weak(session, rec)
        company = _new_company(rec)
        session.add(company)
        session.flush()
        report.companies_created += 1
        if weak is not None:
            session.add(
                MergeCandidate(
                    id=new_id(),
                    company_id=company.id,
                    other_company_id=weak.id,
                    weak_key=rec.email or rec.phone_e164 or rec.phone or "",
                    status="PENDING",
                    created_at=utcnow(),
                )
            )
    else:
        report.deduped += 1
    _merge_company(company, rec)
    contact = _match_contact(session, company.id, rec)
    if contact is None:
        contact = _new_contact(company.id, rec)
        session.add(contact)
        session.flush()
    lead = session.scalar(
        select(Lead).where(Lead.company_id == company.id, Lead.contact_id == contact.id)
    )
    if lead is None:
        lead = Lead(
            id=new_id(),
            company_id=company.id,
            contact_id=contact.id,
            product_interest=rec.product_interest,
            stage=LeadStage.RAW,
            auto_outreach_blocked=bool(rec.hold_note),
            hold_note=rec.hold_note,
            created_at=utcnow(),
            updated_at=utcnow(),
            contact=contact,
        )
        session.add(lead)
        session.flush()
    elif rec.hold_note:
        lead.auto_outreach_blocked = True
        lead.hold_note = rec.hold_note
    if rec.shipment is not None:
        session.add(_shipment(company.id, rec.shipment))
        session.flush()
        _refresh_trade_stats(session, company)
    session.add(
        IngestLedger(
            id=new_id(),
            source=rec.source,
            idempotency_key=rec.idempotency_key,
            company_id=company.id,
            created_at=utcnow(),
        )
    )
    _log.info(
        "ingest_stored",
        lead_id=lead.id,
        trace_id=current_trace_id(),
        source=rec.source,
        company_id=company.id,
    )


def _match_company(session: Session, rec: NormalizedRecord) -> Company | None:
    if rec.domain:
        found = session.scalar(select(Company).where(Company.normalized_domain == rec.domain))
        if found is not None:
            return found
    return session.scalar(
        select(Company).where(
            Company.normalized_name == rec.normalized_name,
            Company.country == rec.country,
        )
    )


def _match_weak(session: Session, rec: NormalizedRecord) -> Company | None:
    if rec.email:
        contact = session.scalar(select(Contact).where(Contact.email == rec.email))
        if contact is not None:
            return session.get(Company, contact.company_id)
    if rec.phone_e164:
        contact = session.scalar(select(Contact).where(Contact.phone_e164 == rec.phone_e164))
        if contact is not None:
            return session.get(Company, contact.company_id)
    return None


def _new_company(rec: NormalizedRecord) -> Company:
    return Company(
        id=new_id(),
        name=rec.company_name,
        country=rec.country,
        domain=rec.domain,
        normalized_name=rec.normalized_name,
        normalized_domain=rec.domain,
        buyer_type=rec.buyer_type,
        source=rec.source,
        source_url=rec.source_url,
        collected_at=rec.collected_at,
        hs_codes=list(rec.hs_codes),
        import_count=0,
        data_usage_scope=rec.data_usage_scope.value,
        source_signals=dict(rec.source_signals) or None,
    )


def _merge_company(company: Company, rec: NormalizedRecord) -> None:
    codes = list(company.hs_codes or [])
    for code in rec.hs_codes:
        if code not in codes:
            codes.append(code)
    company.hs_codes = codes
    if rec.domain and not company.normalized_domain:
        company.domain = rec.domain
        company.normalized_domain = rec.domain
    signals = dict(company.source_signals or {})
    signals.update(rec.source_signals)
    company.source_signals = signals or None
    if rec.collected_at < company.collected_at:
        company.collected_at = rec.collected_at


def _match_contact(session: Session, company_id: str, rec: NormalizedRecord) -> Contact | None:
    if rec.email:
        return session.scalar(
            select(Contact).where(Contact.company_id == company_id, Contact.email == rec.email)
        )
    if rec.phone:
        return session.scalar(
            select(Contact).where(Contact.company_id == company_id, Contact.phone == rec.phone)
        )
    return session.scalar(
        select(Contact).where(Contact.company_id == company_id, Contact.full_name == rec.contact_name)
    )


def _new_contact(company_id: str, rec: NormalizedRecord) -> Contact:
    return Contact(
        id=new_id(),
        company_id=company_id,
        full_name=rec.contact_name,
        role=rec.role,
        email=rec.email,
        email_status=rec.email_status,
        is_role_based=rec.is_role_based,
        contact_channel=rec.contact_channel,
        phone=rec.phone,
        phone_e164=rec.phone_e164,
        whatsapp_consent=False,
        language=rec.language,
        source=rec.source,
        source_url=rec.source_url,
        collected_at=rec.collected_at,
    )


def _shipment(company_id: str, draft: ShipmentDraft) -> CustomsShipment:
    return CustomsShipment(
        id=new_id(),
        company_id=company_id,
        hs_code=draft.hs_code,
        product_desc=draft.product_desc,
        quantity=draft.quantity,
        quantity_unit=draft.quantity_unit,
        amount_usd=draft.amount_usd,
        ship_date=draft.ship_date,
        supplier_name=draft.supplier_name,
        supplier_country=draft.supplier_country,
        port_of_discharge=draft.port_of_discharge,
        bl_no=draft.bl_no,
    )


def _refresh_trade_stats(session: Session, company: Company) -> None:
    rows: Sequence[CustomsShipment] = session.scalars(
        select(CustomsShipment).where(CustomsShipment.company_id == company.id)
    ).all()
    company.import_count = len(rows)
    if not rows:
        return
    company.last_ship_date = max(row.ship_date for row in rows)
    totals: dict[str, Decimal] = {}
    for row in rows:
        amount = row.amount_usd if row.amount_usd is not None else row.quantity
        totals[row.supplier_name] = totals.get(row.supplier_name, Decimal(0)) + amount
    ordered = sorted(totals.values(), reverse=True)
    grand = sum(ordered, Decimal(0))
    if grand > 0:
        company.supplier_top3_share = sum(ordered[:3], Decimal(0)) / grand
