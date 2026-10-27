"""展会、平台、独立站、手工导入。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.ingest.csvutil import aware_date, base_record, country_code, read_csv, require_headers, role_or_unknown
from src.ingest.normalize import normalize_domain
from src.ingest.records import NormalizedRecord, QuarantineRow, RawRecord
from src.models.enums import BuyerType, ContactChannel, ContactRole, DataUsageScope


class ExhibitionAdapter:
    source_name = "exhibition_csv"

    def parse(self, path: Path) -> list[RawRecord]:
        headers, rows = read_csv(path)
        require_headers(
            headers,
            ("company_name", "country", "contact_name", "event_name", "event_date"),
            self.source_name,
        )
        return rows

    def normalize(self, rec: RawRecord) -> NormalizedRecord:
        values = rec.values
        email = values.get("email") or None
        phone = values.get("phone") or None
        if not email and not phone:
            raise QuarantineRow("展会名片缺少邮箱和电话")
        channel = ContactChannel.PERSONAL_MEETING if phone and not email else ContactChannel.EMAIL
        normalized = base_record(
            source=self.source_name,
            record_id="|".join(
                [values.get("event_name", ""), values.get("company_name", ""), values.get("contact_name", "")]
            ),
            source_url=f"event://{values.get('event_name', '')}",
            company_name=values.get("company_name", ""),
            country=country_code(values.get("country", "")),
            email=email,
            phone=phone,
            contact_name=values.get("contact_name") or values.get("company_name", ""),
            role=role_or_unknown(values.get("role")),
            collected_at=aware_date(values.get("event_date", ""), "event_date"),
            scope=DataUsageScope.INTERNAL_USE_ONLY,
            channel=channel,
            buyer_type=BuyerType.UNKNOWN,
            hs_codes=[],
            product_interest=values.get("product_interest") or None,
            shipment=None,
            raw_text=values.get("note") or None,
            hold_note=None,
            domain=normalize_domain(values.get("domain")),
            language=values.get("language") or None,
        )
        normalized.source_signals["event_name"] = values.get("event_name", "")
        return normalized

    def dedupe_key(self, rec: NormalizedRecord) -> str:
        return f"name:{rec.medium_key()}"


class PlatformAdapter:
    source_name = "platform_csv"

    def parse(self, path: Path) -> list[RawRecord]:
        headers, rows = read_csv(path)
        require_headers(headers, ("company_name", "country", "raw_text", "product"), self.source_name)
        return rows

    def normalize(self, rec: RawRecord) -> NormalizedRecord:
        values = rec.values
        collected = (
            aware_date(values["received_at"], "received_at")
            if values.get("received_at")
            else datetime.now(timezone.utc)
        )
        normalized = base_record(
            source=self.source_name,
            record_id=values.get("message_id") or f"row-{rec.row_number}",
            source_url=values.get("source_url") or f"platform://inbox/{rec.row_number}",
            company_name=values.get("company_name", ""),
            country=country_code(values.get("country", "")),
            email=values.get("email") or None,
            phone=None,
            contact_name=values.get("contact_name") or values.get("company_name", ""),
            role=ContactRole.UNKNOWN,
            collected_at=collected,
            scope=DataUsageScope.INTERNAL_USE_ONLY,
            channel=ContactChannel.PLATFORM_INBOX,
            buyer_type=BuyerType.UNKNOWN,
            hs_codes=[],
            product_interest=values.get("product") or None,
            shipment=None,
            raw_text=values.get("raw_text") or None,
            hold_note=None,
            domain=None,
            language=values.get("language") or None,
        )
        for key in ("buyer_member_since", "response_rate"):
            if values.get(key):
                normalized.source_signals[key] = values[key]
        return normalized

    def dedupe_key(self, rec: NormalizedRecord) -> str:
        return f"name:{rec.medium_key()}"


class WebsiteAdapter:
    source_name = "website_csv"

    def parse(self, path: Path) -> list[RawRecord]:
        headers, rows = read_csv(path)
        require_headers(
            headers,
            ("company_name", "country", "email", "message", "landing_url"),
            self.source_name,
        )
        return rows

    def normalize(self, rec: RawRecord) -> NormalizedRecord:
        values = rec.values
        if not values.get("message"):
            raise QuarantineRow("独立站留言为空")
        normalized = base_record(
            source=self.source_name,
            record_id=values.get("form_id") or f"row-{rec.row_number}",
            source_url=values.get("landing_url", ""),
            company_name=values.get("company_name", ""),
            country=country_code(values.get("country", "")),
            email=values.get("email") or None,
            phone=values.get("phone") or None,
            contact_name=values.get("contact_name") or values.get("company_name", ""),
            role=role_or_unknown(values.get("role")),
            collected_at=datetime.now(timezone.utc),
            scope=DataUsageScope.INTERNAL_USE_ONLY,
            channel=ContactChannel.EMAIL,
            buyer_type=BuyerType.UNKNOWN,
            hs_codes=[],
            product_interest=values.get("product") or None,
            shipment=None,
            raw_text=values.get("message") or None,
            hold_note=None,
            domain=normalize_domain(values.get("landing_url")),
            language=values.get("language") or None,
        )
        normalized.source_signals.update({key: values[key] for key in values if key.startswith("utm_")})
        return normalized

    def dedupe_key(self, rec: NormalizedRecord) -> str:
        return f"email:{rec.email}" if rec.email else f"name:{rec.medium_key()}"


class ManualAdapter:
    source_name = "manual_csv"

    def parse(self, path: Path) -> list[RawRecord]:
        headers, rows = read_csv(path)
        require_headers(
            headers,
            ("company_name", "country", "contact_name", "email", "phone", "overrides"),
            self.source_name,
        )
        return rows

    def normalize(self, rec: RawRecord) -> NormalizedRecord:
        values = rec.values
        email = values.get("email") or None
        phone = values.get("phone") or None
        if not email and not phone:
            raise QuarantineRow("手工导入行缺少邮箱和电话")
        return base_record(
            source=self.source_name,
            record_id=values.get("record_id") or f"row-{rec.row_number}",
            source_url=f"file://manual#{rec.row_number}",
            company_name=values.get("company_name", ""),
            country=country_code(values.get("country", "")),
            email=email,
            phone=phone,
            contact_name=values.get("contact_name", ""),
            role=role_or_unknown(values.get("role")),
            collected_at=datetime.now(timezone.utc),
            scope=DataUsageScope.INTERNAL_USE_ONLY,
            channel=ContactChannel.EMAIL if email else ContactChannel.PHONE,
            buyer_type=BuyerType.UNKNOWN,
            hs_codes=[],
            product_interest=values.get("product_interest") or None,
            shipment=None,
            raw_text=values.get("note") or None,
            hold_note=values.get("overrides") or None,
            domain=normalize_domain(values.get("domain")),
            language=values.get("language") or None,
        )

    def dedupe_key(self, rec: NormalizedRecord) -> str:
        if rec.domain:
            return f"domain:{rec.domain}"
        return f"name:{rec.medium_key()}"
