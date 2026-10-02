"""Document-scoped labels; omitted expectations differ from explicit null."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def squash(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


class GoldenSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    document_id: str
    span_kind: Literal["POSITIVE", "TRAP"]
    quote: str
    expected: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_label(self):
        allowed = {"type", "operator", "value", "unit", "period_months", "scope",
                   "required", "group_operator"}
        if not self.span_id or not self.document_id or not squash(self.quote):
            raise ValueError("label IDs and quote must be nonempty")
        if set(self.expected) - allowed:
            raise ValueError("unsupported canonical expectation field")
        return self

    def is_in(self, text: str) -> bool:
        return squash(self.quote) in squash(text)
