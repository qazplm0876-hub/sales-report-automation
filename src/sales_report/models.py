from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OfficialMetric:
    segment: str
    label: str
    market: str
    currency_unit: str
    previous_amount: float = 0.0
    current_amount: float = 0.0
    current_plan_amount: float = 0.0
    prior_ytd_amount: float = 0.0
    current_ytd_amount: float = 0.0
    current_ytd_plan_amount: float = 0.0
    previous_weight: float = 0.0
    current_weight: float = 0.0
    current_plan_weight: float = 0.0
    prior_ytd_weight: float = 0.0
    current_ytd_weight: float = 0.0
    current_ytd_plan_weight: float = 0.0


@dataclass
class OfficialReport:
    path: Path
    year: int
    month: int
    metrics: dict[str, OfficialMetric]
    sheet_name: str


@dataclass
class RawSheetCandidate:
    path: Path
    sheet_name: str
    header_row: int
    headers: list[str]


@dataclass
class InputManifest:
    official_path: Path
    cumulative_files: dict[int, RawSheetCandidate]
    recipient_files: dict[tuple[str, int], RawSheetCandidate]
    ignored_files: list[Path] = field(default_factory=list)


@dataclass
class CumulativeDataset:
    segment: str
    label: str
    rows: list[dict[str, Any]]
    sources: list[dict[str, Any]]


@dataclass
class RecipientDataset:
    segment: str
    label: str
    rows: list[dict[str, Any]]
    sources: list[dict[str, Any]]
