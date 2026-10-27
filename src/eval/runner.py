"""读黄金集，算加权代价。样本不够时不输出提升百分比。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.errors import ConfigError
from src.eval.classify import classify_text, known_label
from src.scoring.config import project_root


@dataclass(frozen=True)
class CostMatrix:
    costs: dict[tuple[str, str], int]
    default_mismatch: int
    min_sample_size: int
    required_class_counts: dict[str, int]


def load_cost_matrix(path: Path | None = None) -> CostMatrix:
    file_path = path or (project_root() / "eval" / "cost_matrix.yaml")
    if not file_path.is_file():
        raise ConfigError(f"缺少代价矩阵：{file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("代价矩阵不是映射")
    pairs = raw.get("pairs")
    required = raw.get("required_class_counts")
    if not isinstance(pairs, list) or not isinstance(required, dict):
        raise ConfigError("代价矩阵缺少 pairs 或 required_class_counts")
    costs: dict[tuple[str, str], int] = {}
    for item in pairs:
        if not isinstance(item, dict):
            raise ConfigError("代价矩阵中有无法读取的一行")
        costs[(str(item["expected"]), str(item["predicted"]))] = int(item["cost"])
    return CostMatrix(
        costs=costs,
        default_mismatch=int(raw["default_mismatch"]),
        min_sample_size=int(raw["min_sample_size"]),
        required_class_counts={str(key): int(value) for key, value in required.items()},
    )


def _load_cases(suite: Path) -> list[dict[str, str]]:
    if not suite.is_dir():
        raise ConfigError(f"找不到黄金集目录：{suite}")
    cases: list[dict[str, str]] = []
    for path in sorted(suite.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                raise ConfigError(f"{path.name} 里有无法读取的样本")
            if row.get("source") != "synthetic" and row.get("source") != "real":
                raise ConfigError(f"{path.name} 的样本缺少 source")
            expected = str(row.get("expected") or "")
            if not known_label(expected):
                raise ConfigError(f"未知标签：{expected}")
            cases.append(
                {
                    "id": str(row.get("id") or path.stem),
                    "source": str(row["source"]),
                    "text": str(row.get("text") or ""),
                    "expected": expected,
                }
            )
    if not cases:
        raise ConfigError(f"{suite} 里没有样本")
    return cases


def _pair_cost(matrix: CostMatrix, expected: str, predicted: str) -> int:
    if expected == predicted:
        return 0
    return matrix.costs.get((expected, predicted), matrix.default_mismatch)


def run_suite(suite: Path, matrix: CostMatrix | None = None) -> dict[str, object]:
    loaded = matrix or load_cost_matrix()
    cases = _load_cases(suite)
    rows: list[dict[str, object]] = []
    confusion: Counter[tuple[str, str]] = Counter()
    weighted = 0
    for case in cases:
        predicted = classify_text(case["text"])
        cost = _pair_cost(loaded, case["expected"], predicted)
        weighted += cost
        confusion[(case["expected"], predicted)] += 1
        rows.append({**case, "predicted": predicted, "cost": cost})
    by_source = Counter(case["source"] for case in cases)
    real_n = by_source.get("real", 0)
    class_counts = Counter(case["expected"] for case in cases if case["source"] == "real")
    gaps = [
        f"{label} 真实样本 {class_counts.get(label, 0)}，要求 {needed}"
        for label, needed in loaded.required_class_counts.items()
        if class_counts.get(label, 0) < needed
    ]
    enough = real_n >= loaded.min_sample_size and not gaps
    return {
        "sample_size": len(cases),
        "real_sample_size": real_n,
        "synthetic_sample_size": by_source.get("synthetic", 0),
        "weighted_cost": weighted,
        "confusion": [
            {"expected": expected, "predicted": predicted, "count": count}
            for (expected, predicted), count in sorted(confusion.items())
        ],
        "cases": rows,
        "lift_percent": None,
        "conclusion": "暂不能判断" if not enough else "样本达到门槛，仍需人工看加权代价",
        "data_gap": "数据不足" if not enough else "",
        "gap_detail": gaps
        or ([f"真实样本量 {real_n}，低于 {loaded.min_sample_size}"] if real_n < loaded.min_sample_size else []),
    }


def load_failure_cases(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise ConfigError(f"找不到失败案例：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ConfigError("失败案例必须是列表")
    ranked: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ConfigError("失败案例里有无法读取的一行")
        cost = int(item["cost"])
        frequency = int(item["frequency"])
        ranked.append(
            {
                "case_id": str(item["case_id"]),
                "source": str(item.get("source") or ""),
                "note": str(item.get("note") or ""),
                "cost": cost,
                "frequency": frequency,
                "cost_times_frequency": cost * frequency,
            }
        )
    ranked.sort(key=lambda item: int(str(item["cost_times_frequency"])), reverse=True)
    return ranked[:5]
