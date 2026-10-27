"""种子与示例配置的结构检查。"""

from __future__ import annotations

from pathlib import Path

from src.models.enums import CertificationType
from src.models.reference_seed import load_reference_seed

_ROOT = Path(__file__).resolve().parents[2]


def test_reference_seed_matches_certification_enum() -> None:
    seed = load_reference_seed()
    assert set(seed.certification_types) == {item.value for item in CertificationType}
    assert len(seed.hs_code_samples) == 3
    assert all(sample.code.isdigit() for sample in seed.hs_code_samples)


def test_example_yaml_marks_every_number() -> None:
    text = (_ROOT / "config" / "example.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(char.isdigit() for char in stripped):
            assert "示例值，上线前必须由业务确认" in stripped


def test_runtime_code_does_not_read_example_yaml() -> None:
    for path in (_ROOT / "src").rglob("*.py"):
        assert "example.yaml" not in path.read_text(encoding="utf-8")
