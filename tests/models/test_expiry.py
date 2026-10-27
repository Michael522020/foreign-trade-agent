"""过期任务只在显式调用时改状态。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models.enums import Incoterm, PaymentTerms, QuotationStatus
from src.models.expiry import expire_due_quotations
from tests.models.support import add_quotation, build_graph


def test_read_does_not_expire_but_job_does(session) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.CIF,
        destination_port="HAMBURG",
        payment_terms=PaymentTerms.LC_AT_SIGHT,
        created_at=now - timedelta(days=10),
        valid_until=now - timedelta(days=1),
    )
    session.flush()
    session.refresh(quote)
    assert quote.status == QuotationStatus.DRAFT
    result = expire_due_quotations(session, now)
    session.flush()
    assert result.expired_ids == [quote.id]
    assert quote.status == QuotationStatus.EXPIRED


def test_high_risk_draft_is_skipped_when_past_due(session) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.EXW,
        destination_port=None,
        payment_terms=PaymentTerms.DA,
        created_at=now - timedelta(days=10),
        valid_until=now - timedelta(days=1),
    )
    session.flush()
    result = expire_due_quotations(session, now)
    session.flush()
    assert quote.id not in result.expired_ids
    assert result.skipped
    assert quote.status == QuotationStatus.DRAFT
