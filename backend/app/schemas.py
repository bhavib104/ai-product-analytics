"""API request/response schemas."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    conversation_id: str | None = None


class SqlRequest(BaseModel):
    sql: str = Field(min_length=5, max_length=8000)


class Stage(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=80)
    event_name: str = Field(min_length=1, max_length=80)


class FunnelAnalyzeRequest(BaseModel):
    funnel_id: str = "default"
    stages: list[Stage] | None = None
    name: str = "Custom funnel"
    start_date: date | None = None
    end_date: date | None = None
    window_days: int = Field(default=14, ge=1, le=90)
    group_by: Literal["channel", "device", "country", "plan", "segment"] | None = None
    compare_period: bool = True

    @field_validator("stages")
    @classmethod
    def _stages(cls, value):
        if value is not None and len(value) < 2:
            raise ValueError("A funnel needs at least two stages.")
        return value


class CreateFunnelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    stages: list[Stage]
    window_days: int = Field(default=14, ge=1, le=90)

    @field_validator("stages")
    @classmethod
    def _stages(cls, value):
        if len(value) < 2:
            raise ValueError("A funnel needs at least two stages.")
        return value


class ReportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question: str | None = None
    interaction_id: str | None = None
    query_id: str | None = None


class IngestRequest(BaseModel):
    force_generate: bool = False
