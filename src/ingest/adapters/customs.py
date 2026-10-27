"""海关 CSV。一条进口记录先变成装运，再按企业聚合。"""

from __future__ import annotations

from pathlib import Path

from src.ingest.csvutil import (
    aware_date,
    base_record,
    country_code,
    decimal_field,
    read_csv,
    require_headers,
)
from src.ingest.normalize import normalize_domain
from src.ingest.records import NormalizedRecord, QuarantineRow, RawRecord, ShipmentDraft
from src.models.enums import BuyerType, ContactChannel, ContactRole, DataUsageScope

_REQUIRED = (
    "raw_importer_name",
    "raw_importer_address",
    "country",
    "hs_code",
    "product_desc",
    "quantity",
    "quantity_unit",
    "amount_usd",
    "ship_date",
    "supplier_name",
    "supplier_country",
    "port_of_discharge",
    "bl_no",
)


class CustomsAdapter:
    source_name = "customs_csv"

    def parse(self, path: Path) -> list[RawRecord]:
        headers, rows = read_csv(path)
        require_headers(headers, _REQUIRED, self.source_name)
        return rows

    def normalize(self, rec: RawRecord) -> NormalizedRecord:
        values = rec.values
        name = values.get("raw_importer_name", "")
        hs_code = values.get("hs_code", "")
        if not name:
            raise QuarantineRow("缺少进口商名称")
        if not hs_code:
            raise QuarantineRow("缺少 hs_code")
        if not hs_code.isdigit():
            raise QuarantineRow(f"hs_code 必须是数字：{hs_code}")
        ship_date = aware_date(values.get("ship_date", ""), "ship_date")
        country = country_code(values.get("country", ""))
        bl_no = values.get("bl_no") or None
        record_id = bl_no or "|".join(
            [name, country, values.get("ship_date", ""), hs_code, values.get("supplier_name", "")]
        )
        email = values.get("email") or None
        amount_raw = values.get("amount_usd", "")
        shipment = ShipmentDraft(
            hs_code=hs_code,
            product_desc=values.get("product_desc") or hs_code,
            quantity=decimal_field(values.get("quantity") or "0", "quantity"),
            quantity_unit=values.get("quantity_unit") or "pcs",
            amount_usd=decimal_field(amount_raw, "amount_usd") if amount_raw else None,
            ship_date=ship_date,
            supplier_name=values.get("supplier_name") or "UNKNOWN",
            supplier_country=country_code(values.get("supplier_country") or country),
            port_of_discharge=values.get("port_of_discharge") or "UNKNOWN",
            bl_no=bl_no,
        )
        return base_record(
            source=self.source_name,
            record_id=record_id,
            source_url=f"file://{self.source_name}#{rec.row_number}",
            company_name=name,
            country=country,
            email=email,
            phone=None,
            contact_name=name,
            role=ContactRole.UNKNOWN,
            collected_at=ship_date,
            scope=DataUsageScope.INTERNAL_USE_ONLY,
            channel=ContactChannel.EMAIL if email else ContactChannel.RECORD_ONLY,
            buyer_type=BuyerType.IMPORTER,
            hs_codes=[hs_code],
            product_interest=values.get("product_desc") or None,
            shipment=shipment,
            raw_text=None,
            hold_note=None,
            domain=normalize_domain(values.get("domain")),
            language=None,
        )

    def dedupe_key(self, rec: NormalizedRecord) -> str:
        if rec.domain:
            return f"domain:{rec.domain}"
        return f"name:{rec.medium_key()}"
