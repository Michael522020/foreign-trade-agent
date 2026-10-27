"""开发信只在校验通过后落盘。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.errors import ConfigError
from src.models.base import new_id
from src.models.compliance import Interaction
from src.models.enums import (
    BuyerType,
    Channel,
    ContactChannel,
    ContactRole,
    Direction,
    EmailStatus,
    LeadStage,
)
from src.models.parties import Company, Contact, Lead
from src.outreach.compose import compose_body, compose_subject, resolve_language
from src.outreach.draft import draft_daily
from src.outreach.validate import (
    REJECTED_FIRST_TOUCH_LINK,
    REJECTED_TOO_LONG,
    REJECTED_UNAPPROVED_CERT,
    REJECTED_UNAPPROVED_FACT,
    ApprovedFact,
    validate_with_one_compress,
)
from src.scoring.config import load_scoring
from src.scoring.engine import score_lead

AS_OF = datetime(2026, 10, 27, tzinfo=timezone.utc)
_FACTS = [
    ApprovedFact("100", "pcs", "config/product.yaml"),
    ApprovedFact("30", "days", "config/product.yaml"),
]


def test_unapproved_number_link_cert_and_length() -> None:
    subject = "Second source for furniture"
    _, reasons = validate_with_one_compress(
        subject,
        "word " * 130,
        _FACTS,
        first_touch=True,
        cert_allowed=False,
    )
    assert REJECTED_TOO_LONG in reasons
    _, linked = validate_with_one_compress(
        subject,
        ("We can share details at https://example.invalid later. " * 12).strip(),
        _FACTS,
        first_touch=True,
        cert_allowed=False,
    )
    assert REJECTED_FIRST_TOUCH_LINK in linked
    _, certified = validate_with_one_compress(
        subject,
        ("Our goods are CE certified for this category. " * 8).strip(),
        _FACTS,
        first_touch=True,
        cert_allowed=False,
    )
    assert REJECTED_UNAPPROVED_CERT in certified
    _, extra = validate_with_one_compress(
        subject,
        ("The order would be 500 pcs and that is not approved. " * 8).strip(),
        _FACTS,
        first_touch=True,
        cert_allowed=True,
    )
    assert any(reason.startswith(REJECTED_UNAPPROVED_FACT) for reason in extra)


def test_portuguese_is_not_an_english_template() -> None:
    config = load_scoring()
    body = compose_body("pt", config, "Ana")
    assert "escrevo" in body
    assert "quantidade" in body
    assert not body.startswith("Hello")
    subject = compose_subject("pt", config)
    body, reasons = validate_with_one_compress(
        subject, body, _FACTS, first_touch=True, cert_allowed=False
    )
    assert reasons == []
    assert 75 <= len(body.split()) <= 125


def test_unsupported_language_fails_closed() -> None:
    try:
        resolve_language("ja")
    except ConfigError as exc:
        assert "ja" in str(exc)
    else:
        raise AssertionError("不支持的语言必须拒绝")


def _ready_lead(session: Session, role: ContactRole, language: str) -> Lead:
    company = Company(
        id=new_id(),
        name="SYN-OUTREACH-1",
        country="DE",
        buyer_type=BuyerType.IMPORTER,
        source="synthetic",
        source_url="fixture://outreach",
        collected_at=AS_OF,
        hs_codes=["940360"],
        import_count=4,
        last_ship_date=AS_OF - timedelta(days=20),
        supplier_top3_share=Decimal("0.40"),
    )
    session.add(company)
    session.flush()
    contact = Contact(
        id=new_id(),
        company_id=company.id,
        full_name="SYN-BUYER",
        role=role,
        email="buyer@syn-outreach.example",
        email_status=EmailStatus.VERIFIED,
        contact_channel=ContactChannel.EMAIL,
        source="synthetic",
        source_url=company.source_url,
        collected_at=AS_OF,
        language=language,
    )
    session.add(contact)
    session.flush()
    lead = Lead(
        id=new_id(),
        company_id=company.id,
        contact_id=contact.id,
        stage=LeadStage.RAW,
        owner="sales01",
        created_at=AS_OF,
        updated_at=AS_OF,
        contact=contact,
    )
    session.add(lead)
    session.flush()
    score_lead(session, lead, load_scoring(), AS_OF)
    return lead


def test_unknown_role_is_skipped(session: Session, tmp_path: Path) -> None:
    lead = _ready_lead(session, ContactRole.UNKNOWN, "en")
    report = draft_daily(session, "sales01", AS_OF, load_scoring(), tmp_path, dry_run=True)
    assert report.written == []
    assert report.skipped[0]["lead_id"] == lead.id
    assert report.skipped[0]["skip_reason"] == "角色不明"


def test_inbound_reply_stops_the_sequence(session: Session, tmp_path: Path) -> None:
    lead = _ready_lead(session, ContactRole.PURCHASING_MANAGER, "pt")
    session.add(
        Interaction(
            id=new_id(),
            lead_id=lead.id,
            channel=Channel.EMAIL,
            direction=Direction.INBOUND,
            occurred_at=AS_OF,
            content_ref="fixture://reply",
        )
    )
    session.flush()
    report = draft_daily(session, "sales01", AS_OF, load_scoring(), tmp_path, dry_run=False)
    assert report.written == []
    assert any("已有回复" in item["skip_reason"] for item in report.skipped)
    assert list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob(f"{lead.id}.json"))


def test_accepted_draft_stays_pending_review(session: Session, tmp_path: Path) -> None:
    lead = _ready_lead(session, ContactRole.PURCHASING_MANAGER, "de")
    report = draft_daily(session, "sales01", AS_OF, load_scoring(), tmp_path, dry_run=False)
    assert report.written == [lead.id]
    path = tmp_path / "2026-10-27" / f"{lead.id}.json"
    payload = path.read_text(encoding="utf-8")
    assert '"status": "pending_review"' in payload
    assert "why_this_works_zh" in payload
    stored = session.scalar(select(Lead).where(Lead.id == lead.id))
    assert stored is not None
    assert stored.stage == LeadStage.SCORED
