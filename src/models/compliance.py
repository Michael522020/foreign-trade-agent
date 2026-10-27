"""抑制名单、交互流水、合规审计。抑制与联系人无级联。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import ID_COL, AwareDateTime, Base, enum_col
from src.models.enums import (
    Channel,
    ComplianceDecision,
    Direction,
    SuppressionReason,
    SuppressionScope,
)
from src.models.parties import Lead


class Suppression(Base):
    __tablename__ = "suppression"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL OR domain IS NOT NULL",
            name="ck_suppression_has_target",
        ),
        Index("ix_suppression_email", "email"),
        Index("ix_suppression_phone", "phone"),
        Index("ix_suppression_domain", "domain"),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    domain: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[SuppressionReason] = mapped_column(
        enum_col(SuppressionReason),
        nullable=False,
    )
    scope: Mapped[SuppressionScope] = mapped_column(
        enum_col(SuppressionScope),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(200))


class Interaction(Base):
    __tablename__ = "interaction"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("lead.id"), nullable=False)
    channel: Mapped[Channel] = mapped_column(enum_col(Channel), nullable=False)
    direction: Mapped[Direction] = mapped_column(enum_col(Direction), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    content_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(200))
    next_action_at: Mapped[datetime | None] = mapped_column(AwareDateTime())

    lead: Mapped[Lead] = relationship()


class ComplianceAudit(Base):
    __tablename__ = "compliance_audit"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_id: Mapped[str] = mapped_column(ForeignKey("lead.id"), nullable=False)
    decision: Mapped[ComplianceDecision] = mapped_column(
        enum_col(ComplianceDecision),
        nullable=False,
    )
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gate_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(100))
    override_reason: Mapped[str | None] = mapped_column(String(500))
    override_evidence_ref: Mapped[str | None] = mapped_column(String(200))

    lead: Mapped[Lead] = relationship()
