from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProbeDefinition:
    key: str
    category: str
    label: str
    method_path: str
    purpose: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass
class ProbeResult:
    key: str
    category: str
    label: str
    method_path: str
    status: str
    duration_ms: int = 0
    sample_count: int | None = None
    fields: list[str] = field(default_factory=list)
    parameters_used: dict[str, Any] = field(default_factory=dict)
    required_parameters: list[str] = field(default_factory=list)
    error_type: str | None = None
    message: str | None = None
    sample_file: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    run_id: str
    started_at: str
    finished_at: str
    settings: dict[str, object]
    sdk_version: str | None
    summary: dict[str, int]
    results: list[ProbeResult]
    context: dict[str, Any]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [result.as_dict() for result in self.results]
        return data
