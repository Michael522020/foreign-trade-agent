"""发送闸门：失败即拦截，检查出错也拦截，并且不发送。"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.compliance.config import GateConfig, load_gate_config
from src.compliance.gate import SendTask, send_gate
from src.logging_config import bind_trace, current_trace_id
from src.models.base import new_id, utcnow
from src.models.compliance import ComplianceAudit, Suppression
from src.models.enums import EmailStatus, SuppressionReason, SuppressionScope
from src.outreach.validate import ApprovedFact
from tests.models.support import build_graph

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
_FACTS = [ApprovedFact("100", "pcs", "config/product.yaml")]


def _ctx(**overrides: object) -> GateConfig:
    payload: dict[str, object] = {
        "auth_ready": True,
        "daily_cap": 20,
        "complaint_block": Decimal("0.001"),
        "complaint_warn": Decimal("0.0008"),
        "bounce_block": Decimal("0.02"),
        "freemail_domains": frozenset({"gmail.com"}),
        "blocked_countries": frozenset({"DE", "AU", "CA"}),
        "lia_required_countries": frozenset({"FR"}),
        "lia_recorded_countries": frozenset(),
        "sanction_list_loaded": True,
        "sanction_names": frozenset(),
        "config_hash": "test",
    }
    payload.update(overrides)
    return GateConfig(**payload)  # type: ignore[arg-type]


def _task(lead_id: str, **overrides: object) -> SendTask:
    payload: dict[str, object] = {
        "task_id": "task-1",
        "lead_id": lead_id,
        "body": "",
        "is_first_touch": True,
        "human_approved": True,
    }
    payload.update(overrides)
    return SendTask(**payload)  # type: ignore[arg-type]


def test_default_config_is_not_ready_to_send() -> None:
    loaded = load_gate_config()
    assert loaded.auth_ready is False
    assert loaded.sanction_list_loaded is False


def test_trace_id_stays_for_the_whole_command() -> None:
    bind_trace("trace-fixed")
    assert current_trace_id() == "trace-fixed"
    assert current_trace_id() == "trace-fixed"


def test_opt_out_and_suppression_block(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    session.add(
        Suppression(
            id=new_id(),
            email=graph.contact.email,
            reason=SuppressionReason.UNSUBSCRIBED,
            scope=SuppressionScope.GLOBAL,
            created_at=utcnow(),
        )
    )
    session.flush()
    result = send_gate(session, _task(graph.lead.id), _ctx(), _FACTS, NOW)
    assert result.allowed is False
    assert result.blocked_reasons == ["PREVIOUSLY_OPTED_OUT"]
    audit = session.scalars(select(ComplianceAudit)).one()
    assert audit.decision.value == "blocked"
    assert audit.lead_id == graph.lead.id


def test_unverified_email_blocks(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.contact.email_status = EmailStatus.UNKNOWN
    session.flush()
    result = send_gate(session, _task(graph.lead.id), _ctx(), _FACTS, NOW)
    assert result.blocked_reasons == ["EMAIL_NOT_VERIFIED"]


def test_germany_blocks_even_when_the_note_is_clean(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    session.flush()
    result = send_gate(session, _task(graph.lead.id), _ctx(), _FACTS, NOW)
    assert result.blocked_reasons == ["JURISDICTION_RESTRICTED"]


def test_missing_human_approval_blocks_a_clear_us_lead(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.company.country = "US"
    session.flush()
    result = send_gate(
        session,
        _task(graph.lead.id, human_approved=False),
        _ctx(),
        _FACTS,
        NOW,
    )
    assert result.allowed is False
    assert result.blocked_reasons == ["NO_HUMAN_APPROVAL"]


def test_exact_sanction_name_blocks_without_override(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.company.country = "US"
    session.flush()
    result = send_gate(
        session,
        _task(graph.lead.id),
        _ctx(sanction_names=frozenset({graph.company.name.casefold()})),
        _FACTS,
        NOW,
    )
    assert result.blocked_reasons == ["SANCTIONED_ENTITY"]


def test_unapproved_quantity_is_named(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    graph.company.country = "US"
    session.flush()
    result = send_gate(
        session,
        _task(graph.lead.id, body="Please ship 500 pcs this month and confirm the rest later."),
        _ctx(),
        _FACTS,
        NOW,
    )
    assert result.blocked_reasons == ["UNAPPROVED_COMMERCIAL_TERM:500 pcs"]


def test_gate_error_does_not_allow_send() -> None:
    class Broken:
        def get(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("数据库不可用")

        def add(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("审计写不进去")

        def scalars(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("数据库不可用")

    result = send_gate(Broken(), _task("missing"), _ctx(), _FACTS, NOW)  # type: ignore[arg-type]
    assert result.allowed is False
    assert result.blocked_reasons == ["GATE_CHECK_ERROR"]


def test_quota_zero_blocks(session) -> None:  # type: ignore[no-untyped-def]
    graph = build_graph(session)
    session.flush()
    result = send_gate(session, _task(graph.lead.id), _ctx(daily_cap=0), _FACTS, NOW)
    assert result.blocked_reasons == ["DAILY_QUOTA_EXCEEDED"]
