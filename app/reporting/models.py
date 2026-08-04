from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ResponsibilityLevel = Literal["not_mine", "normal", "key"]
ResponsibilityInput = Literal["not_mine", "normal", "key", "inherit"]
PeriodType = Literal["day", "week", "month", "quarter", "year"]
ActionStatus = Literal["planned", "in_progress", "completed", "cancelled"]
ActionSource = Literal["user", "ai"]


class ScopeUpdate(BaseModel):
    product_line_id: int = Field(gt=0)
    asin: Optional[str] = None
    responsibility_level: ResponsibilityInput

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class TargetCreate(BaseModel):
    period_type: PeriodType
    period_start: date
    period_end: date
    product_line_id: int = Field(gt=0)
    asin: Optional[str] = None
    metric_code: str = Field(min_length=1, max_length=100)
    target_value: float
    unit: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("asin")
    @classmethod
    def normalize_target_asin(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("period_end")
    @classmethod
    def validate_period_end(cls, value: date, info):
        start = info.data.get("period_start")
        if start and value < start:
            raise ValueError("period_end must be on or after period_start")
        return value


class ActionCreate(BaseModel):
    product_line_id: int = Field(gt=0)
    asin: Optional[str] = None
    action_date: date
    action_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5000)
    reason: Optional[str] = Field(default=None, max_length=5000)
    expected_result: Optional[str] = Field(default=None, max_length=5000)
    review_date: Optional[date] = None
    status: ActionStatus = "planned"
    actual_result: Optional[str] = Field(default=None, max_length=5000)
    source: ActionSource = "user"
    confirmed: bool = True

    @field_validator("asin")
    @classmethod
    def normalize_action_asin(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class ActionUpdate(BaseModel):
    status: Optional[ActionStatus] = None
    actual_result: Optional[str] = Field(default=None, max_length=5000)
    review_date: Optional[date] = None
    confirmed: Optional[bool] = None
