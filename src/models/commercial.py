"""询盘与报价。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import ID_COL, AwareDateTime, Base, enum_col
from src.models.enums import (
    Channel,
    Incoterm,
    InquiryStatus,
    InquiryType,
    PaymentTerms,
    QuotationStatus,
    Urgency,
)
from src.models.parties import Company, Lead


class Inquiry(Base):
    __tablename__ = "inquiry"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("lead.id"), nullable=False)
    channel: Mapped[Channel] = mapped_column(enum_col(Channel), nullable=False)
    raw_text: Mapped[str] = mapped_column(String(8000), nullable=False)
    received_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    inquiry_type: Mapped[InquiryType] = mapped_column(
        enum_col(InquiryType),
        nullable=False,
    )
    urgency: Mapped[Urgency] = mapped_column(
        enum_col(Urgency),
        nullable=False,
        default=Urgency.NORMAL,
    )
    missing_info: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    first_response_at: Mapped[datetime | None] = mapped_column(AwareDateTime())
    status: Mapped[InquiryStatus] = mapped_column(
        enum_col(InquiryStatus),
        nullable=False,
        default=InquiryStatus.NEW,
    )

    lead: Mapped[Lead] = relationship()


class Quotation(Base):
    __tablename__ = "quotation"
    __table_args__ = (
        CheckConstraint(
            "("
            "incoterm IN ('CFR', 'CIF', 'DAP', 'DDP') "
            "AND destination_port IS NOT NULL"
            ") OR ("
            "incoterm IN ('EXW', 'FOB') "
            "AND destination_port IS NULL"
            ")",
            name="ck_quotation_destination_port",
        ),
        CheckConstraint(
            "payment_terms NOT IN ('DP', 'DA', 'OA') OR status = 'DRAFT'",
            name="ck_quotation_high_risk_stays_draft",
        ),
        CheckConstraint(
            "valid_until > created_at",
            name="ck_quotation_valid_until",
        ),
        CheckConstraint(
            "incoterm NOT IN ('CIF', 'DDP') "
            "OR CAST(json_extract(cost_breakdown, '$.insurance') AS NUMERIC) > 0",
            name="ck_quotation_cif_ddp_insurance",
        ),
        Index("ix_quotation_valid_until", "valid_until"),
        Index("ix_quotation_status", "status"),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    inquiry_id: Mapped[str] = mapped_column(ForeignKey("inquiry.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    product_sku: Mapped[str] = mapped_column(ForeignKey("product.sku"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    incoterm: Mapped[Incoterm] = mapped_column(enum_col(Incoterm), nullable=False)
    destination_port: Mapped[str | None] = mapped_column(String(100))
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        enum_col(PaymentTerms),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_breakdown: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        doc="1 单位报价币种兑多少人民币",
    )
    fx_rate_source: Mapped[str] = mapped_column(String(100), nullable=False)
    fx_rate_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    status: Mapped[QuotationStatus] = mapped_column(
        enum_col(QuotationStatus),
        nullable=False,
        default=QuotationStatus.DRAFT,
    )

    inquiry: Mapped[Inquiry] = relationship()
    customer: Mapped[Company] = relationship()
