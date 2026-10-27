"""报价成本快照。

加总口径（金额均为报价币种、且对应该报价数量的行总额）：

    各项成本之和 - export_rebate_adjustment
    × (1 + fx_buffer_rate)
    = floor_price
    + target_margin
    = extended_total

extended_total 必须等于 unit_price × quantity，相对容差 0.5%。
容差来自 P0 任务书，不做成可调配置，避免把闸门调松。
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.errors import ConstraintViolation

COST_SUM_RELATIVE_TOLERANCE = Decimal("0.005")
COMPUTED_COST_KEYS = frozenset({"floor_price", "extended_total"})


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_cost: Decimal = Field(ge=0)
    labor_cost: Decimal = Field(ge=0)
    packaging_cost: Decimal = Field(ge=0)
    inland_freight: Decimal = Field(ge=0)
    export_clearance_fee: Decimal = Field(ge=0)
    main_freight: Decimal = Field(ge=0)
    insurance: Decimal = Field(ge=0)
    bank_charge: Decimal = Field(ge=0)
    certification_amortized: Decimal = Field(ge=0)
    export_rebate_adjustment: Decimal = Field(ge=0)
    fx_buffer_rate: Decimal = Field(ge=0)
    target_margin: Decimal


def _subtotal(breakdown: CostBreakdown) -> Decimal:
    return (
        breakdown.material_cost
        + breakdown.labor_cost
        + breakdown.packaging_cost
        + breakdown.inland_freight
        + breakdown.export_clearance_fee
        + breakdown.main_freight
        + breakdown.insurance
        + breakdown.bank_charge
        + breakdown.certification_amortized
        - breakdown.export_rebate_adjustment
    )


def floor_price(breakdown: CostBreakdown) -> Decimal:
    return _subtotal(breakdown) * (Decimal(1) + breakdown.fx_buffer_rate)


def extended_total(breakdown: CostBreakdown) -> Decimal:
    return floor_price(breakdown) + breakdown.target_margin


def assert_cost_matches(
    breakdown: CostBreakdown,
    unit_price: Decimal,
    quantity: int,
) -> None:
    if quantity <= 0:
        raise ConstraintViolation("quantity", "数量必须大于 0", value=quantity)
    if unit_price <= 0:
        raise ConstraintViolation("unit_price", "单价必须大于 0", value=unit_price)
    expected = unit_price * quantity
    actual = extended_total(breakdown)
    relative = abs(actual - expected) / abs(expected)
    if relative > COST_SUM_RELATIVE_TOLERANCE:
        raise ConstraintViolation(
            "cost_breakdown",
            (
                f"成本加总 {actual} 与单价×数量 {expected} 的相对偏差 {relative} "
                f"超过容差 {COST_SUM_RELATIVE_TOLERANCE}"
            ),
            value=actual,
        )


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def snapshot_cost(breakdown: CostBreakdown) -> dict[str, str]:
    raw = breakdown.model_dump()
    stored = {key: _format_decimal(raw[key]) for key in raw}
    stored["floor_price"] = _format_decimal(floor_price(breakdown))
    stored["extended_total"] = _format_decimal(extended_total(breakdown))
    return stored


def parse_cost(payload: object) -> CostBreakdown:
    if not isinstance(payload, dict):
        raise ConstraintViolation(
            "cost_breakdown",
            "成本明细必须是对象",
            value=payload,
        )
    cleaned = {
        key: value
        for key, value in payload.items()
        if key not in COMPUTED_COST_KEYS
    }
    return CostBreakdown.model_validate(cleaned)
