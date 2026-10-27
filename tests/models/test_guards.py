"""状态机守卫与数据库约束。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.errors import ConstraintViolation, InvalidTransition
from src.models.enums import (
    EmailStatus,
    Incoterm,
    LeadStage,
    PaymentTerms,
    QuotationStatus,
)
from src.models.parties import Lead
from src.models.schemas import QuotationIn
from src.models.state_machine import LeadEvent, transition
from tests.models.support import add_quotation, build_graph, load_fixture

CREATED = datetime(2026, 10, 1, tzinfo=timezone.utc)
VALID = datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_exw_rejects_destination_port() -> None:
    fixture = load_fixture()
    with pytest.raises(ValidationError):
        QuotationIn.model_validate(
            {
                "inquiry_id": "synthetic-inquiry",
                "customer_id": "synthetic-customer",
                "product_sku": "SYN-SKU-1",
                "quantity": 10,
                "incoterm": Incoterm.EXW,
                "destination_port": "HAMBURG",
                "payment_terms": PaymentTerms.TT_100_ADVANCE,
                "unit_price": "10",
                "currency": "usd",
                "cost_breakdown": {
                    "material_cost": "100",
                    "labor_cost": "0",
                    "packaging_cost": "0",
                    "inland_freight": "0",
                    "export_clearance_fee": "0",
                    "main_freight": "0",
                    "insurance": "0",
                    "bank_charge": "0",
                    "certification_amortized": "0",
                    "export_rebate_adjustment": "0",
                    "fx_buffer_rate": "0",
                    "target_margin": "0",
                },
                "fx_rate": fixture["fx_rate"],
                "fx_rate_source": fixture["fx_rate_source"],
                "fx_rate_at": CREATED,
                "valid_until": VALID,
                "created_at": CREATED,
            }
        )


def test_disabled_incoterm_is_rejected() -> None:
    fixture = load_fixture()
    with pytest.raises(ValidationError):
        QuotationIn.model_validate(
            {
                "inquiry_id": "synthetic-inquiry",
                "customer_id": "synthetic-customer",
                "product_sku": "SYN-SKU-1",
                "quantity": 1,
                "incoterm": Incoterm.FCA,
                "destination_port": None,
                "payment_terms": PaymentTerms.TT_100_ADVANCE,
                "unit_price": "1",
                "currency": "USD",
                "cost_breakdown": {
                    "material_cost": "1",
                    "labor_cost": "0",
                    "packaging_cost": "0",
                    "inland_freight": "0",
                    "export_clearance_fee": "0",
                    "main_freight": "0",
                    "insurance": "0",
                    "bank_charge": "0",
                    "certification_amortized": "0",
                    "export_rebate_adjustment": "0",
                    "fx_buffer_rate": "0",
                    "target_margin": "0",
                },
                "fx_rate": fixture["fx_rate"],
                "fx_rate_source": fixture["fx_rate_source"],
                "fx_rate_at": CREATED,
                "valid_until": VALID,
                "created_at": CREATED,
            }
        )


def test_database_rejects_high_risk_status_update(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.EXW,
        destination_port=None,
        payment_terms=PaymentTerms.DP,
        created_at=CREATED,
        valid_until=VALID,
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE quotation SET status = 'PENDING_REVIEW' WHERE id = :id"),
            {"id": quote.id},
        )
    session.rollback()


def test_orm_bypass_of_high_risk_transition_is_rejected(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.EXW,
        destination_port=None,
        payment_terms=PaymentTerms.OA,
        created_at=CREATED,
        valid_until=VALID,
    )
    session.flush()
    quote.status = QuotationStatus.PENDING_REVIEW
    with pytest.raises(InvalidTransition):
        session.flush()


def test_cif_without_port_is_rejected_by_database(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    quote = add_quotation(
        session,
        graph,
        material="100",
        unit_price="10",
        quantity=10,
        incoterm=Incoterm.EXW,
        destination_port=None,
        payment_terms=PaymentTerms.TT_100_ADVANCE,
        created_at=CREATED,
        valid_until=VALID,
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE quotation SET incoterm = 'CIF' WHERE id = :id"),
            {"id": quote.id},
        )
    session.rollback()


def test_unverified_email_cannot_enter_queued(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.contact.email_status = EmailStatus.UNKNOWN
    graph.lead.icp_score = 40
    transition(graph.lead, LeadEvent.ENRICH)
    session.flush()
    transition(graph.lead, LeadEvent.SCORE)
    session.flush()
    with pytest.raises(ConstraintViolation) as caught:
        transition(graph.lead, LeadEvent.QUEUE)
    assert caught.value.field == "email_status"
    assert graph.lead.stage == LeadStage.SCORED


def test_missing_role_cannot_enter_queued(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.contact.role = None
    graph.lead.icp_score = 40
    transition(graph.lead, LeadEvent.ENRICH)
    session.flush()
    transition(graph.lead, LeadEvent.SCORE)
    session.flush()
    with pytest.raises(ConstraintViolation) as caught:
        transition(graph.lead, LeadEvent.QUEUE)
    assert caught.value.field == "role"


def test_new_lead_cannot_start_suppressed(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    rogue = Lead(
        company_id=graph.company.id,
        contact_id=graph.contact.id,
        stage=LeadStage.SUPPRESSED,
        created_at=CREATED,
        updated_at=CREATED,
    )
    session.add(rogue)
    with pytest.raises(InvalidTransition):
        session.flush()


def test_won_cannot_move_to_suppressed() -> None:
    lead = Lead(stage=LeadStage.WON)
    with pytest.raises(InvalidTransition) as caught:
        transition(lead, LeadEvent.SUPPRESS)
    assert caught.value.from_state == LeadStage.WON.value
    assert caught.value.to_state == LeadStage.SUPPRESSED.value
