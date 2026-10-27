"""读取 seeds/reference.yaml。只校验结构，不写入客户。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.errors import ConfigError
from src.models.enums import CertificationType


@dataclass(frozen=True)
class HsCodeSample:
    code: str
    description_zh: str


@dataclass(frozen=True)
class ReferenceSeed:
    certification_types: tuple[str, ...]
    hs_code_samples: tuple[HsCodeSample, ...]


def default_seed_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "seeds" / "reference.yaml"
        if candidate.is_file():
            return candidate
    raise ConfigError("找不到 seeds/reference.yaml")


def load_reference_seed(path: Path | None = None) -> ReferenceSeed:
    target = default_seed_path() if path is None else path
    if not target.is_file():
        raise ConfigError(f"缺少种子文件：{target}")
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigError(f"种子文件必须是映射：{target}")
    raw_types = loaded.get("certification_types")
    raw_codes = loaded.get("hs_code_samples")
    if not isinstance(raw_types, list) or not isinstance(raw_codes, list):
        raise ConfigError(f"种子文件缺少 certification_types 或 hs_code_samples：{target}")
    types = tuple(str(item) for item in raw_types)
    expected = {item.value for item in CertificationType}
    if set(types) != expected:
        missing = sorted(expected - set(types))
        extra = sorted(set(types) - expected)
        raise ConfigError(f"认证类型与枚举不一致；缺少 {missing}；多余 {extra}")
    if len(raw_codes) != 3:
        raise ConfigError(f"HS 编码样例必须是 3 条，实际 {len(raw_codes)} 条")
    samples: list[HsCodeSample] = []
    for item in raw_codes:
        if not isinstance(item, dict):
            raise ConfigError(f"HS 编码样例必须是映射：{item!r}")
        code = str(item.get("code", "")).strip()
        description = str(item.get("description_zh", "")).strip()
        if not code.isdigit() or not 4 <= len(code) <= 10:
            raise ConfigError(f"HS 编码样例格式不对：{code}")
        if not description:
            raise ConfigError(f"HS 编码样例缺少中文说明：{code}")
        samples.append(HsCodeSample(code=code, description_zh=description))
    return ReferenceSeed(certification_types=types, hs_code_samples=tuple(samples))
