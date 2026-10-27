"""测试夹具。公司名只来自 tests/fixtures，且 source=synthetic。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from src.models.base import new_id
from src.models.catalog import Product
from src.models.insurance import insurance_premium
from src.models.commercial import Inquiry, Quotation
from src.models.enums import (
    BuyerType,
    Channel,
    ContactRole,
    EmailStatus,
    Incoterm,
    InquiryStatus,
    InquiryType,
    LeadStage,
    PaymentTerms,
    QuotationStatus,
)
from src.models.parties import Company, Contact, Lead

COLLECTED_AT = datetime(2026, 1, 15, tzinfo=timezone.utc)
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parties.json"


@dataclass
class Graph:
    company: Company
    contact: Contact
    lead: Lead
    product: Product
    inquiry: Inquiry


def load_fixture() -> dict[str, object]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("source") != "synthetic":
        raise RuntimeError(f"测试夹具必须标记 source=synthetic：{_FIXTURE}")
    return payload


def _companies() -> list[dict[str, str]]:
    raw = load_fixture()["companies"]
    if not isinstance(raw, list):
        raise RuntimeError("companies 必须是数组")
    return [item for item in raw if isinstance(item, dict)]


def _company_raw(key: str) -> dict[str, str]:
    for item in _companies():
        if item.get("key") == key:
            return item
    raise RuntimeError(f"夹具里没有企业 {key}")


def _contact_raw() -> dict[str, str]:
    raw = load_fixture()["contacts"]
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise RuntimeError("夹具缺少联系人")
    return raw[0]


def _product_raw() -> dict[str, str]:
    raw = load_fixture()["product"]
    if not isinstance(raw, dict):
        raise RuntimeError("夹具缺少产品")
    return raw


def add_company(session: Session, key: str) -> Company:
    raw = _company_raw(key)
    row = Company(
        id=new_id(),
        name=raw["name"],
        country=raw["country"],
        domain=raw["domain"],
        buyer_type=BuyerType(raw["buyer_type"]),
        source=raw["source"],
        source_url=raw["source_url"],
        industry=raw["industry"],
        hs_codes=[],
        collected_at=COLLECTED_AT,
    )
    session.add(row)
    return row


def add_contact(
    session: Session,
    company: Company,
    *,
    email: str | None = None,
    full_name: str | None = None,
    role: ContactRole | None = ContactRole.PURCHASING_MANAGER,
    email_status: EmailStatus = EmailStatus.VERIFIED,
) -> Contact:
    raw = _contact_raw()
    row = Contact(
        id=new_id(),
        company_id=company.id,
        full_name=full_name or raw["full_name"],
        role=role,
        email=email or raw["email"],
        email_status=email_status,
        whatsapp_consent=False,
        source=raw["source"],
        source_url=raw["source_url"],
        collected_at=COLLECTED_AT,
    )
    session.add(row)
    return row


def add_lead(
    session: Session,
    company: Company,
    contact: Contact,
    *,
    icp_score: int | None = None,
) -> Lead:
    row = Lead(
        id=new_id(),
        company_id=company.id,
        contact_id=contact.id,
        stage=LeadStage.RAW,
        icp_score=icp_score,
        created_at=COLLECTED_AT,
        updated_at=COLLECTED_AT,
        contact=contact,
    )
    session.add(row)
    return row


def add_product(session: Session) -> Product:
    raw = _product_raw()
    row = Product(
        id=new_id(),
        sku=raw["sku"],
        name_en=raw["name_en"],
        hs_code=raw["hs_code"],
        category=raw["category"],
    )
    session.add(row)
    return row


def add_inquiry(session: Session, lead: Lead) -> Inquiry:
    row = Inquiry(
        id=new_id(),
        lead_id=lead.id,
        channel=Channel.EMAIL,
        raw_text="synthetic inquiry",
        received_at=COLLECTED_AT,
        inquiry_type=InquiryType.REAL_RFQ,
        missing_info=[],
        status=InquiryStatus.NEW,
    )
    session.add(row)
    return row


def build_graph(session: Session) -> Graph:
    company = add_company(session, "a")
    contact = add_contact(session, company)
    lead = add_lead(session, company, contact)
    product = add_product(session)
    inquiry = add_inquiry(session, lead)
    session.flush()
    return Graph(
        company=company,
        contact=contact,
        lead=lead,
        product=product,
        inquiry=inquiry,
    )


def cost_fields(material: str, margin: str = "0") -> dict[str, str]:
    fields = {
        "material_cost": material,
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
        "target_margin": margin,
    }
    return fields


def add_quotation(
    session: Session,
    graph: Graph,
    *,
    material: str,
    unit_price: str,
    quantity: int,
    incoterm: Incoterm,
    destination_port: str | None,
    payment_terms: PaymentTerms,
    created_at: datetime,
    valid_until: datetime,
) -> Quotation:
    fixture = load_fixture()
    fx_rate = fixture["fx_rate"]
    fx_source = fixture["fx_rate_source"]
    if not isinstance(fx_rate, str) or not isinstance(fx_source, str):
        raise RuntimeError("夹具汇率字段类型不对")
    breakdown = cost_fields(material)
    if incoterm in {Incoterm.CIF, Incoterm.DDP}:
        premium = insurance_premium(Decimal(unit_price) * quantity)
        material_amount = Decimal(material) - premium
        if material_amount < 0:
            raise RuntimeError("合成报价扣掉保险后材料成本为负")
        breakdown["insurance"] = format(premium, "f")
        breakdown["material_cost"] = format(material_amount, "f")
    row = Quotation(
        id=new_id(),
        inquiry_id=graph.inquiry.id,
        customer_id=graph.company.id,
        product_sku=graph.product.sku,
        quantity=quantity,
        incoterm=incoterm,
        destination_port=destination_port,
        payment_terms=payment_terms,
        unit_price=Decimal(unit_price),
        currency="USD",
        cost_breakdown=breakdown,
        fx_rate=Decimal(fx_rate),
        fx_rate_source=fx_source,
        fx_rate_at=created_at,
        valid_until=valid_until,
        created_at=created_at,
        status=QuotationStatus.DRAFT,
    )
    session.add(row)
    return row
