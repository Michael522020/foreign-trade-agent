"""入库前的 pydantic 校验。监听器与调用方共用这一套。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import NoReturn, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator, model_validator

from src.errors import ConstraintViolation
from src.models.cost import CostBreakdown, assert_cost_matches
from src.models.insurance import assert_insurance_premium
from src.models.enums import (
    ENABLED_INCOTERMS,
    PORT_FORBIDDEN,
    PORT_REQUIRED,
    AnnualRevenueBand,
    BuyerType,
    ContactRole,
    EmailStatus,
    EmployeeBand,
    Incoterm,
    PaymentTerms,
    SuppressionReason,
    SuppressionScope,
)

_E164 = r"^\+[1-9]\d{1,14}$"


def reject_validation(
    exc: ValidationError,
    *,
    record_id: str | None,
) -> NoReturn:
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first["loc"]) or "record"
    raise ConstraintViolation(
        loc,
        str(first["msg"]),
        value=first.get("input"),
        record_id=record_id,
    ) from exc


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field} 必须带时区")
    return value


class CompanyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    buyer_type: BuyerType
    source: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=500)
    collected_at: datetime
    hs_codes: list[str] = Field(default_factory=list)
    domain: str | None = None
    website: str | None = None
    employee_band: EmployeeBand | None = None
    annual_revenue_band: AnnualRevenueBand | None = None

    @field_validator("collected_at")
    @classmethod
    def _collected(cls, value: datetime) -> datetime:
        return _aware(value, "collected_at")

    @field_validator("country")
    @classmethod
    def _country(cls, value: str) -> str:
        upper = value.upper()
        if not upper.isalpha():
            raise ValueError("country 必须是两位字母")
        return upper

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        lowered = value.lower()
        if "://" in lowered or " " in lowered:
            raise ValueError("domain 只能是主机名，不能带协议")
        return lowered

    @field_validator("website")
    @classmethod
    def _website(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("website 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("hs_codes")
    @classmethod
    def _hs(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            code = item.strip()
            if not code.isdigit():
                raise ValueError(f"HS 编码必须是数字：{code}")
            cleaned.append(code)
        return cleaned


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    email_status: EmailStatus
    contact_channel: str | None = None
    source: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=500)
    collected_at: datetime
    role: ContactRole | None = None
    phone: str | None = None
    phone_e164: str | None = None
    whatsapp_consent: bool = False
    linkedin_url: str | None = None
    language: str | None = None
    timezone: str | None = None
    last_contacted_at: datetime | None = None

    @field_validator("collected_at", "last_contacted_at")
    @classmethod
    def _times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _aware(value, "datetime")

    @field_validator("phone_e164")
    @classmethod
    def _e164(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        import re

        if re.fullmatch(_E164, value) is None:
            raise ValueError("phone_e164 必须是 E.164，例如 +4930123456")
        return value

    @field_validator("language")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        import re

        if re.fullmatch(r"[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*", value) is None:
            raise ValueError("language 必须是 BCP 47 语言标签")
        return value

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{value}") from exc
        return value

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _reachable(self) -> Self:
        reachable_later = self.contact_channel in {"PLATFORM_INBOX", "RECORD_ONLY"}
        if self.email is None and not self.phone and not reachable_later:
            raise ValueError("联系人至少要有邮箱或电话；平台站内信除外")
        return self

    @field_validator("linkedin_url")
    @classmethod
    def _linkedin(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if "linkedin.com" not in value or not value.startswith("https://"):
            raise ValueError("linkedin_url 必须是 https 的 LinkedIn 地址")
        return value


class QuotationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inquiry_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    product_sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    incoterm: Incoterm
    destination_port: str | None = None
    payment_terms: PaymentTerms
    unit_price: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    cost_breakdown: CostBreakdown
    fx_rate: Decimal = Field(gt=0, description="1 单位报价币种兑多少人民币")
    fx_rate_source: str = Field(min_length=1, max_length=100)
    fx_rate_at: datetime
    valid_until: datetime
    created_at: datetime

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        upper = value.upper()
        if not upper.isalpha() or len(upper) != 3:
            raise ValueError("币种必须是 3 位字母")
        return upper

    @field_validator("fx_rate_at", "valid_until", "created_at")
    @classmethod
    def _times(cls, value: datetime) -> datetime:
        return _aware(value, "datetime")

    @field_validator("destination_port")
    @classmethod
    def _port(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.incoterm not in ENABLED_INCOTERMS:
            raise ValueError(f"贸易术语 {self.incoterm.value} 未启用")
        port = self.destination_port
        if self.incoterm in PORT_REQUIRED and port is None:
            raise ValueError(f"{self.incoterm.value} 必须填写目的港 destination_port")
        if self.incoterm in PORT_FORBIDDEN and port is not None:
            raise ValueError(f"{self.incoterm.value} 的 destination_port 必须为空")
        assert_insurance_premium(
            self.incoterm,
            self.unit_price,
            self.quantity,
            self.cost_breakdown.insurance,
        )
        if self.currency == "CNY" and self.fx_rate != Decimal(1):
            raise ValueError("报价币种是人民币时，fx_rate 必须是 1（1 人民币兑 1 人民币）")
        if self.valid_until <= self.created_at:
            raise ValueError("valid_until 必须晚于 created_at")
        assert_cost_matches(self.cost_breakdown, self.unit_price, self.quantity)
        return self


class SuppressionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr | None = None
    phone: str | None = None
    domain: str | None = None
    reason: SuppressionReason
    scope: SuppressionScope
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value.lower()

    @model_validator(mode="after")
    def _target(self) -> Self:
        if self.email is None and not self.phone and self.domain is None:
            raise ValueError("抑制名单至少要有 email、phone、domain 之一")
        return self
