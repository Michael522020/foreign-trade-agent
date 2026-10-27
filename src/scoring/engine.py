"""确定性评分。缺数据就跳过该维度，不用行业均值填。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src.errors import ConstraintViolation
from src.models.enums import AnnualRevenueBand, ContactRole, EmailStatus, EmployeeBand, LeadStage
from src.models.parties import Lead
from src.models.state_machine import LeadEvent, transition
from src.scoring.config import DIMENSIONS, ScoringConfig

_DECISION_ROLES = frozenset(
    {
        ContactRole.PURCHASING_MANAGER,
        ContactRole.SOURCING_SPECIALIST,
        ContactRole.OWNER_FOUNDER,
    }
)


@dataclass
class ScoreResult:
    total: Decimal
    breakdown: dict[str, Decimal]
    bands: dict[str, Decimal]
    confidence: Decimal
    reasons: list[str]
    missing: list[str]
    pain_hypothesis: str
    points: dict[str, Decimal] = field(default_factory=dict)

    def stored_total(self) -> int:
        return int(self.total.to_integral_value())

    def as_dict(self) -> dict[str, object]:
        return {
            "total": str(self.total),
            "confidence": str(self.confidence),
            "breakdown": {key: str(value) for key, value in self.breakdown.items()},
            "bands": {key: str(value) for key, value in self.bands.items()},
            "reasons": list(self.reasons),
            "missing": list(self.missing),
            "pain_hypothesis": self.pain_hypothesis,
        }


def _window_band(days: int, config: ScoringConfig) -> Decimal:
    if days <= config.window_recent_days:
        return config.window_factors["within_90_days"]
    if days <= config.window_mid_days:
        return config.window_factors["within_180_days"]
    if days <= config.window_year_days:
        return config.window_factors["within_365_days"]
    return config.window_factors["older"]


def _switch_band(share: Decimal, config: ScoringConfig) -> Decimal:
    if share < config.switch_open_below:
        return config.switch_factors["open"]
    if share > config.switch_closed_above:
        return config.switch_factors["closed"]
    return config.switch_factors["mid"]


def score_lead(session: Session, lead: Lead, config: ScoringConfig, as_of: datetime) -> ScoreResult:
    company = lead.company
    contact = lead.contact
    if company is None or contact is None:
        raise ConstraintViolation("lead", "评分前必须能读到企业和联系人", record_id=lead.id)
    if contact.role is None:
        contact.role = ContactRole.UNKNOWN
    if not company.employee_band:
        company.employee_band = EmployeeBand.UNKNOWN.value
    if not company.annual_revenue_band:
        company.annual_revenue_band = AnnualRevenueBand.UNKNOWN.value
    bands: dict[str, Decimal] = {}
    missing: list[str] = []
    reasons: list[str] = []
    hs_codes = set(company.hs_codes or [])
    if not hs_codes:
        missing.append("demand_fit")
    else:
        overlap = hs_codes & set(config.our_hs_codes)
        bands["demand_fit"] = Decimal(1) if overlap else Decimal(0)
        if overlap:
            reasons.append(f"进口 HS 与我方品类重合 {len(overlap)} 个")
        else:
            reasons.append("进口 HS 与我方品类没有重合")
    if company.last_ship_date is None:
        missing.append("window")
    else:
        days = (as_of - company.last_ship_date).days
        bands["window"] = _window_band(days, config)
        reasons.append(f"距最近一批进口 {days} 天，窗口系数 {bands['window']}")
    if company.supplier_top3_share is None:
        missing.append("switchability")
    else:
        share = Decimal(company.supplier_top3_share)
        bands["switchability"] = _switch_band(share, config)
        percent = (share * Decimal(100)).quantize(Decimal("1"))
        if share > config.switch_closed_above:
            reasons.append(f"前 3 大供应商占比 {percent}%，供应关系稳定，切入难度高")
        else:
            reasons.append(f"前 3 大供应商占比 {percent}%，正在多方比价")
    if contact.role is None or contact.role == ContactRole.UNKNOWN:
        missing.append("role_access")
    else:
        personal = Decimal(1) if not contact.is_role_based else Decimal("0.4")
        decision = Decimal(1) if contact.role in _DECISION_ROLES else Decimal("0.5")
        bands["role_access"] = min(Decimal(1), personal * decision)
        reasons.append(f"联系人角色为 {contact.role.value}")
    quantity = company.import_count or 0
    if quantity <= 0:
        missing.append("scale_fit")
    else:
        # 用进口批次数对照月产能的数量级，不把金额当成客户价值。
        if Decimal(quantity) * config.scale_batch_factor < config.moq:
            bands["scale_fit"] = Decimal("0.3")
        elif quantity > config.monthly_capacity:
            bands["scale_fit"] = Decimal("0.4")
        else:
            bands["scale_fit"] = Decimal(1)
        reasons.append(f"已记录进口 {quantity} 批")
    if contact.email is None and not contact.whatsapp_consent:
        missing.append("reachability")
    else:
        status = contact.email_status
        factor = config.reachability.get(status.value if isinstance(status, EmailStatus) else "unknown", Decimal(0))
        if contact.whatsapp_consent:
            factor = min(Decimal(1), factor + config.reachability["whatsapp_bonus"])
        bands["reachability"] = factor
        reasons.append(f"邮箱状态 {status.value if isinstance(status, EmailStatus) else status}")
    points = {name: bands[name] * config.weights[name] for name in bands}
    total = sum(points.values(), Decimal(0))
    used_weight = sum((config.weights[name] for name in bands), Decimal(0))
    confidence = Decimal(0) if used_weight == 0 else used_weight / Decimal(100)
    for name in DIMENSIONS:
        if name not in bands and name not in missing:
            missing.append(name)
    pain = "；".join(reasons) if reasons else "缺少可引用的采购证据"
    result = ScoreResult(
        total=total,
        breakdown=points,
        bands=bands,
        confidence=confidence,
        reasons=reasons,
        missing=missing,
        pain_hypothesis=pain,
        points=points,
    )
    lead.icp_score = result.stored_total()
    lead.score_breakdown = result.as_dict()
    if lead.stage == LeadStage.RAW:
        transition(lead, LeadEvent.ENRICH)
        session.flush()
        transition(lead, LeadEvent.SCORE)
    elif lead.stage == LeadStage.ENRICHED:
        transition(lead, LeadEvent.SCORE)
    return result
