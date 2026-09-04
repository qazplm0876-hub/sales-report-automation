from __future__ import annotations

import argparse
import logging
import re
import sys
import traceback
from pathlib import Path

from .analysis import build_analysis
from .config import DEFAULT_CONFIG, load_config
from .input_loader import discover_inputs, discover_official, load_cumulative_datasets, load_recipient_datasets
from .narrative import build_markdown
from .official import parse_official_report
from .workbook_writer import write_analysis_workbook


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="월간 매출실적 분석 자동화")
    parser.add_argument("--input", type=Path, default=Path("input"), help="원본 엑셀 폴더")
    parser.add_argument("--output", type=Path, default=Path("output"), help="결과 저장 폴더")
    parser.add_argument("--month", default="auto", help="분석월 YYYYMM 또는 auto")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="분석 규칙 YAML")
    return parser


def _configure_logging(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def run(args) -> tuple[Path, Path]:
    input_dir = args.input.resolve()
    output_root = args.output.resolve()
    if not input_dir.exists():
        raise ValueError(f"input 폴더가 없습니다: {input_dir}")
    config = load_config(args.config.resolve())

    official_path = discover_official(input_dir)
    print(f"[1/6] 공식 실적표 확인: {official_path.name}")
    official = parse_official_report(official_path, config)
    official_period = f"{official.year}{official.month:02d}"
    if args.month == "auto":
        target_period = official_period
    else:
        if not re.fullmatch(r"20\d{4}", args.month):
            raise ValueError("분석월은 YYYYMM 형식으로 입력해 주세요. 예: 202607")
        target_period = args.month
        if target_period != official_period:
            raise ValueError(f"입력한 분석월({target_period})과 공식 실적표 제목({official_period})이 다릅니다.")
    print(f"[2/6] 분석월 확정: {target_period}")

    manifest = discover_inputs(input_dir, official_path, official.year, config)
    cumulative_datasets = load_cumulative_datasets(manifest, target_period, config)
    print(
        f"[3/6] 누계 수치자료 확인: "
        f"{manifest.cumulative_files[official.year - 1].path.name}, {manifest.cumulative_files[official.year].path.name}"
    )

    recipient_datasets = load_recipient_datasets(manifest, target_period, config, official.metrics)
    print(f"[4/6] 인수처 자료 확인: {len(manifest.recipient_files)}개 ({official.year - 1}년 6개 + {official.year}년 6개)")
    if manifest.ignored_files:
        print("참고: 분석 대상이 아닌 파일은 무시했습니다: " + ", ".join(path.name for path in manifest.ignored_files))

    for segment in config["report_order"]:
        logging.info(
            "SOURCES %s | cumulative_rows=%s | recipient_rows=%s",
            segment,
            len(cumulative_datasets[segment].rows),
            len(recipient_datasets[segment].rows),
        )

    print("[5/6] 6개 부문 품목·인수처·지역·월별 추이 분석 중...")
    analysis = build_analysis(official, cumulative_datasets, recipient_datasets, target_period, config)
    run_dir = output_root / target_period
    run_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = run_dir / f"{target_period}_매출실적_분석.xlsx"
    markdown_path = run_dir / f"{target_period}_보고용_초안.md"
    write_analysis_workbook(workbook_path, analysis, official, config)
    markdown_path.write_text(build_markdown(analysis, official, config), encoding="utf-8-sig")

    logging.info("MODEL STATUS %s", analysis["model_status"])
    for check in analysis["checks"]:
        logging.info(
            "CHECK %s | %s | status=%s | official=%.6f | calculated=%.6f | diff=%.6f | match=%s",
            check["label"],
            check["check"],
            check["status"],
            check["official"],
            check["calculated"],
            check["difference"],
            check["match_pct"],
        )
    logging.info("OUTPUT workbook=%s markdown=%s", workbook_path, markdown_path)
    print(f"[6/6] 완료: {workbook_path}")
    if analysis["model_status"] == "WARN":
        print("주의: 공식표와 누계파일 계산값에 차이가 있어 검산 시트에 WARN을 표시했습니다.")
    return workbook_path, markdown_path


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    log_root = args.output.resolve().parent / "logs"
    month_for_log = args.month if args.month != "auto" else "auto"
    log_path = log_root / f"run_{month_for_log}.log"
    _configure_logging(log_path)
    try:
        workbook_path, markdown_path = run(args)
        print(f"분석표: {workbook_path}")
        print(f"보고문안: {markdown_path}")
        return 0
    except Exception as exc:
        logging.error("분석 실패: %s\n%s", exc, traceback.format_exc())
        print(f"오류: {exc}", file=sys.stderr)
        print(f"상세 로그: {log_path}", file=sys.stderr)
        return 1
