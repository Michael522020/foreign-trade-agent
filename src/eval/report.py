"""月报。没有基线、样本不足时只写「数据不足」，不写提升百分比。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.parties import Lead


def monthly_report(session: Session, month: str) -> dict[str, object]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    leads = session.scalars(select(Lead)).all()
    in_month = [
        lead
        for lead in leads
        if lead.created_at is not None and start <= lead.created_at < end
    ]
    return {
        "month": month,
        "baseline": None,
        "current_lead_count": len(in_month),
        "reply_rate": None,
        "lift_percent": None,
        "weighted_confusion": [],
        "failure_top5": [],
        "data_gap": "数据不足",
        "conclusion": "暂不能判断",
        "note": "没有改造前基线，也没有达到评估门槛的真实外呼样本，因此不计算回复率，不写提升百分比。",
    }


def render_monthly(report: dict[str, object]) -> str:
    lines = [
        f"月份 {report['month']}",
        "数据不足",
        str(report["note"]),
        f"本月线索数 {report['current_lead_count']}",
        "结论：暂不能判断",
    ]
    return "\n".join(lines)
