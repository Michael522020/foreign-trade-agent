"""采集落库用的表。抑制命中只记在 ingest_drop，不写 Company。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import ID_COL, AwareDateTime, Base


class CustomsShipment(Base):
    __tablename__ = "customs_shipment"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    hs_code: Mapped[str] = mapped_column(String(16), nullable=False)
    product_desc: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ship_date: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_country: Mapped[str] = mapped_column(String(2), nullable=False)
    port_of_discharge: Mapped[str] = mapped_column(String(100), nullable=False)
    bl_no: Mapped[str | None] = mapped_column(String(64))


class QuarantineItem(Base):
    __tablename__ = "quarantine"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    row_number: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class MergeCandidate(Base):
    __tablename__ = "merge_candidate"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    other_company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), nullable=False)
    weak_key: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class IngestLedger(Base):
    __tablename__ = "ingest_ledger"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_ingest_idempotency"),)

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("company.id"))
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class IngestDrop(Base):
    __tablename__ = "ingest_drop"

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    drop_reason: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
