from __future__ import annotations

import math
import re
from datetime import date, datetime


def text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def number(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalize_period(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y%m")
    raw = text(value).replace("-", "").replace("/", "")
    if re.fullmatch(r"\d{6}(?:\.0)?", raw):
        return raw[:6]
    if re.fullmatch(r"\d{8}(?:\.0)?", raw):
        return raw[:6]
    return raw


def compact(value) -> str:
    return re.sub(r"\s+", "", text(value))


def previous_period(period: str) -> str:
    year, month = int(period[:4]), int(period[4:])
    if month == 1:
        return f"{year - 1}12"
    return f"{year}{month - 1:02d}"


def pct_change(current: float, previous: float) -> float | None:
    if abs(previous) < 1e-12:
        return None
    return current / previous - 1


def safe_unit_price(amount: float, weight: float) -> float | None:
    if abs(weight) < 1e-12:
        return None
    return amount / weight


def relative_error(actual: float, expected: float) -> float:
    denominator = max(abs(expected), 1.0)
    return abs(actual - expected) / denominator


def month_label(period: str) -> str:
    return f"{int(period[4:])}월"


def signed_number(value: float, decimals: int = 0) -> str:
    return f"{value:+,.{decimals}f}"


def percent_text(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "비교 불가"
    return f"{value * 100:+.{decimals}f}%"
