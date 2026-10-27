"""卖方产品与认证台账。认证状态只记录台账值，不按国家推断。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, JSON, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import ID_COL, AwareDateTime, Base, enum_col
from src.models.enums import CertificationStatus, CertificationType

product_certification = Table(
    "product_certification",
    Base.metadata,
    Column("product_id", ForeignKey("product.id"), primary_key=True),
    Column("certification_id", ForeignKey("certification.id"), primary_key=True),
)


class Certification(Base):
    __tablename__ = "certification"
    __table_args__ = (
        CheckConstraint("valid_to >= valid_from", name="ck_certification_validity"),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    type: Mapped[CertificationType] = mapped_column(
        enum_col(CertificationType),
        nullable=False,
    )
    cert_no: Mapped[str] = mapped_column(String(100), nullable=False)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    covered_skus: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    document_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[CertificationStatus] = mapped_column(
        enum_col(CertificationStatus),
        nullable=False,
    )

    products: Mapped[list[Product]] = relationship(
        secondary=product_certification,
        back_populates="certifications",
    )


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        CheckConstraint(
            "moq_default IS NULL OR moq_default > 0",
            name="ck_product_moq_positive",
        ),
        CheckConstraint(
            "lead_time_days_default IS NULL OR lead_time_days_default >= 0",
            name="ck_product_lead_time_non_negative",
        ),
    )

    id: Mapped[str] = mapped_column(ID_COL, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    hs_code: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    moq_default: Mapped[int | None] = mapped_column(Integer)
    lead_time_days_default: Mapped[int | None] = mapped_column(Integer)
    cost_breakdown_ref: Mapped[str | None] = mapped_column(String(200))

    certifications: Mapped[list[Certification]] = relationship(
        secondary=product_certification,
        back_populates="products",
    )
