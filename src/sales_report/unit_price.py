"""Recurring generator for the unit-price root-cause workbook.

This command intentionally creates only the ``제품판매단가_원인탐색용``
workbook.  It does not generate the separate monthly sales narrative report.
"""
from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from copy import copy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook

from .utils import normalize_period, number, text


RAW_HEADERS = {
    "부문", "내수/수출", "요청월", "레벨1명", "레벨2명", "레벨3명", "계정",
    "중량", "달러금액", "한국원화금액",
}


@dataclass(frozen=True)
class Mapping:
    report_row: int
    report_group: str
    report_product: str
    company: str
    market: str
    source_division: str
    market_values: tuple[str, ...]
    level1_values: tuple[str, ...]
    level2_values: tuple[str, ...]
    amount_basis: str
    unit: str


def _split_conditions(value: object) -> tuple[str, ...]:
    value = text(value)
    if not value or value == "(조건 없음)":
        return ()
    return tuple(item.strip() for item in value.split("/") if item.strip())


def _header_candidate(path: Path):
    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        candidates = []
        for worksheet in workbook.worksheets:
            for row_number, row in enumerate(worksheet.iter_rows(min_row=1, max_row=15, values_only=True), 1):
                headers = [text(value) for value in row]
                if RAW_HEADERS.issubset(headers):
                    candidates.append((max(0, (worksheet.max_row or 0) - row_number), worksheet.title, row_number, headers))
                    break
        if not candidates:
            return None
        _, title, row_number, headers = max(candidates)
        return title, row_number, headers
    finally:
        workbook.close()


def _find_raw_files(input_dir: Path) -> list[Path]:
    files = [path for path in sorted(input_dir.glob("*.xlsx")) if not path.name.startswith("~$")]
    files = [path for path in files if _header_candidate(path)]
    if len(files) != 2:
        found = ", ".join(path.name for path in files) or "없음"
        raise ValueError(
            "단가 원인탐색용 input 폴더에는 2025년·2026년 누계 Raw 파일 2개만 넣어 주세요. "
            f"현재 감지: {found}"
        )
    return files


def _infer_latest_period(paths: Iterable[Path]) -> tuple[int, int]:
    periods = []
    for path in paths:
        candidate = _header_candidate(path)
        if not candidate:
            continue
        sheet_name, header_row, headers = candidate
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            worksheet = workbook[sheet_name]
            period_index = headers.index("요청월")
            for row in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
                period = normalize_period(row[period_index] if period_index < len(row) else None)
                if len(period) == 6 and period.isdigit():
                    periods.append(period)
        finally:
            workbook.close()
    if not periods:
        raise ValueError("누계 Raw에서 요청월을 찾지 못했습니다.")
    latest = max(periods)
    return int(latest[:4]), int(latest[4:])


def _read_mappings(workbook) -> list[Mapping]:
    worksheet = workbook["분류맵"]
    result = []
    for row in worksheet.iter_rows(min_row=4, values_only=True):
        if not row[0]:
            continue
        result.append(
            Mapping(
                report_row=int(number(row[0])),
                report_group=text(row[1]),
                report_product=text(row[2]),
                company=text(row[3]),
                market=text(row[4]),
                source_division=text(row[5]),
                market_values=_split_conditions(row[6]),
                level1_values=_split_conditions(row[7]),
                level2_values=_split_conditions(row[8]),
                amount_basis=text(row[9]),
                unit=text(row[10]),
            )
        )
    if len(result) != 28:
        raise ValueError("템플릿의 분류맵이 28개 보고서 행으로 구성되어 있지 않습니다.")
    return result


def _matches(record: dict, mapping: Mapping) -> bool:
    if text(record.get("부문")) != mapping.source_division:
        return False
    if mapping.market_values and text(record.get("내수/수출")) not in mapping.market_values:
        return False
    if mapping.level1_values and text(record.get("레벨1명")) not in mapping.level1_values:
        return False
    if mapping.level2_values and text(record.get("레벨2명")) not in mapping.level2_values:
        return False
    return True


def _percentile(values: list[float], ratio: float) -> float:
    positives = sorted(abs(value) for value in values if abs(value) > 1e-12)
    if not positives:
        return 0.0
    return positives[min(len(positives) - 1, int((len(positives) - 1) * ratio))]


def _source_unit_divisors(market: str, amounts: list[float], weights: list[float]) -> tuple[float, float]:
    """Detect source units (kg/USD/won) versus report units (ton/KUSD/million won)."""
    amount_p90 = _percentile(amounts, 0.90)
    weight_p90 = _percentile(weights, 0.90)
    if market == "export":
        amount_divisor = 1_000.0 if amount_p90 >= 1_000 else 1.0
    else:
        amount_divisor = 1_000_000.0 if amount_p90 >= 100_000 else 1.0
    weight_divisor = 1_000.0 if weight_p90 >= 1_000 else 1.0
    return amount_divisor, weight_divisor


def _read_records(paths: Iterable[Path], mappings: list[Mapping], target_year: int, target_month: int) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    sources: list[dict] = []
    for path in paths:
        candidate = _header_candidate(path)
        if not candidate:
            continue
        sheet_name, header_row, headers = candidate
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        worksheet = workbook[sheet_name]
        index = {name: position for position, name in enumerate(headers) if name}
        pending: list[dict] = []
        stats = defaultdict(lambda: {"source_rows": 0, "excluded": 0, "unmapped": 0, "duplicate": 0, "kept": 0})
        try:
            for source_row, row in enumerate(worksheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
                raw = {name: row[pos] if pos < len(row) else None for name, pos in index.items()}
                period = normalize_period(raw.get("요청월"))
                if len(period) != 6 or not period.isdigit():
                    continue
                year, month = int(period[:4]), int(period[4:])
                if year not in {target_year - 1, target_year} or month > target_month:
                    continue
                stats[year]["source_rows"] += 1
                if int(number(raw.get("계정"))) == 6:
                    stats[year]["excluded"] += 1
                    continue
                matched_items = [item for item in mappings if _matches(raw, item)]
                if not matched_items:
                    stats[year]["unmapped"] += 1
                    continue
                if len(matched_items) > 1:
                    stats[year]["duplicate"] += 1
                matched = matched_items[0]
                market = "export" if matched.amount_basis == "달러금액" else "domestic"
                pending.append({
                    "raw": raw,
                    "source_row": source_row,
                    "period": period,
                    "year": year,
                    "mapping": matched,
                    "market": market,
                    "amount": number(raw.get(matched.amount_basis)),
                    "weight": number(raw.get("중량")),
                })
                stats[year]["kept"] += 1
        finally:
            workbook.close()

        grouped = defaultdict(lambda: {"amounts": [], "weights": []})
        for item in pending:
            group = grouped[(item["year"], item["market"])]
            group["amounts"].append(item["amount"])
            group["weights"].append(item["weight"])
        divisors = {
            key: _source_unit_divisors(key[1], values["amounts"], values["weights"])
            for key, values in grouped.items()
        }

        for item in pending:
            raw = item["raw"]
            matched = item["mapping"]
            amount_divisor, weight_divisor = divisors[(item["year"], item["market"])]
            weight, amount = item["weight"], item["amount"]
            analyst = text(raw.get("담당자(세부)명")) or text(raw.get("담당자명")) or "담당자없음"
            short_name = text(raw.get("약어명")) or text(raw.get("품명")) or text(raw.get("품번2")) or "(미지정)"
            flags = []
            if weight < 0:
                flags.append("음수중량")
            if amount < 0:
                flags.append("음수금액")
            if not weight and amount:
                flags.append("중량0·금액있음")
            if weight and not amount:
                flags.append("금액0")
            unit_system = "kg·USD·원" if weight_divisor == 1_000 else "톤·KUSD·백만원"
            record = {
                **raw,
                "원본파일": path.name,
                "원본행": item["source_row"],
                "연도": item["year"],
                "연월": item["period"],
                "보고서행": matched.report_row,
                "보고서구분": matched.report_group,
                "보고서품목": matched.report_product,
                "분석대상": "Y",
                "제외사유": "",
                "분석담당자": analyst,
                "약어명": short_name,
                "중량(톤)": weight / weight_divisor,
                "분석금액": amount / amount_divisor,
                "금액단위": "KUSD" if item["market"] == "export" else "백만원",
                "단가단위": matched.unit,
                "원본단위체계": unit_system,
            }
            record["행단가"] = record["분석금액"] / record["중량(톤)"] if record["중량(톤)"] else None
            record["특이값플래그"] = " · ".join(flags) if flags else "정상"
            records.append(record)

        for year, values in stats.items():
            sources.append({"file": path.name, "sheet": sheet_name, "year": year, **values})
    if not records:
        raise ValueError("분석대상으로 매핑된 거래행이 없습니다. 누계 Raw 파일과 분류맵을 확인해 주세요.")
    return records, sources


def _metrics(records: Iterable[dict]) -> tuple[float, float, float | None]:
    weight = sum(number(record["중량(톤)"]) for record in records)
    amount = sum(number(record["분석금액"]) for record in records)
    return weight, amount, amount / weight if weight else None


def _period_records(records: list[dict], report_row: int, year: int, months: range) -> list[dict]:
    allowed = {f"{year}{month:02d}" for month in months}
    return [record for record in records if record["보고서행"] == report_row and record["연월"] in allowed]


def _pct(current: float | None, previous: float | None) -> float | None:
    return None if current is None or previous in (None, 0) else current / previous - 1


def _components(baseline: list[dict], compared: list[dict]) -> list[dict]:
    def grouped(rows):
        values = defaultdict(lambda: [0.0, 0.0])
        meta = {}
        for row in rows:
            key = (row["약어명"], row["분석담당자"], text(row.get("레벨1명")), text(row.get("레벨2명")))
            values[key][0] += number(row["중량(톤)"])
            values[key][1] += number(row["분석금액"])
            meta[key] = row
        return values, meta

    left, left_meta = grouped(baseline)
    right, right_meta = grouped(compared)
    total_w0, _, total_p0 = _metrics(baseline)
    total_w1, _, total_p1 = _metrics(compared)
    if total_p0 is None or total_p1 is None:
        return []
    result = []
    for key in sorted(set(left) | set(right)):
        w0, a0 = left[key]
        w1, a1 = right[key]
        if not w0 and not w1:
            continue
        p0, p1 = (a0 / w0 if w0 else None), (a1 / w1 if w1 else None)
        share0, share1 = (w0 / total_w0 if total_w0 else 0), (w1 / total_w1 if total_w1 else 0)
        reference_price = p0 if p0 is not None else p1
        mix = (share1 - share0) * ((reference_price or total_p0) - total_p0)
        price = share1 * (p1 - p0) if p0 is not None and p1 is not None else 0.0
        total = mix + price
        meta = right_meta.get(key) or left_meta.get(key) or {}
        status = "계속" if w0 and w1 else ("신규" if w1 else "중단")
        if status == "신규":
            cause = "고단가 신규" if (p1 or 0) >= total_p0 else "저단가 신규"
        elif status == "중단":
            cause = "고단가 중단" if (p0 or 0) >= total_p0 else "저단가 중단"
        elif abs(price) > abs(mix):
            cause = "제품단가 상승" if price >= 0 else "제품단가 하락"
        else:
            level = "고단가" if (p0 or 0) >= total_p0 else "저단가"
            cause = f"{level} 비중{'↑' if share1 >= share0 else '↓'}"
        result.append({
            "약어명": key[0], "분석담당자": key[1], "레벨1명": key[2], "레벨2명": key[3],
            "담당자명": text(meta.get("담당자명")), "담당자(세부)명": text(meta.get("담당자(세부)명")),
            "상태": status, "기준중량": w0, "비교중량": w1, "기준비중": share0, "비교비중": share1,
            "기준제품단가": p0, "비교제품단가": p1, "믹스효과": mix, "가격효과": price,
            "총단가기여도": total, "영향절대값": abs(total), "원인유형": cause,
        })
    residual = (total_p1 - total_p0) - sum(item["총단가기여도"] for item in result)
    if abs(residual) > 1e-10:
        result.append({
            "약어명": "(중량0 금액효과)", "분석담당자": "-", "레벨1명": "-", "레벨2명": "-",
            "담당자명": "", "담당자(세부)명": "", "상태": "대사조정", "기준중량": 0.0,
            "비교중량": 0.0, "기준비중": 0.0, "비교비중": 0.0, "기준제품단가": None,
            "비교제품단가": None, "믹스효과": 0.0, "가격효과": residual,
            "총단가기여도": residual, "영향절대값": abs(residual), "원인유형": "중량0 금액효과",
        })
    return sorted(result, key=lambda item: item["영향절대값"], reverse=True)


def _copy_row_style(worksheet, source_row: int, destination_row: int, columns: int):
    for column in range(1, columns + 1):
        source = worksheet.cell(source_row, column)
        target = worksheet.cell(destination_row, column)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        target.alignment = copy(source.alignment)


def _reset_table(worksheet, rows: list[list], columns: int, source_style_row: int = 5, start_row: int = 5):
    style = [copy(worksheet.cell(source_style_row, column)._style) for column in range(1, columns + 1)]
    alignment = [copy(worksheet.cell(source_style_row, column).alignment) for column in range(1, columns + 1)]
    if worksheet.max_row >= start_row:
        worksheet.delete_rows(start_row, worksheet.max_row - start_row + 1)
    for row_number, values in enumerate(rows, start_row):
        for column, value in enumerate(values, 1):
            cell = worksheet.cell(row_number, column, value)
            if column <= len(style) and style[column - 1]:
                cell._style = copy(style[column - 1])
            if column <= len(alignment):
                cell.alignment = copy(alignment[column - 1])


def _write_headers(worksheet, row_number: int, headers: list[str]):
    """Replace a dynamic header row without leaving prior-month columns behind."""
    previous_width = worksheet.max_column or 0
    for column in range(1, max(previous_width, len(headers)) + 1):
        worksheet.cell(row_number, column).value = headers[column - 1] if column <= len(headers) else None


def _write_raw_sheet(workbook, records: list[dict], target_year: int, target_month: int):
    worksheet = workbook["가공데이터"]
    headers = [
        "부문", "내수/수출", "실적국가", "회사", "시작일", "종료일", "요청월", "요청년도", "상태", "실적공장", "내수구분",
        "담당자", "담당자명", "담당자(세부)", "담당자(세부)명", "LVL1", "레벨1명", "LVL2", "레벨2명", "LVL3", "레벨3명",
        "LVL4", "레벨4명", "품번1", "품번2", "품번3", "약어명", "등급", "계정", "중량", "원화금액", "달러금액",
        "한국원화금액", "원본파일", "원본행", "연도", "연월", "원본단위체계", "법인", "판매구분", "정규화부문",
        "보고서행", "보고서구분", "보고서품목", "분석대상", "제외사유", "분석담당자", "중량(톤)", "분석금액", "금액단위",
        "단가단위", "행단가", "특이값플래그",
    ]
    worksheet.cell(1, 1).value = f"가공데이터 | {target_year - 1}년·{target_year}년 Raw 통합 + 동일 단위·보고서 매핑·담당자·특이값"
    worksheet.cell(2, 1).value = f"연도별 Raw 단위체계를 자동 판별해 톤·KUSD·백만원으로 정규화합니다. 분석기간은 1~{target_month}월입니다."
    for column, header in enumerate(headers, 1):
        worksheet.cell(3, column).value = header
    if worksheet.max_row >= 4:
        worksheet.delete_rows(4, worksheet.max_row - 3)
    for row_number, record in enumerate(sorted(records, key=lambda item: (item["연월"], item["보고서행"], item["원본파일"], item["원본행"])), 4):
        values = [
            record.get("부문"), record.get("내수/수출"), record.get("실적국가"), record.get("회사"), record.get("시작일"), record.get("종료일"),
            record.get("요청월"), record.get("요청년도"), record.get("상태"), record.get("실적공장"), record.get("내수구분"), record.get("담당자"),
            record.get("담당자명"), record.get("담당자(세부)"), record.get("담당자(세부)명"), record.get("LVL1"), record.get("레벨1명"), record.get("LVL2"),
            record.get("레벨2명"), record.get("LVL3"), record.get("레벨3명"), record.get("LVL4"), record.get("레벨4명"), record.get("품번1"),
            record.get("품번2"), record.get("품번3"), record.get("약어명"), record.get("등급"), record.get("계정"), record.get("중량"),
            record.get("원화금액"), record.get("달러금액"), record.get("한국원화금액"), record.get("원본파일"), record.get("원본행"),
            record.get("연도"), record.get("연월"), record.get("원본단위체계"), record.get("회사"), record.get("내수/수출"), record.get("부문"),
            record.get("보고서행"), record.get("보고서구분"), record.get("보고서품목"), record.get("분석대상"), record.get("제외사유"),
            record.get("분석담당자"), record.get("중량(톤)"), record.get("분석금액"), record.get("금액단위"), record.get("단가단위"),
            record.get("행단가"), record.get("특이값플래그"),
        ]
        for column, value in enumerate(values, 1):
            worksheet.cell(row_number, column).value = value
    worksheet.freeze_panes = "A4"


def _cause_summary(components: list[dict], direction: int) -> tuple[str, str, str, float]:
    candidates = [item for item in components if item["총단가기여도"] * direction > 0]
    if not candidates:
        return None, None, None, None
    item = candidates[0]
    return item["약어명"], item["분석담당자"], item["원인유형"], item["총단가기여도"]


def _write_ytd_sheet(workbook, mappings: list[Mapping], records: list[dict], target_year: int, target_month: int):
    worksheet = workbook["누계비교"]
    worksheet.cell(1, 1).value = f"1단계 | 누계비교 — {target_year - 1}년 대비 {target_year}년 1~{target_month}월 누계 변동"
    rows = []
    for mapping in mappings:
        baseline = _period_records(records, mapping.report_row, target_year - 1, range(1, target_month + 1))
        compared = _period_records(records, mapping.report_row, target_year, range(1, target_month + 1))
        w0, a0, p0 = _metrics(baseline); w1, a1, p1 = _metrics(compared)
        components = _components(baseline, compared)
        up = _cause_summary(components, 1); down = _cause_summary(components, -1)
        price_change = (p1 or 0) - (p0 or 0)
        rows.append([
            mapping.report_row, mapping.report_group, mapping.report_product, mapping.unit, w0, w1, _pct(w1, w0), a0, a1, _pct(a1, a0),
            p0, p1, _pct(p1, p0), *up, *down, "확인" if abs(_pct(p1, p0) or 0) >= 0.1 else "",
            f"누계비 | {target_year - 1} 1~{target_month}월→{target_year} 1~{target_month}월 | {mapping.report_row} | {mapping.report_group} | {mapping.report_product}",
        ])
    _reset_table(worksheet, rows, 23)


def _write_yearly_scans(workbook, mappings: list[Mapping], records: list[dict], target_year: int, target_month: int):
    yoy = workbook["전년동월스캔"]
    yoy.cell(1, 1).value = f"1단계 | 전년동월스캔 — {target_year - 1}년 대비 {target_year}년 단가변동 찾기"
    yoy.cell(2, 1).value = f"{target_month}월 전년동월비와 최대 변동월의 탐색키를 원인탐색요약·상세에서 확인합니다."
    base_headers = ["보고서행", "구분", "품목", "단위"]
    month_headers = []
    for month in range(1, target_month + 1):
        month_headers += [f"{target_year - 1}년 {month}월", f"{target_year}년 {month}월", f"{month}월 전년비"]
    headers = base_headers + month_headers + ["최대변동월", "최대변동률", "우선확인", "탐색키(최대변동)"]
    _write_headers(yoy, 4, headers)
    rows = []
    for mapping in mappings:
        values = [mapping.report_row, mapping.report_group, mapping.report_product, mapping.unit]
        rates = []
        for month in range(1, target_month + 1):
            _, _, p0 = _metrics(_period_records(records, mapping.report_row, target_year - 1, range(month, month + 1)))
            _, _, p1 = _metrics(_period_records(records, mapping.report_row, target_year, range(month, month + 1)))
            rate = _pct(p1, p0); values += [p0, p1, rate]; rates.append(rate)
        valid = [(index + 1, rate) for index, rate in enumerate(rates) if rate is not None]
        peak_month, peak_rate = max(valid, key=lambda item: abs(item[1])) if valid else (target_month, None)
        key = f"전년동월비 | {target_year - 1} {peak_month}월→{target_year} {peak_month}월 | {mapping.report_row} | {mapping.report_group} | {mapping.report_product}"
        values += [f"{peak_month}월", peak_rate, "확인" if abs(peak_rate or 0) >= 0.1 else "", key]
        rows.append(values)
    _reset_table(yoy, rows, len(headers))

    mom = workbook["변동스캔"]
    mom.cell(1, 1).value = "1단계 | 변동스캔 — 연도별 전월비 변동 찾기"
    mom.cell(2, 1).value = f"{target_month - 1}월→{target_month}월 전월비와 연도별 최대 변동월의 탐색키를 확인합니다."
    headers = ["연도", "보고서행", "구분", "품목", "단위"] + [f"{month}월" for month in range(1, target_month + 1)]
    headers += [f"{month - 1}월→{month}월 전월비" for month in range(2, target_month + 1)] + ["최대변동월", "최대변동률", "우선확인", "탐색키(최대변동)"]
    _write_headers(mom, 4, headers)
    rows = []
    for year in (target_year - 1, target_year):
        for mapping in mappings:
            prices = [_metrics(_period_records(records, mapping.report_row, year, range(month, month + 1)))[2] for month in range(1, target_month + 1)]
            rates = [_pct(prices[index], prices[index - 1]) for index in range(1, len(prices))]
            valid = [(index + 2, rate) for index, rate in enumerate(rates) if rate is not None]
            peak_month, peak_rate = max(valid, key=lambda item: abs(item[1])) if valid else (target_month, None)
            key = f"전월비 | {year} {peak_month - 1}월→{peak_month}월 | {mapping.report_row} | {mapping.report_group} | {mapping.report_product}"
            rows.append([year, mapping.report_row, mapping.report_group, mapping.report_product, mapping.unit, *prices, *rates,
                         f"{peak_month - 1}월→{peak_month}월", peak_rate, "확인" if abs(peak_rate or 0) >= 0.1 else "", key])
    _reset_table(mom, rows, len(headers))


def _comparison_specs(target_year: int, target_month: int):
    specs = [
        ("누계비", f"{target_year - 1}→{target_year}", f"{target_year - 1} 1~{target_month}월→{target_year} 1~{target_month}월", range(1, target_month + 1), target_year - 1, range(1, target_month + 1), target_year),
    ]
    for month in range(1, target_month + 1):
        specs.append((
            "전년동월비", f"{target_year - 1}→{target_year}", f"{target_year - 1} {month}월→{target_year} {month}월",
            range(month, month + 1), target_year - 1, range(month, month + 1), target_year,
        ))
    for year in (target_year - 1, target_year):
        for month in range(2, target_month + 1):
            specs.append((
                "전월비", str(year), f"{year} {month - 1}월→{year} {month}월",
                range(month - 1, month), year, range(month, month + 1), year,
            ))
    return specs


def _write_cause_sheets(workbook, mappings: list[Mapping], records: list[dict], target_year: int, target_month: int):
    summary_rows, detail_rows = [], []
    for mapping in mappings:
        for kind, basis_year, period_label, left_months, left_year, right_months, right_year in _comparison_specs(target_year, target_month):
            baseline = _period_records(records, mapping.report_row, left_year, left_months)
            compared = _period_records(records, mapping.report_row, right_year, right_months)
            w0, _, p0 = _metrics(baseline); w1, _, p1 = _metrics(compared)
            rate = _pct(p1, p0)
            key = f"{kind} | {period_label} | {mapping.report_row} | {mapping.report_group} | {mapping.report_product}"
            components = _components(baseline, compared) if p0 is not None and p1 is not None else []
            up = _cause_summary(components, 1); down = _cause_summary(components, -1)
            price_change = p1 - p0 if p0 is not None and p1 is not None else None
            reconciliation = (
                sum(item["총단가기여도"] for item in components) - price_change
                if price_change is not None else None
            )
            summary_rows.append([
                0, "확인" if rate is not None and abs(rate) >= 0.1 else "", kind, basis_year, key, period_label, mapping.report_row, mapping.report_group,
                mapping.report_product, mapping.unit, p0, p1, price_change, rate, w0, w1, _pct(w1, w0),
                sum(1 for item in components if item["상태"] == "신규"), sum(1 for item in components if item["상태"] == "중단"),
                *up, *down, reconciliation,
                "전체판매없음·효과N/A" if p0 is None or p1 is None else ("금액0" if p0 == 0 or p1 == 0 else ""),
            ])
            for rank, item in enumerate(components, 1):
                direction = "단가상승" if item["총단가기여도"] >= 0 else "단가하락"
                detail_rows.append([
                    key, kind, f"{left_year}{min(left_months):02d}~{left_year}{max(left_months):02d}", f"{right_year}{min(right_months):02d}~{right_year}{max(right_months):02d}",
                    period_label, mapping.report_row, mapping.report_group, mapping.report_product, rank, direction, item["원인유형"], item["상태"],
                    item["약어명"], item["분석담당자"], item["레벨1명"], item["레벨2명"], item["담당자명"], item["담당자(세부)명"],
                    p0, p1, rate, item["기준중량"], item["비교중량"], item["기준비중"], item["비교비중"], item["비교비중"] - item["기준비중"],
                    item["기준제품단가"], item["비교제품단가"],
                    item["비교제품단가"] - item["기준제품단가"] if item["비교제품단가"] is not None and item["기준제품단가"] is not None else None,
                    item["믹스효과"], item["가격효과"], item["총단가기여도"],
                    item["영향절대값"], item["총단가기여도"] / price_change if price_change else None,
                    "중량0 금액효과" if item["상태"] == "대사조정" else "정상",
                ])
    summary_rows.sort(key=lambda row: (row[13] is not None, abs(row[13] or 0)), reverse=True)
    for rank, row in enumerate(summary_rows, 1): row[0] = rank
    _reset_table(workbook["원인탐색요약"], summary_rows, 29)
    _reset_table(workbook["원인탐색상세"], detail_rows, 35)


def _write_monthly_trend(workbook, mappings: list[Mapping], records: list[dict], target_year: int, target_month: int):
    """Rebuild the optional detailed trend sheet so it never retains last run's rows."""
    worksheet = workbook["상세월별추이(선택)"]
    worksheet.cell(1, 1).value = (
        f"선택 | 상세월별추이 — 약어명·담당자 조합의 1~{target_month}월 중량·금액·단가·비중"
    )
    worksheet.cell(2, 1).value = "원인탐색상세에서 눈에 띈 약어명이나 담당자만 추가 확인할 때 사용합니다."
    base_headers = [
        "연도", "보고서행", "보고서구분", "보고서품목", "레벨1명", "레벨2명", "약어명", "분석담당자",
        "담당자명", "담당자(세부)명", "금액단위", "단가단위",
    ]
    headers = base_headers[:]
    for month in range(1, target_month + 1):
        headers += [f"{month}월 중량(톤)", f"{month}월 금액", f"{month}월 단가", f"{month}월 비중"]
    _write_headers(worksheet, 3, headers)

    rows = []
    for year in (target_year - 1, target_year):
        for mapping in mappings:
            relevant = [
                record for record in records
                if record["연도"] == year and record["보고서행"] == mapping.report_row
            ]
            combinations = {}
            for record in relevant:
                key = (record["약어명"], record["분석담당자"], text(record.get("레벨1명")), text(record.get("레벨2명")))
                combinations.setdefault(key, record)
            for key in sorted(combinations):
                representative = combinations[key]
                values = [
                    year, mapping.report_row, mapping.report_group, mapping.report_product, key[2], key[3], key[0], key[1],
                    representative.get("담당자명"), representative.get("담당자(세부)명"), representative["금액단위"], mapping.unit,
                ]
                for month in range(1, target_month + 1):
                    month_records = [
                        record for record in relevant
                        if record["연월"] == f"{year}{month:02d}" and record["약어명"] == key[0]
                        and record["분석담당자"] == key[1] and text(record.get("레벨1명")) == key[2]
                        and text(record.get("레벨2명")) == key[3]
                    ]
                    total_records = _period_records(records, mapping.report_row, year, range(month, month + 1))
                    weight, amount, price = _metrics(month_records)
                    total_weight, _, _ = _metrics(total_records)
                    values += [weight, amount, price, weight / total_weight if total_weight else 0]
                rows.append(values)
    _reset_table(worksheet, rows, len(headers), source_style_row=4, start_row=4)
    worksheet.freeze_panes = "A4"


def _write_validation(workbook, mappings: list[Mapping], records: list[dict], sources: list[dict], target_year: int, target_month: int):
    worksheet = workbook["검증"]
    headers = ["연도", "원본행", "제외행", "가공행", "분석대상", "미매핑", "", "연도", "품질항목", "건수", "처리"]
    for column, header in enumerate(headers, 1): worksheet.cell(4, column).value = header
    overview = []
    quality = []
    for year in (target_year - 1, target_year):
        year_records = [item for item in records if item["연도"] == year]
        year_sources = [item for item in sources if item["year"] == year]
        source_rows = sum(item["source_rows"] for item in year_sources)
        excluded = sum(item["excluded"] for item in year_sources)
        unmapped = sum(item["unmapped"] for item in year_sources)
        kept = sum(item["kept"] for item in year_sources)
        overview.append([year, source_rows, excluded, source_rows - excluded, kept, unmapped])
        checks = [
            ("음수중량", sum(1 for item in year_records if number(item["중량(톤)"]) < 0)),
            ("중량0", sum(1 for item in year_records if not number(item["중량(톤)"]))),
            ("음수금액", sum(1 for item in year_records if number(item["분석금액"]) < 0)),
            ("금액0", sum(1 for item in year_records if not number(item["분석금액"]))),
            ("담당자없음", sum(1 for item in year_records if item["분석담당자"] == "담당자없음")),
        ]
        quality.extend([[year, label, count, "삭제하지 않고 플래그"] for label, count in checks])

    effect_checks = effect_failures = effect_na = 0
    for mapping in mappings:
        for _, _, _, left_months, left_year, right_months, right_year in _comparison_specs(target_year, target_month):
            baseline = _period_records(records, mapping.report_row, left_year, left_months)
            compared = _period_records(records, mapping.report_row, right_year, right_months)
            _, _, p0 = _metrics(baseline); _, _, p1 = _metrics(compared)
            if p0 is None or p1 is None:
                effect_na += 1
                continue
            effect_checks += 1
            residual = sum(item["총단가기여도"] for item in _components(baseline, compared)) - (p1 - p0)
            if abs(residual) > 1e-8:
                effect_failures += 1
    duplicate_count = sum(item["duplicate"] for item in sources)
    model_rows = [
        ["모델 점검", "건수", "판정", "비고"],
        ["중복 매핑", duplicate_count, "PASS" if not duplicate_count else "WARN", "한 Raw 행이 여러 보고서행에 잡히는지 확인"],
        ["효과 대사", effect_checks, "PASS" if not effect_failures else "WARN", f"불일치 {effect_failures}건"],
        ["효과 N/A", effect_na, "INFO", "기준월 또는 비교월 전체판매 없음"],
    ]
    row_count = max(len(overview), len(quality), len(model_rows) + 1)
    rows = []
    for index in range(row_count):
        left = overview[index] if index < len(overview) else ([None] * 6)
        right = quality[index] if index < len(quality) else ([None] * 4)
        rows.append([*left, "", *right])
    rows.append([None] * 11)
    for model_row in model_rows:
        rows.append([*model_row, None, None, None, None, None, None, None])
    _reset_table(worksheet, rows, 11)
    worksheet["A2"] = "MODEL STATUS"
    worksheet["B2"] = "PASS" if not duplicate_count and not effect_failures else "WARN"


def build_workbook(template: Path, raw_paths: list[Path], output: Path, target_year: int | None = None, target_month: int | None = None) -> Path:
    if not template.exists():
        raise ValueError(f"템플릿 파일이 없습니다: {template}")
    template_book = load_workbook(template, read_only=True, data_only=False, keep_links=False)
    try:
        mappings = _read_mappings(template_book)
    finally:
        template_book.close()

    inferred_year, inferred_month = _infer_latest_period(raw_paths)
    target_year, target_month = target_year or inferred_year, target_month or inferred_month
    records, sources = _read_records(raw_paths, mappings, target_year, target_month)

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    workbook = load_workbook(output, data_only=False, keep_links=False)
    _write_raw_sheet(workbook, records, target_year, target_month)
    _write_ytd_sheet(workbook, mappings, records, target_year, target_month)
    _write_yearly_scans(workbook, mappings, records, target_year, target_month)
    _write_cause_sheets(workbook, mappings, records, target_year, target_month)
    _write_monthly_trend(workbook, mappings, records, target_year, target_month)
    _write_validation(workbook, mappings, records, sources, target_year, target_month)
    workbook["사용가이드"]["A1"] = f"제품판매단가 원인탐색용 | {target_year - 1}년·{target_year}년 1~{target_month}월 통합"
    workbook["사용가이드"]["A2"] = f"생성일시: {datetime.now():%Y-%m-%d %H:%M} | 누계 Raw 2개를 기준으로 자동 생성"
    workbook.save(output)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="제품판매단가 원인탐색 통합파일 생성")
    parser.add_argument("--input", type=Path, default=Path("unit_price_input"))
    parser.add_argument("--template", type=Path, default=Path("unit_price_template.xlsx"))
    parser.add_argument("--output", type=Path, default=Path("unit_price_output"))
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    args = parser.parse_args(argv)
    raw_paths = _find_raw_files(args.input.resolve())
    output_year = args.year
    output_month = args.month
    if bool(output_year) != bool(output_month) or output_month and not 1 <= output_month <= 12:
        raise ValueError("연도와 월은 함께 지정하며 월은 1~12여야 합니다.")
    year, month = (output_year, output_month) if output_year else _infer_latest_period(raw_paths)
    target_name = f"제품판매단가_원인탐색용_{year - 1}년·{year}년_1~{month}월_통합.xlsx"
    output = args.output.resolve() / target_name
    result = build_workbook(args.template.resolve(), raw_paths, output, output_year, output_month)
    print(f"완료: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
