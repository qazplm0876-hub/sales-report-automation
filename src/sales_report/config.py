from __future__ import annotations

from pathlib import Path

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "analysis_rules.yaml"


def load_config(path: Path | None = None) -> dict:
    config_path = path or DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    required = {"report_order", "segments", "display_names", "thresholds", "output"}
    missing = required - set(config)
    if missing:
        raise ValueError(f"설정 파일 필수 항목 누락: {', '.join(sorted(missing))}")
    return config
