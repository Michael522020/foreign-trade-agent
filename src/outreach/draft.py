"""把通过校验的草稿写到 outbox。校验失败的不写正文文件。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.errors import ConfigError, ConstraintViolation
from src.logging_config import current_trace_id
from src.models.base import new_id
from src.models.catalog import Certification
from src.models.compliance import Interaction
from src.models.enums import CertificationStatus, CertificationType, Direction, LeadStage
from src.models.parties import Lead
from src.outreach.compose import (
    approved_facts,
    compose_body,
    compose_subject,
    resolve_language,
    why_this_works_zh,
)
from src.outreach.validate import validate_with_one_compress
from src.scoring.config import ScoringConfig
from src.scoring.queue import build_daily_queue

_log = structlog.get_logger("outreach")


@dataclass
class DraftReport:
    written: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"生成草稿 {len(self.written)}", f"跳过 {len(self.skipped)}"]
        for item in self.skipped:
            lines.append(f"跳过 {item['lead_id']}：{item['skip_reason']}")
        return "\n".join(lines)


def _confidence(lead: Lead) -> str:
    raw = (lead.score_breakdown or {}).get("confidence", "0")
    return str(raw)


def _cert_allowed(session: Session, sku: str | None) -> bool:
    if not sku:
        return False
    rows = session.scalars(
        select(Certification).where(
            Certification.type == CertificationType.CE,
            Certification.status == CertificationStatus.VALID,
        )
    ).all()
    return any(sku in (row.covered_skus or []) for row in rows)


def _skip(report: DraftReport, lead_id: str, reason: str) -> None:
    report.skipped.append({"lead_id": lead_id, "skip_reason": reason})
    _log.info("draft_skipped", lead_id=lead_id, trace_id=current_trace_id(), skip_reason=reason)


def _sequence_step(session: Session, lead_id: str) -> int | None:
    rows = session.scalars(select(Interaction).where(Interaction.lead_id == lead_id)).all()
    if any(row.direction == Direction.INBOUND for row in rows):
        return None
    outbound = sum(1 for row in rows if row.direction == Direction.OUTBOUND)
    return outbound + 1


def draft_daily(
    session: Session,
    owner: str,
    as_of: datetime,
    config: ScoringConfig,
    outbox: Path,
    *,
    dry_run: bool,
    sku: str | None = None,
) -> DraftReport:
    report = DraftReport()
    queue = build_daily_queue(session, owner, as_of, config)
    facts = approved_facts(config)
    cert_ok = _cert_allowed(session, sku)
    folder = outbox / as_of.date().isoformat()
    for lead in queue.items:
        contact = lead.contact
        if lead.stage != LeadStage.SCORED:
            _skip(report, lead.id, "线索不在 SCORED")
            continue
        if contact is None or contact.role is None or contact.role.value == "UNKNOWN":
            _skip(report, lead.id, "角色不明")
            continue
        try:
            confidence = Decimal(_confidence(lead))
        except InvalidOperation as exc:
            raise ConstraintViolation(
                "confidence",
                "置信度无法读取",
                value=_confidence(lead),
                record_id=lead.id,
            ) from exc
        if confidence < config.min_confidence:
            _skip(report, lead.id, "置信度不足")
            continue
        step = _sequence_step(session, lead.id)
        if step is None:
            _skip(report, lead.id, "已有回复，序列停止")
            continue
        if step > len(config.sequence_offsets_days):
            _skip(report, lead.id, "序列已结束")
            continue
        try:
            language = resolve_language(contact.language)
        except ConfigError as exc:
            _skip(report, lead.id, str(exc))
            continue
        subject = compose_subject(language, config)
        body = compose_body(language, config, contact.full_name)
        body, reasons = validate_with_one_compress(
            subject,
            body,
            facts,
            first_touch=step == 1,
            cert_allowed=cert_ok,
        )
        if reasons:
            _skip(report, lead.id, "，".join(reasons))
            continue
        payload = {
            "task_id": new_id(),
            "lead_id": lead.id,
            "status": "pending_review",
            "channel": "EMAIL",
            "language": language,
            "subject": subject,
            "body": body,
            "why_this_works_zh": why_this_works_zh(language),
            "sequence": {
                "step": step,
                "offset_days": config.sequence_offsets_days[step - 1],
                "offsets_days": list(config.sequence_offsets_days),
            },
            "approved_facts": [
                {"value": fact.value, "unit": fact.unit, "src": fact.src} for fact in facts
            ],
        }
        report.written.append(lead.id)
        if dry_run:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{lead.id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log.info("draft_written", lead_id=lead.id, trace_id=current_trace_id(), status="pending_review")
    if report.skipped and not dry_run:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "skipped.json").write_text(
            json.dumps(report.skipped, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report
