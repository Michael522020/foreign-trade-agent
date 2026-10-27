"""海关样本去重、隔离、抑制。公司名来自 tests/fixtures，source=synthetic。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingest.adapters import ADAPTERS
from src.ingest.normalize import normalize_company_name
from src.ingest.pipeline import ingest_path
from src.ingest.records import IngestRejected
from src.ingest.tables import CustomsShipment, IngestDrop, QuarantineItem
from src.models.base import new_id, utcnow
from src.models.compliance import Suppression
from src.models.enums import SuppressionReason, SuppressionScope
from src.models.parties import Company

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "customs_sample.csv"


def _mx(_domain: str) -> bool:
    return True


def test_suffix_variants_share_one_normalized_name() -> None:
    left = normalize_company_name("ABC Trading Co., Ltd")
    right = normalize_company_name("abc trading limited")
    assert left == right == "abc trading"


def test_five_customs_rows_become_one_company(session: Session) -> None:
    report = ingest_path(session, ADAPTERS["customs_csv"], _FIXTURE, mx_lookup=_mx)
    assert report.parsed == 5
    assert report.passed == 5
    assert report.quarantined == 0
    assert report.deduped == 4
    assert report.suppressed == 0
    assert report.companies_created == 1
    company = session.scalars(select(Company)).one()
    assert company.import_count == 5
    assert company.last_ship_date is not None
    assert company.last_ship_date.date().isoformat() == "2026-08-18"
    assert session.scalar(select(func.count()).select_from(CustomsShipment)) == 5
    again = ingest_path(session, ADAPTERS["customs_csv"], _FIXTURE, mx_lookup=_mx)
    assert again.deduped == 5
    assert session.scalar(select(func.count()).select_from(Company)) == 1
    assert session.scalar(select(func.count()).select_from(CustomsShipment)) == 5


def test_dry_run_keeps_counts_and_rolls_back(session: Session) -> None:
    report = ingest_path(
        session, ADAPTERS["customs_csv"], _FIXTURE, mx_lookup=_mx, dry_run=True
    )
    assert "解析行数 5" in report.render()
    assert "去重合并数 4" in report.render()
    assert session.scalar(select(func.count()).select_from(Company)) == 0


def test_missing_hs_code_is_quarantined(session: Session, tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    header = _FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(
        header
        + '\nsynthetic,"SYN-IMPORTER-B Co., Ltd",1 Synthetic Road,DE,,chairs,1,pcs,10,2026-02-01,SYN-SUPPLIER-9,CN,DEHAM,SYN-BL-9,,\n',
        encoding="utf-8",
    )
    report = ingest_path(session, ADAPTERS["customs_csv"], path, mx_lookup=_mx)
    assert report.quarantined == 1
    assert report.passed == 0
    assert session.scalar(select(func.count()).select_from(QuarantineItem)) == 1
    assert session.scalar(select(func.count()).select_from(Company)) == 0


def test_suppressed_email_is_dropped_before_insert(session: Session, tmp_path: Path) -> None:
    session.add(
        Suppression(
            id=new_id(),
            email="buyer@syn-importer-a.example",
            reason=SuppressionReason.UNSUBSCRIBED,
            scope=SuppressionScope.GLOBAL,
            created_at=utcnow(),
        )
    )
    session.flush()
    path = tmp_path / "one.csv"
    lines = _FIXTURE.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n" + lines[1] + "\n", encoding="utf-8")
    report = ingest_path(session, ADAPTERS["customs_csv"], path, mx_lookup=_mx)
    assert report.suppressed == 1
    assert report.passed == 0
    drop = session.scalars(select(IngestDrop)).one()
    assert drop.drop_reason == "SUPPRESSED"
    assert session.scalar(select(func.count()).select_from(Company)) == 0


def test_manual_missing_column_rejects_the_batch(session: Session, tmp_path: Path) -> None:
    path = tmp_path / "manual.csv"
    path.write_text("company_name,country,contact_name,email,phone\n", encoding="utf-8")
    with pytest.raises(IngestRejected, match="overrides"):
        ADAPTERS["manual_csv"].parse(path)
    assert session.scalar(select(func.count()).select_from(Company)) == 0
