"""领域异常。调用方必须处理，不允许吞掉。"""

from __future__ import annotations

from collections.abc import Sequence


class ConfigError(Exception):
    """配置缺失或种子文件不合法。"""


class ConstraintViolation(Exception):
    """模型约束失败。携带字段、值和记录号，便于定位是哪一条数据。"""

    def __init__(
        self,
        field: str,
        message: str,
        *,
        value: object = None,
        record_id: str | None = None,
    ) -> None:
        self.field = field
        self.message = message
        self.value = value
        self.record_id = record_id
        super().__init__(
            f"{field}: {message}；record_id={record_id}；value={value!r}"
        )


class InvalidTransition(Exception):
    """非法状态转移。"""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        allowed_from: Sequence[str],
        *,
        reason: str | None = None,
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.allowed_from = [str(item) for item in allowed_from]
        self.reason = reason
        if reason is not None:
            detail = reason
        else:
            allowed = ", ".join(self.allowed_from) or "（无）"
            detail = (
                f"非法状态转移：{self.from_state} → {self.to_state}；"
                f"允许的来源状态：{allowed}"
            )
        super().__init__(detail)
