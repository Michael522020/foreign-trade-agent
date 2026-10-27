"""企业、联系人、线索。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import ID_COL, AwareDateTime, Base, enum_col
from src.models.enums import BuyerType, ContactChannel, ContactRole, EmailStatus, LeadStage


class Company(Base):
    __tablename__ = "company"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(100))
    hs_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    employee_band: Mapped[str | None] = mapped_column(String(32))
    annual_revenue_band: Mapped[str | None] = mapped_column(String(32))
    buyer_type: Mapped[BuyerType] = mapped_column(enum_col(BuyerType), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String(200))
    normalized_domain: Mapped[str | None] = mapped_column(String(200))
    import_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_ship_date: Mapped[datetime | None] = mapped_column(AwareDateTime())
    supplier_top3_share: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    data_usage_scope: Mapped[str | None] = mapped_column(String(40))
    source_signals: Mapped[dict[str, object] | None] = mapped_column(JSON)

    contacts: Mapped[list[Contact]] = relationship(back_populates="company")


class Contact(Base):
    __tablename__ = "contact"
    __table_args__ = (
        UniqueConstraint("company_id", "email", name="uq_contact_company_email"),
        Index("ix_contact_email", "email"),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[ContactRole | None] = mapped_column(enum_col(ContactRole))
    email: Mapped[str | None] = mapped_column(String(320))
    is_role_based: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contact_channel: Mapped[ContactChannel | None] = mapped_column(enum_col(ContactChannel))
    email_status: Mapped[EmailStatus] = mapped_column(
        enum_col(EmailStatus),
        nullable=False,
    )
    phone: Mapped[str | None] = mapped_column(String(32))
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    whatsapp_consent: Mapped[bool] = mapped_column(nullable=False, default=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    language: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(AwareDateTime())

    company: Mapped[Company] = relationship(back_populates="contacts")


class Lead(Base):
    __tablename__ = "lead"
    __table_args__ = (
        CheckConstraint(
            "icp_score IS NULL OR (icp_score >= 0 AND icp_score <= 100)",
            name="ck_lead_icp_score_range",
        ),
        Index("ix_lead_stage", "stage"),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contact.id"), nullable=False)
    product_interest: Mapped[str | None] = mapped_column(String(200))
    icp_score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSON)
    stage: Mapped[LeadStage] = mapped_column(
        enum_col(LeadStage),
        nullable=False,
        default=LeadStage.RAW,
    )
    owner: Mapped[str | None] = mapped_column(String(100))
    auto_outreach_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hold_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)

    company: Mapped[Company] = relationship()
    contact: Mapped[Contact] = relationship()
