"""评估在样本不足时拒绝写提升百分比。"""

from __future__ import annotations

from pathlib import Path

from src.eval.report import monthly_report, render_monthly
from src.eval.runner import load_failure_cases, run_suite

_ROOT = Path(__file__).resolve().parents[2]


def test_golden_set_refuses_a_lift_percentage() -> None:
    report = run_suite(_ROOT / "eval" / "golden_set")
    assert report["lift_percent"] is None
    assert report["data_gap"] == "数据不足"
    assert report["conclusion"] == "暂不能判断"
    assert report["real_sample_size"] == 0
    assert int(report["weighted_cost"]) > 0
    text = str(report)
    assert "%" not in str(report["conclusion"])
    assert "50" in " ".join(str(item) for item in report["gap_detail"])
    del text


def test_failure_cases_sort_by_cost_times_frequency() -> None:
    ranked = load_failure_cases(_ROOT / "eval" / "failure_cases" / "cases.json")
    scores = [int(item["cost_times_frequency"]) for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100


def test_monthly_report_says_data_is_missing(session) -> None:
    payload = monthly_report(session, "2026-10")
    text = render_monthly(payload)
    assert "数据不足" in text
    assert "暂不能判断" in text
    assert payload["lift_percent"] is None
    assert payload["reply_rate"] is None
    assert "%" not in text
