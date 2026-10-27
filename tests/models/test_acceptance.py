"""P0 验收反例。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from src.errors import ConstraintViolation, InvalidTransition
from src.models.commercial import Quotation
from src.models.cost import COST_SUM_RELATIVE_TOLERANCE
from src.models.enums import Incoterm, PaymentTerms, QuotationStatus
from src.models.enums import LeadStage
from src.models.parties import Lead
from src.models.schemas import QuotationIn
from src.models.state_machine import LeadEvent, QuotationEvent, transition
from tests.models.support import add_contact, add_company, add_quotation, build_graph, cost_fields, load_fixture

CREATED = datetime(2026, 10, 1, tzinfo=timezone.utc)
VALID = datetime(2026, 10, 20, tzinfo=timezone.utc)


def _quote_payload(incoterm: Incoterm, port: str | None, material: str) -> dict[str, object]:
    fixture = load_fixture()
    return {
        "inquiry_id": "synthetic-inquiry",
        "customer_id": "synthetic-customer",
        "product_sku": "SYN-SKU-1",
        "quantity": 10,
        "incoterm": incoterm,
        "destination_port": port,
        "payment_terms": PaymentTerms.TT_100_ADVANCE,
        "unit_price": Decimal("10"),
        "currency": "USD",
        "cost_breakdown": cost_fields(material),
        "fx_rate": Decimal(str(fixture["fx_rate"])),
        "fx_rate_source": fixture["fx_rate_source"],
        "fx_rate_at": CREATED,
        "valid_until": VALID,
        "created_at": CREATED,
    }


@pytest.mark.parametrize("terms", [PaymentTerms.DP, PaymentTerms.DA, PaymentTerms.OA])
def test_high_risk_payment_cannot_leave_draft(terms: PaymentTerms) -> None:
    quote = Quotation(status=QuotationStatus.DRAFT, payment_terms=terms)
    with pytest.raises(InvalidTransition) as caught:
        transition(quote, QuotationEvent.SUBMIT_REVIEW)
    assert caught.value.from_state == QuotationStatus.DRAFT.value
    assert caught.value.to_state == QuotationStatus.PENDING_REVIEW.value
    assert caught.value.allowed_from == []


def test_cif_requires_destination_port() -> None:
    with pytest.raises(ValidationError):
        QuotationIn.model_validate(_quote_payload(Incoterm.CIF, None, "100"))


def test_cost_breakdown_off_by_five_percent_is_rejected(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    add_quotation(
        session,
        graph,
        material="105",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.EXW,
        destination_port=None,
        payment_terms=PaymentTerms.TT_100_ADVANCE,
        created_at=CREATED,
        valid_until=VALID,
    )
    with pytest.raises(ConstraintViolation) as caught:
        session.flush()
    assert caught.value.field == "cost_breakdown"


def test_cost_within_half_percent_is_stored(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    add_quotation(
        session,
        graph,
        material="100.5",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.FOB,
        destination_port=None,
        payment_terms=PaymentTerms.TT_30_70_BL_COPY,
        created_at=CREATED,
        valid_until=VALID,
    )
    session.flush()
    assert COST_SUM_RELATIVE_TOLERANCE == Decimal("0.005")


def test_suppressed_lead_cannot_be_contacted() -> None:
    lead = Lead(stage=LeadStage.SUPPRESSED)
    with pytest.raises(InvalidTransition) as caught:
        transition(lead, LeadEvent.CONTACT)
    assert caught.value.from_state == "SUPPRESSED"
    assert caught.value.to_state == "CONTACTED"
    assert caught.value.allowed_from == ["QUEUED"]


def test_duplicate_company_email_rejected(session) -> None:  # type: ignore[no-untyped-def]
    company = add_company(session, "a")
    add_contact(session, company)
    session.flush()
    add_contact(session, company, full_name="SYN-CONTACT-DUP")
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_same_email_on_another_company_is_allowed(session) -> None:  # type: ignore[no-untyped-def]
    first = add_company(session, "a")
    second = add_company(session, "b")
    raw_email = "buyer-a@syn-company-a.example"
    add_contact(session, first, email=raw_email)
    add_contact(session, second, email=raw_email, full_name="SYN-CONTACT-B")
    session.flush()
