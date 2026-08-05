from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ResponsibilityLevel = Literal["not_mine", "normal", "key"]
WindowCode = Literal["day", "3d", "7d", "14d", "month"]


class ListingScopeUpdate(BaseModel):
    listing_id: int = Field(gt=0)
    responsibility_level: ResponsibilityLevel
    product_line: Optional[str] = Field(default=None, max_length=200)

    @field_validator("product_line")
    @classmethod
    def normalize_product_line(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class NoteSave(BaseModel):
    product_line: str = Field(min_length=1, max_length=200)
    window_code: WindowCode
    period_key: str = Field(min_length=1, max_length=100)
    content: str = Field(default="", max_length=20000)

    @field_validator("product_line", "period_key")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized
