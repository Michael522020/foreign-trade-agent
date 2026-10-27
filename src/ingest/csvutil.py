"""CSV 读取和行级小工具，供各个来源适配器共用。"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.ingest.normalize import normalize_company_name
from src.ingest.records import (
    IngestRejected,
    NormalizedRecord,
    QuarantineRow,
    RawRecord,
    ShipmentDraft,
)
from src.models.enums import (
    BuyerType,
    ContactChannel,
    ContactRole,
    DataUsageScope,
    EmailStatus,
)


def read_csv(path: Path) -> tuple[list[str], list[RawRecord]]:
    if not path.is_file():
        raise IngestRejected(f"找不到文件：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise IngestRejected(f"{path.name} 没有表头")
        headers = [name.strip() for name in reader.fieldnames if name]
        rows: list[RawRecord] = []
        for index, row in enumerate(reader, start=2):
            values = {key.strip(): (value or "").strip() for key, value in row.items() if key}
            rows.append(RawRecord(row_number=index, values=values))
    return headers, rows


def require_headers(headers: list[str], required: tuple[str, ...], source: str) -> None:
    missing = [name for name in required if name not in headers]
    if missing:
        raise IngestRejected(f"{source} 缺少列：{', '.join(missing)}")


def aware_date(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise QuarantineRow(f"{field} 日期无法解析：{value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def decimal_field(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise QuarantineRow(f"{field} 不是数字：{value}") from exc


def idempotency_key(source: str, record_id: str) -> str:
    return hashlib.sha256(f"{source}|{record_id}".encode()).hexdigest()


def country_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise QuarantineRow(f"country 必须是两位字母：{value}")
    return code


def role_or_unknown(value: str | None) -> ContactRole:
    if not value:
        return ContactRole.UNKNOWN
    try:
        return ContactRole(value)
    except ValueError as exc:
        raise QuarantineRow(f"未知角色：{value}") from exc


def base_record(
    *,
    source: str,
    record_id: str,
    source_url: str,
    company_name: str,
    country: str,
    email: str | None,
    phone: str | None,
    contact_name: str,
    role: ContactRole,
    collected_at: datetime,
    scope: DataUsageScope,
    channel: ContactChannel,
    buyer_type: BuyerType,
    hs_codes: list[str],
    product_interest: str | None,
    shipment: ShipmentDraft | None,
    raw_text: str | None,
    hold_note: str | None,
    domain: str | None,
    language: str | None,
) -> NormalizedRecord:
    if not company_name.strip():
        raise QuarantineRow("缺少企业名称")
    normalized = normalize_company_name(company_name)
    if not normalized:
        raise QuarantineRow(f"企业名归一化后为空：{company_name}")
    return NormalizedRecord(
        source=source,
        source_record_id=record_id,
        idempotency_key=idempotency_key(source, record_id),
        source_url=source_url,
        company_name=company_name.strip(),
        normalized_name=normalized,
        country=country,
        domain=domain,
        email=email.lower() if email else None,
        is_role_based=False,
        email_status=EmailStatus.UNKNOWN,
        phone=phone,
        phone_e164=phone if phone and phone.startswith("+") else None,
        contact_name=contact_name.strip() or company_name.strip(),
        role=role,
        language=language,
        hs_codes=hs_codes,
        collected_at=collected_at,
        data_usage_scope=scope,
        contact_channel=channel,
        buyer_type=buyer_type,
        product_interest=product_interest,
        hold_note=hold_note,
        raw_text=raw_text,
        shipment=shipment,
    )
