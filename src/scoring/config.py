"""读取评分权重。总和不等于 100 就拒绝启动，不偷偷归一化。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from src.errors import ConfigError

DIMENSIONS = (
    "demand_fit",
    "window",
    "switchability",
    "role_access",
    "scale_fit",
    "reachability",
)


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, Decimal]
    window_recent_days: int
    window_mid_days: int
    window_year_days: int
    window_factors: dict[str, Decimal]
    scale_batch_factor: Decimal
    switch_open_below: Decimal
    switch_closed_above: Decimal
    switch_factors: dict[str, Decimal]
    reachability: dict[str, Decimal]
    daily_cap: int
    new_customer_cap: int
    min_confidence: Decimal
    our_hs_codes: frozenset[str]
    moq: Decimal
    monthly_capacity: Decimal
    seller_name: str
    category_en: str
    category_pt: str
    category_de: str
    facts: dict[str, dict[str, object]]
    sequence_offsets_days: tuple[int, ...]


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("找不到项目根目录")


def _decimal_map(raw: object, label: str) -> dict[str, Decimal]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} 必须是映射")
    return {str(key): Decimal(str(value)) for key, value in raw.items()}


def load_scoring(
    scoring_path: Path | None = None,
    product_path: Path | None = None,
) -> ScoringConfig:
    root = project_root()
    scoring_file = scoring_path or (root / "config" / "scoring.yaml")
    product_file = product_path or (root / "config" / "product.yaml")
    if not scoring_file.is_file():
        raise ConfigError(f"缺少评分配置：{scoring_file}")
    if not product_file.is_file():
        raise ConfigError(f"缺少产品配置：{product_file}")
    scoring = yaml.safe_load(scoring_file.read_text(encoding="utf-8"))
    product = yaml.safe_load(product_file.read_text(encoding="utf-8"))
    if not isinstance(scoring, dict) or not isinstance(product, dict):
        raise ConfigError("评分或产品配置不是映射")
    weights = _decimal_map(scoring.get("weights"), "weights")
    missing = [name for name in DIMENSIONS if name not in weights]
    if missing:
        raise ConfigError(f"评分权重缺少维度：{', '.join(missing)}")
    total = sum((weights[name] for name in DIMENSIONS), Decimal(0))
    if total != Decimal(100):
        raise ConfigError(f"评分权重之和必须等于 100，实际 {total}")
    queue = scoring.get("queue")
    scale = product.get("scale")
    if not isinstance(queue, dict) or not isinstance(scale, dict):
        raise ConfigError("queue 或 scale 配置缺失")
    facts = product.get("facts")
    if not isinstance(facts, dict):
        raise ConfigError("product.yaml 缺少 facts")
    offsets = product.get("sequence_offsets_days")
    if not isinstance(offsets, list) or not offsets:
        raise ConfigError("sequence_offsets_days 必须是非空列表")
    hs_codes = product.get("our_hs_codes")
    if not isinstance(hs_codes, list):
        raise ConfigError("our_hs_codes 必须是列表")
    window_days = scoring.get("window_days")
    if not isinstance(window_days, dict):
        raise ConfigError("window_days 配置缺失")
    windows = _decimal_map(scoring.get("window_factors"), "window_factors")
    switches = _decimal_map(scoring.get("switch_factors"), "switch_factors")
    switch_thresholds = _decimal_map(scoring.get("switch_thresholds"), "switch_thresholds")
    return ScoringConfig(
        weights=weights,
        window_recent_days=int(window_days["recent"]),
        window_mid_days=int(window_days["mid"]),
        window_year_days=int(window_days["year"]),
        window_factors=windows,
        scale_batch_factor=Decimal(str(scoring["scale_batch_factor"])),
        switch_open_below=switch_thresholds["open_below"],
        switch_closed_above=switch_thresholds["closed_above"],
        switch_factors=switches,
        reachability=_decimal_map(scoring.get("reachability"), "reachability"),
        daily_cap=int(queue["daily_cap"]),
        new_customer_cap=int(queue["new_customer_cap"]),
        min_confidence=Decimal(str(queue["min_confidence"])),
        our_hs_codes=frozenset(str(code) for code in hs_codes),
        moq=Decimal(str(scale["moq"])),
        monthly_capacity=Decimal(str(scale["monthly_capacity"])),
        seller_name=str(product.get("seller_name") or ""),
        category_en=str(product.get("category_en") or ""),
        category_pt=str(product.get("category_pt") or ""),
        category_de=str(product.get("category_de") or ""),
        facts={str(key): value for key, value in facts.items() if isinstance(value, dict)},
        sequence_offsets_days=tuple(int(item) for item in offsets),
    )
