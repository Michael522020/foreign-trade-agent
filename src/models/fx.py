"""汇率方向：1 单位报价币种兑多少人民币。"""

from __future__ import annotations

from decimal import Decimal

from src.errors import ConstraintViolation


def foreign_to_cny(amount: Decimal, fx_rate: Decimal) -> Decimal:
    """人民币金额 = 外币金额 × fx_rate。"""
    if amount < 0:
        raise ConstraintViolation("amount", "外币金额不能为负", value=amount)
    if fx_rate <= 0:
        raise ConstraintViolation("fx_rate", "汇率必须大于 0", value=fx_rate)
    return amount * fx_rate
