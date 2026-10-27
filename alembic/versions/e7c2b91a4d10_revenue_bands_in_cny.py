"""年营收档位改为人民币口径。旧的美元代码清空，不换算。

Revision ID: e7c2b91a4d10
Revises: c4e8a1b27d90
Create Date: 2026-10-27 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e7c2b91a4d10"
down_revision: Union[str, None] = "c4e8a1b27d90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REVENUE_CNY = (
    "annual_revenue_band IS NULL OR annual_revenue_band IN ("
    "'UNKNOWN', 'UNDER_1M_CNY', '1M_10M_CNY', '10M_50M_CNY', "
    "'50M_200M_CNY', '200M_1B_CNY', 'OVER_1B_CNY'"
    ")"
)
_REVENUE_USD = (
    "annual_revenue_band IS NULL OR annual_revenue_band IN ("
    "'UNKNOWN', 'UNDER_1M', '1M_10M', '10M_50M', '50M_200M', '200M_1B', 'OVER_1B'"
    ")"
)


def upgrade() -> None:
    op.execute(
        "UPDATE company SET annual_revenue_band = NULL "
        "WHERE annual_revenue_band IS NOT NULL "
        "AND annual_revenue_band NOT IN ("
        "'UNKNOWN', 'UNDER_1M_CNY', '1M_10M_CNY', '10M_50M_CNY', "
        "'50M_200M_CNY', '200M_1B_CNY', 'OVER_1B_CNY'"
        ")"
    )
    with op.batch_alter_table("company") as batch_op:
        batch_op.drop_constraint("ck_company_annual_revenue_band", type_="check")
        batch_op.create_check_constraint("ck_company_annual_revenue_band", _REVENUE_CNY)


def downgrade() -> None:
    op.execute(
        "UPDATE company SET annual_revenue_band = NULL "
        "WHERE annual_revenue_band IN ("
        "'UNDER_1M_CNY', '1M_10M_CNY', '10M_50M_CNY', "
        "'50M_200M_CNY', '200M_1B_CNY', 'OVER_1B_CNY'"
        ")"
    )
    with op.batch_alter_table("company") as batch_op:
        batch_op.drop_constraint("ck_company_annual_revenue_band", type_="check")
        batch_op.create_check_constraint("ck_company_annual_revenue_band", _REVENUE_USD)
