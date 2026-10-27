"""评分缺数据就不进队列。权重和窗口系数来自配置。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import structlog
from sqlalchemy.orm import Session

from src.errors import ConfigError
from src.models.base import new_id
from src.models.enums import BuyerType, ContactChannel, ContactRole, EmailStatus, LeadStage
from src.models.parties import Company, Contact, Lead
from src.scoring.config import load_scoring
from src.scoring.engine import score_lead
from src.scoring.queue import build_daily_queue

AS_OF = datetime(2026, 10, 27, tzinfo=timezone.utc)


def _company(session: Session, index: int) -> Company:
    row = Company(
        id=new_id(),
        name=f"SYN-QUEUE-{index:02d}",
        country="DE",
        buyer_type=BuyerType.IMPORTER,
        source="synthetic",
        source_url=f"fixture://queue/{index}",
        collected_at=AS_OF,
        hs_codes=["940360"],
        import_count=3,
        last_ship_date=AS_OF - timedelta(days=10),
        supplier_top3_share=Decimal("0.20"),
    )
    session.add(row)
    session.flush()
    return row


def _contact(session: Session, company: Company, index: int, role: ContactRole) -> Contact:
    row = Contact(
        id=new_id(),
        company_id=company.id,
        full_name=f"SYN-CONTACT-{index:02d}",
        role=role,
        email=f"buyer{index}@syn-queue-{index}.example",
        email_status=EmailStatus.VERIFIED,
        contact_channel=ContactChannel.EMAIL,
        source="synthetic",
        source_url=company.source_url,
        collected_at=AS_OF,
        language="en",
    )
    session.add(row)
    session.flush()
    return row


def _lead(session: Session, company: Company, contact: Contact) -> Lead:
    row = Lead(
        id=new_id(),
        company_id=company.id,
        contact_id=contact.id,
        stage=LeadStage.RAW,
        owner="sales01",
        created_at=AS_OF,
        updated_at=AS_OF,
        contact=contact,
    )
    session.add(row)
    session.flush()
    return row


def test_weights_must_sum_to_100(tmp_path: Path) -> None:
    text = Path("config/scoring.yaml").read_text(encoding="utf-8")
    broken = text.replace("demand_fit: 30", "demand_fit: 31", 1)
    target = tmp_path / "scoring-broken.yaml"
    target.write_text(broken, encoding="utf-8")
    with pytest.raises(ConfigError, match="100"):
        load_scoring(target, Path("config/product.yaml"))


def test_missing_profile_stays_out_of_the_queue(session: Session) -> None:
    company = Company(
        id=new_id(),
        name="SYN-EMPTY-1",
        country="DE",
        buyer_type=BuyerType.UNKNOWN,
        source="synthetic",
        source_url="fixture://empty",
        collected_at=AS_OF,
        hs_codes=[],
        import_count=0,
    )
    session.add(company)
    session.flush()
    contact = Contact(
        id=new_id(),
        company_id=company.id,
        full_name="SYN-EMPTY-CONTACT",
        role=ContactRole.UNKNOWN,
        email=None,
        email_status=EmailStatus.UNKNOWN,
        contact_channel=ContactChannel.RECORD_ONLY,
        source="synthetic",
        source_url=company.source_url,
        collected_at=AS_OF,
    )
    session.add(contact)
    session.flush()
    lead = _lead(session, company, contact)
    config = load_scoring()
    result = score_lead(session, lead, config, AS_OF)
    assert result.confidence < config.min_confidence
    assert set(result.missing) == {
        "demand_fit",
        "window",
        "switchability",
        "role_access",
        "scale_fit",
        "reachability",
    }
    queued = build_daily_queue(session, "sales01", AS_OF, config)
    assert lead not in queued.items


def test_old_window_and_closed_supply(session: Session) -> None:
    company = _company(session, 1)
    company.last_ship_date = AS_OF - timedelta(days=400)
    company.supplier_top3_share = Decimal("0.85")
    contact = _contact(session, company, 1, ContactRole.PURCHASING_MANAGER)
    lead = _lead(session, company, contact)
    result = score_lead(session, lead, load_scoring(), AS_OF)
    assert result.bands["window"] == Decimal("0.1")
    assert any("供应关系稳定，切入难度高" in reason for reason in result.reasons)


def test_queue_truncates_new_customers(session: Session) -> None:
    config = load_scoring()
    for index in range(40):
        company = _company(session, index + 10)
        contact = _contact(session, company, index + 10, ContactRole.PURCHASING_MANAGER)
        lead = _lead(session, company, contact)
        score_lead(session, lead, config, AS_OF)
    with structlog.testing.capture_logs() as logs:
        result = build_daily_queue(session, "sales01", AS_OF, config)
    assert len(result.items) == config.new_customer_cap
    assert result.truncated_count == 40 - config.new_customer_cap
    assert any(log.get("truncated_count") == result.truncated_count for log in logs)
    widened = replace(config, daily_cap=30, new_customer_cap=30)
    again = build_daily_queue(session, "sales01", AS_OF, widened)
    assert len(again.items) == 30
    assert again.truncated_count == 10
