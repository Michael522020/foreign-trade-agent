"""lock confirmed business decisions

Revision ID: c4e8a1b27d90
Revises: 1ad1b98dc5a3
Create Date: 2026-10-27 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4e8a1b27d90"
down_revision: Union[str, None] = "1ad1b98dc5a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPLOYEE = (
    "employee_band IS NULL OR employee_band IN ("
    "'UNKNOWN', '1-10', '11-50', '51-200', '201-500', '501-1000', "
    "'1001-5000', '5001-10000', '10001+'"
    ")"
)
_REVENUE = (
    "annual_revenue_band IS NULL OR annual_revenue_band IN ("
    "'UNKNOWN', 'UNDER_1M', '1M_10M', '10M_50M', '50M_200M', '200M_1B', 'OVER_1B'"
    ")"
)
_OUTCOME = (
    "outcome IS NULL OR outcome IN ("
    "'NO_REPLY', 'REPLIED', 'POSITIVE', 'OBJECTION', 'MEETING_SET', "
    "'NOT_INTERESTED', 'NURTURE', 'BOUNCED', 'UNSUBSCRIBED', 'WRONG_CONTACT'"
    ")"
)
_INSURANCE = (
    "incoterm NOT IN ('CIF', 'DDP') "
    "OR CAST(json_extract(cost_breakdown, '$.insurance') AS NUMERIC) > 0"
)


def upgrade() -> None:
    with op.batch_alter_table("company") as batch_op:
        batch_op.create_check_constraint("ck_company_employee_band", _EMPLOYEE)
        batch_op.create_check_constraint("ck_company_annual_revenue_band", _REVENUE)
    with op.batch_alter_table("interaction") as batch_op:
        batch_op.create_check_constraint("ck_interaction_outcome", _OUTCOME)
    with op.batch_alter_table("quotation") as batch_op:
        batch_op.create_check_constraint("ck_quotation_cif_ddp_insurance", _INSURANCE)


def downgrade() -> None:
    with op.batch_alter_table("quotation") as batch_op:
        batch_op.drop_constraint("ck_quotation_cif_ddp_insurance", type_="check")
    with op.batch_alter_table("interaction") as batch_op:
        batch_op.drop_constraint("ck_interaction_outcome", type_="check")
    with op.batch_alter_table("company") as batch_op:
        batch_op.drop_constraint("ck_company_annual_revenue_band", type_="check")
        batch_op.drop_constraint("ck_company_employee_band", type_="check")
