"""读取发送闸门配置。缺项就拒绝启动。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from src.errors import ConfigError
from src.scoring.config import project_root


@dataclass(frozen=True)
class GateConfig:
    auth_ready: bool
    daily_cap: int
    complaint_block: Decimal
    complaint_warn: Decimal
    bounce_block: Decimal
    freemail_domains: frozenset[str]
    blocked_countries: frozenset[str]
    lia_required_countries: frozenset[str]
    lia_recorded_countries: frozenset[str]
    sanction_list_loaded: bool
    sanction_names: frozenset[str]
    config_hash: str


def _codes(raw: object, label: str) -> frozenset[str]:
    if not isinstance(raw, list):
        raise ConfigError(f"{label} 必须是列表")
    codes: set[str] = set()
    for item in raw:
        code = str(item).strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ConfigError(f"{label} 里有无法识别的国家代码：{item}")
        codes.add(code)
    return frozenset(codes)


def _domains(raw: object) -> frozenset[str]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("freemail_domains 必须是非空列表")
    return frozenset(str(item).strip().lower() for item in raw if str(item).strip())


def load_gate_config(path: Path | None = None) -> GateConfig:
    file_path = path or (project_root() / "config" / "compliance.yaml")
    if not file_path.is_file():
        raise ConfigError(f"缺少合规配置：{file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("合规配置不是映射")
    auth = raw.get("auth")
    quota = raw.get("quota")
    rates = raw.get("rates")
    sanctions = raw.get("sanctions")
    if not isinstance(auth, dict) or not isinstance(quota, dict):
        raise ConfigError("auth 或 quota 配置缺失")
    if not isinstance(rates, dict) or not isinstance(sanctions, dict):
        raise ConfigError("rates 或 sanctions 配置缺失")
    for key in ("spf_ready", "dkim_ready", "dmarc_aligned"):
        if not isinstance(auth.get(key), bool):
            raise ConfigError(f"auth.{key} 必须是布尔值")
    loaded = sanctions.get("loaded")
    if not isinstance(loaded, bool):
        raise ConfigError("sanctions.loaded 必须是布尔值")
    entities = sanctions.get("entities")
    if not isinstance(entities, list):
        raise ConfigError("sanctions.entities 必须是列表")
    names = frozenset(str(item).strip().casefold() for item in entities if str(item).strip())
    payload = {
        "auth": auth,
        "quota": quota,
        "rates": rates,
        "freemail_domains": raw.get("freemail_domains"),
        "blocked_countries": raw.get("blocked_countries"),
        "lia_required_countries": raw.get("lia_required_countries"),
        "lia_recorded_countries": raw.get("lia_recorded_countries"),
        "sanctions": sanctions,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return GateConfig(
        auth_ready=bool(auth["spf_ready"] and auth["dkim_ready"] and auth["dmarc_aligned"]),
        daily_cap=int(quota["daily_cap"]),
        complaint_block=Decimal(str(rates["complaint_block"])),
        complaint_warn=Decimal(str(rates["complaint_warn"])),
        bounce_block=Decimal(str(rates["bounce_block"])),
        freemail_domains=_domains(raw.get("freemail_domains")),
        blocked_countries=_codes(raw.get("blocked_countries"), "blocked_countries"),
        lia_required_countries=_codes(raw.get("lia_required_countries"), "lia_required_countries"),
        lia_recorded_countries=_codes(raw.get("lia_recorded_countries"), "lia_recorded_countries"),
        sanction_list_loaded=loaded,
        sanction_names=names,
        config_hash=digest,
    )
