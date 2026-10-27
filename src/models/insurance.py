"""CIF / DDP 保险费。投保比例已确认，费率从配置读取。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from src.errors import ConfigError
from src.models.cost import COST_SUM_RELATIVE_TOLERANCE
from src.models.enums import Incoterm
from src.scoring.config import project_root

CONFIRMED_COVER_RATIO = Decimal("1.10")
_COVERED = frozenset({Incoterm.CIF, Incoterm.DDP})


@dataclass(frozen=True)
class InsuranceRule:
    cover_ratio: Decimal
    premium_rate: Decimal


def load_insurance_rule(path: Path | None = None) -> InsuranceRule:
    file_path = path or (project_root() / "config" / "quotation.yaml")
    if not file_path.is_file():
        raise ConfigError(f"缺少报价保险配置：{file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("报价保险配置不是映射")
    try:
        cover = Decimal(str(raw["invoice_cover_ratio"]))
        rate = Decimal(str(raw["premium_rate"]))
    except KeyError as exc:
        raise ConfigError(f"报价保险配置缺少 {exc.args[0]}") from exc
    if cover != CONFIRMED_COVER_RATIO:
        raise ConfigError("投保比例已确认为发票金额的 110%，不能改成别的数")
    if rate <= 0 or rate >= 1:
        raise ConfigError("premium_rate 必须大于 0 且小于 1")
    return InsuranceRule(cover_ratio=cover, premium_rate=rate)


def insurance_premium(invoice_amount: Decimal, rule: InsuranceRule | None = None) -> Decimal:
    """保险费 = 发票金额 × 110% × 费率。"""
    loaded = rule or load_insurance_rule()
    premium = invoice_amount * loaded.cover_ratio * loaded.premium_rate
    if premium <= 0:
        raise ConfigError("保险费计算结果必须大于 0")
    return premium


def assert_insurance_premium(
    incoterm: Incoterm,
    unit_price: Decimal,
    quantity: int,
    insurance: Decimal,
) -> None:
    if incoterm not in _COVERED:
        return
    expected = insurance_premium(unit_price * quantity)
    gap = abs(insurance - expected) / expected
    if insurance <= 0 or gap > COST_SUM_RELATIVE_TOLERANCE:
        raise ValueError(
            "CIF 与 DDP 的保险必须单独列在 insurance，大于 0，"
            "并按发票金额的 110% 投保后计费。"
            f"应为 {format(expected, 'f')}，实际 {format(insurance, 'f')}"
        )
