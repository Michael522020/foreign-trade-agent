"""已确认的业务口径。反例必须被拒绝。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.errors import ConstraintViolation, InvalidTransition
from src.models.base import new_id
from src.models.commercial import Inquiry
from src.models.compliance import Interaction
from src.models.enums import Channel, Direction, Incoterm, InquiryStatus, LeadStage, PaymentTerms
from src.models.fx import foreign_to_cny
from src.models.parties import Lead
from src.models.schemas import QuotationIn
from src.models.state_machine import InquiryEvent, LeadEvent, transition
from tests.models.support import add_quotation, build_graph, cost_fields, load_fixture

CREATED = datetime(2026, 10, 1, tzinfo=timezone.utc)
VALID = datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_fx_rate_converts_one_foreign_unit_into_cny() -> None:
    assert foreign_to_cny(Decimal("10"), Decimal("7.1")) == Decimal("71.0")


def test_cny_quote_rejects_a_non_one_rate() -> None:
    fixture = load_fixture()
    payload = {
        "inquiry_id": "synthetic-inquiry",
        "customer_id": "synthetic-customer",
        "product_sku": "SYN-SKU-1",
        "quantity": 10,
        "incoterm": Incoterm.EXW,
        "destination_port": None,
        "payment_terms": PaymentTerms.TT_100_ADVANCE,
        "unit_price": Decimal("10"),
        "currency": "CNY",
        "cost_breakdown": cost_fields("100"),
        "fx_rate": Decimal(str(fixture["fx_rate"])),
        "fx_rate_source": fixture["fx_rate_source"],
        "fx_rate_at": CREATED,
        "valid_until": VALID,
        "created_at": CREATED,
    }
    with pytest.raises(ValidationError, match="人民币"):
        QuotationIn.model_validate(payload)
    payload["fx_rate"] = Decimal(1)
    parsed = QuotationIn.model_validate(payload)
    assert parsed.fx_rate == Decimal(1)


def test_cif_and_ddp_require_a_positive_insurance_line() -> None:
    fixture = load_fixture()
    base = {
        "inquiry_id": "synthetic-inquiry",
        "customer_id": "synthetic-customer",
        "product_sku": "SYN-SKU-1",
        "quantity": 10,
        "destination_port": "HAMBURG",
        "payment_terms": PaymentTerms.TT_100_ADVANCE,
        "unit_price": Decimal("10"),
        "currency": "USD",
        "cost_breakdown": cost_fields("100"),
        "fx_rate": Decimal(str(fixture["fx_rate"])),
        "fx_rate_source": fixture["fx_rate_source"],
        "fx_rate_at": CREATED,
        "valid_until": VALID,
        "created_at": CREATED,
    }
    for incoterm in (Incoterm.CIF, Incoterm.DDP):
        with pytest.raises(ValidationError, match="保险"):
            QuotationIn.model_validate({**base, "incoterm": incoterm})


def test_database_rejects_zero_cif_insurance(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.CIF,
        destination_port="HAMBURG",
        payment_terms=PaymentTerms.TT_100_ADVANCE,
        created_at=CREATED,
        valid_until=VALID,
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "UPDATE quotation "
                "SET cost_breakdown = json_set(cost_breakdown, '$.insurance', '0') "
                "WHERE id = :id"
            ),
            {"id": quote.id},
        )


def test_contacted_cannot_skip_the_reply(session) -> None:  # type: ignore[no-untyped-def]
    del session
    lead = Lead(stage=LeadStage.CONTACTED)
    for event in (LeadEvent.MARK_NOT_INTERESTED, LeadEvent.NURTURE):
        with pytest.raises(InvalidTransition, match="必须先有回复") as caught:
            transition(lead, event)
        assert caught.value.allowed_from == ["REPLIED"]
        assert lead.stage == LeadStage.CONTACTED


def test_complete_inquiry_still_passes_needs_info() -> None:
    inquiry = Inquiry(status=InquiryStatus.TRIAGED, missing_info=[])
    with pytest.raises(InvalidTransition, match="五要素齐全") as caught:
        transition(inquiry, InquiryEvent.MARK_QUOTED)
    assert caught.value.allowed_from == ["NEEDS_INFO"]
    assert inquiry.status == InquiryStatus.TRIAGED


def test_unknown_employee_band_is_rejected(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.company.employee_band = "HUGE"
    with pytest.raises(ConstraintViolation) as caught:
        session.flush()
    assert caught.value.field == "employee_band"


def test_unknown_outcome_is_rejected(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    session.add(
        Interaction(
            id=new_id(),
            lead_id=graph.lead.id,
            channel=Channel.EMAIL,
            direction=Direction.INBOUND,
            occurred_at=CREATED,
            content_ref="fixture://outcome",
            outcome="CALL_BACK_LATER",
        )
    )
    with pytest.raises(ConstraintViolation, match="交互结果") as caught:
        session.flush()
    assert caught.value.field == "outcome"
