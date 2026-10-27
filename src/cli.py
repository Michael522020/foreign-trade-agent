"""命令行。生成和评估都停在本地文件，不连接发送服务。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from src.db import make_engine, session_factory
from src.eval.report import monthly_report, render_monthly
from src.eval.runner import load_failure_cases, run_suite
from src.ingest.adapters import ADAPTERS
from src.ingest.pipeline import ingest_path
from src.models import Base
from src.outreach.draft import draft_daily
from src.scoring.config import load_scoring, project_root
from src.scoring.queue import build_daily_queue


def _session() -> Session:
    engine = make_engine()
    Base.metadata.create_all(engine)
    return session_factory(engine)()


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cmd_ingest(args: argparse.Namespace) -> int:
    adapter = ADAPTERS.get(args.source)
    if adapter is None:
        print(f"未知来源：{args.source}")
        return 2
    db = _session()
    try:
        report = ingest_path(db, adapter, Path(args.file), dry_run=args.dry_run)
        if not args.dry_run:
            db.commit()
        print(report.render())
    finally:
        db.close()
    return 0


def _cmd_queue(args: argparse.Namespace) -> int:
    config = load_scoring()
    db = _session()
    try:
        result = build_daily_queue(db, args.owner, _aware(args.date), config)
        if args.format == "table":
            print("lead_id\tscore\tconfidence\tstage")
            for lead in result.items:
                breakdown = lead.score_breakdown or {}
                print(
                    f"{lead.id}\t{breakdown.get('total', '')}\t{breakdown.get('confidence', '')}\t{lead.stage.value}"
                )
            print(f"截断条数 {result.truncated_count}")
        else:
            print(json.dumps({"count": len(result.items), "truncated_count": result.truncated_count}))
    finally:
        db.close()
    return 0


def _cmd_draft(args: argparse.Namespace) -> int:
    if args.queue != "daily":
        print("目前只支持 --queue daily")
        return 2
    config = load_scoring()
    root = project_root()
    db = _session()
    try:
        report = draft_daily(
            db,
            args.owner,
            datetime.now(timezone.utc),
            config,
            root / "outbox",
            dry_run=args.dry_run,
        )
        print(report.render())
    finally:
        db.close()
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    if args.eval_command != "run":
        print("用法：eval run --suite ... --report ...")
        return 2
    suite = Path(args.suite)
    result = run_suite(suite)
    failure_dir = suite.parent / "failure_cases" / "cases.json"
    if failure_dir.is_file():
        result["failure_top5"] = load_failure_cases(failure_dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"样本量 {result['sample_size']}")
    print(result["data_gap"] or result["conclusion"])
    print(f"报告已写入 {report_path}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    if args.report_command != "monthly":
        print("用法：report monthly --month YYYY-MM")
        return 2
    db = _session()
    try:
        payload = monthly_report(db, args.month)
    finally:
        db.close()
    root = project_root()
    path = root / "reports" / f"monthly_{args.month}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(render_monthly(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--source", required=True)
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--dry-run", action="store_true")
    ingest.set_defaults(func=_cmd_ingest)
    queue = sub.add_parser("queue")
    queue.add_argument("--owner", required=True)
    queue.add_argument("--date", required=True)
    queue.add_argument("--format", default="table")
    queue.set_defaults(func=_cmd_queue)
    draft = sub.add_parser("draft")
    draft.add_argument("--queue", required=True)
    draft.add_argument("--owner", required=True)
    draft.add_argument("--dry-run", action="store_true")
    draft.set_defaults(func=_cmd_draft)
    evaluation = sub.add_parser("eval")
    evaluation.add_argument("eval_command")
    evaluation.add_argument("--suite", required=True)
    evaluation.add_argument("--report", required=True)
    evaluation.set_defaults(func=_cmd_eval)
    report = sub.add_parser("report")
    report.add_argument("report_command")
    report.add_argument("--month", required=True)
    report.set_defaults(func=_cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
