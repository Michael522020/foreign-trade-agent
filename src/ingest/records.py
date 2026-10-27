"""采集行在入库前的中间形态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.models.enums import BuyerType, ContactChannel, ContactRole, DataUsageScope, EmailStatus


class IngestRejected(Exception):
    """整批不能导入。调用方必须把原因展示出来。"""


class QuarantineRow(Exception):
    """单行隔离。原因要写进 quarantine，不能悄悄丢掉。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class RawRecord:
    row_number: int
    values: dict[str, str]


@dataclass
class ShipmentDraft:
    hs_code: str
    product_desc: str
    quantity: Decimal
    quantity_unit: str
    amount_usd: Decimal | None
    ship_date: datetime
    supplier_name: str
    supplier_country: str
    port_of_discharge: str
    bl_no: str | None


@dataclass
class NormalizedRecord:
    source: str
    source_record_id: str
    idempotency_key: str
    source_url: str
    company_name: str
    normalized_name: str
    country: str
    domain: str | None
    email: str | None
    is_role_based: bool
    email_status: EmailStatus
    phone: str | None
    phone_e164: str | None
    contact_name: str
    role: ContactRole
    language: str | None
    hs_codes: list[str]
    collected_at: datetime
    data_usage_scope: DataUsageScope
    contact_channel: ContactChannel
    buyer_type: BuyerType
    product_interest: str | None
    hold_note: str | None
    raw_text: str | None
    shipment: ShipmentDraft | None
    source_signals: dict[str, str] = field(default_factory=dict)

    def medium_key(self) -> str:
        return f"{self.normalized_name}|{self.country}"


@dataclass
class IngestReport:
    parsed: int = 0
    passed: int = 0
    quarantined: int = 0
    deduped: int = 0
    suppressed: int = 0
    companies_created: int = 0

    def render(self) -> str:
        return "\n".join(
            [
                f"解析行数 {self.parsed}",
                f"通过数 {self.passed}",
                f"隔离数 {self.quarantined}",
                f"去重合并数 {self.deduped}",
                f"抑制命中数 {self.suppressed}",
            ]
        )
