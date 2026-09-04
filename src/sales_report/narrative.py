from __future__ import annotations

from statistics import mean, pstdev

from .utils import signed_number


def _change_word(value: float) -> str:
    return "증가" if value >= 0 else "감소"


def _pct_statement(value: float | None, delta: float) -> str:
    if value is None:
        return "기준기간 실적이 없어 증감률 산출 불가"
    return f"{abs(value) * 100:.1f}% {_change_word(delta)}"


def _status_particle(status: str) -> str:
    if not status:
        return "로"
    last = status[-1]
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28:
        return "으로"
    return "로"


def _destination_particle(unit: str) -> str:
    return "으로" if unit == "백만원" else "로"


def _number_destination_particle(value: float) -> str:
    rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    last = rendered[-1] if rendered else "0"
    return "으로" if last in "036" else "로"


def _topic_particle(value: str) -> str:
    if not value:
        return "은"
    last = value[-1]
    if "가" <= last <= "힣":
        return "은" if (ord(last) - ord("가")) % 28 else "는"
    return "은"


def _subject_particle(value: str) -> str:
    if not value:
        return "이"
    last = value[-1]
    if "가" <= last <= "힣":
        return "이" if (ord(last) - ord("가")) % 28 else "가"
    normalized = value.upper().rstrip(".)")
    if normalized[-1:] in "013678":
        return "이"
    return "이" if normalized.endswith(("SPRING", "HEADING", "VECTRAN", "SSWR", "GENERAL")) else "가"


def _object_particle(value: str) -> str:
    if not value:
        return "을"
    last = value[-1]
    if "가" <= last <= "힣":
        return "을" if (ord(last) - ord("가")) % 28 else "를"
    return "을"


def _directional(items: list[dict], positive: bool, limit: int) -> list[dict]:
    selected = [item for item in items if (item["amount_delta"] > 0 if positive else item["amount_delta"] < 0)]
    selected.sort(key=lambda item: item["amount_delta"], reverse=positive)
    return selected[:limit]


def _list_changes(items: list[dict], positive: bool, limit: int = 4, name_key: str = "primary") -> str:
    selected = _directional(items, positive, limit)
    return ", ".join(f"{item[name_key]} {abs(item['amount_delta']):,.0f}" for item in selected)


def _summary_paragraph(summary: dict, month: int) -> str:
    comparison = summary["comparison"]
    unit = summary["currency_unit"]
    if comparison == "전월 대비":
        period_text = f"{month}월"
        compare_text = "전월 대비"
    else:
        period_text = f"1~{month}월 누계"
        compare_text = "전년 동기 대비"
    amount_change = f"{abs(summary['amount_pct']) * 100:.1f}% {_change_word(summary['amount_delta'])}" if summary["amount_pct"] is not None else "증감률 산출 불가"
    weight_change = f"{abs(summary['weight_pct']) * 100:.1f}% {_change_word(summary['weight_delta'])}" if summary["weight_pct"] is not None else "증감률 산출 불가"
    price_delta = (summary["current_price"] or 0) - (summary["previous_price"] or 0)
    price_change = f"{abs(summary['price_pct']) * 100:.1f}% {_change_word(price_delta)}" if summary["price_pct"] is not None else "증감률 산출 불가"
    price_text = (
        f"평균단가는 {summary['previous_price']:.2f}에서 {summary['current_price']:.2f}"
        f"{_number_destination_particle(summary['current_price'])} {price_change}했습니다."
        if summary["previous_price"] is not None and summary["current_price"] is not None
        else "제품판매중량이 없는 상품 실적이 포함돼 평균단가는 산출하지 않았습니다."
    )
    return (
        f"{period_text} {summary['label']} 판매금액은 {summary['current_amount']:,.0f}{unit}{_destination_particle(unit)} {compare_text} "
        f"{abs(summary['amount_delta']):,.0f}{unit}, {amount_change}했습니다. "
        f"제품판매중량은 {summary['previous_weight']:,.0f}톤에서 {summary['current_weight']:,.0f}톤으로 "
        f"{weight_change}했고, {price_text}"
    )


def _driver_paragraph(summary: dict) -> str:
    unit = summary["currency_unit"]
    return (
        f"기준기간 평균단가를 적용해 구분하면 제품판매중량 변화 효과는 {signed_number(summary['volume_effect'])}{unit}, "
        f"평균단가 및 제품 구성 변화 효과는 {signed_number(summary['price_mix_effect'])}{unit}입니다."
    )


def _item_paragraph(summary: dict, items: list[dict]) -> str:
    increases = _list_changes(items, True)
    decreases = _list_changes(items, False)
    parts = []
    if increases:
        parts.append(f"증가 품목은 {increases}{summary['currency_unit']}입니다")
    if decreases:
        parts.append(f"감소 품목은 {decreases}{summary['currency_unit']}입니다")
    if not parts:
        return "품목별 증감 내역은 상세 분석표에서 확인할 수 있습니다."
    sentence = "품목별로 " + ". 반면 ".join(parts) + "."
    positive = [item for item in items if item["amount_delta"] > 0]
    if summary["amount_delta"] > 0 and positive:
        top = positive[0]
        ratio = top["amount_delta"] / summary["amount_delta"] if summary["amount_delta"] else 0
        if 1.2 <= ratio <= 10:
            sentence += f" {top['primary']} 증가액은 전체 순증가액의 약 {ratio:.1f}배로, 다른 품목의 감소를 상쇄했습니다."
    return sentence


def _select_focus_items(summary: dict, items: list[dict], config: dict, market: str) -> list[dict]:
    nonzero = sorted((item for item in items if abs(item["amount_delta"]) > 0.5), key=lambda item: abs(item["amount_delta"]), reverse=True)
    if not nonzero:
        return []
    maximum = int(config["output"].get("focus_primary_items_max", 8))
    coverage_target = float(config["output"].get("focus_primary_coverage_ratio", 0.9))
    threshold = float(config["thresholds"]["large_amount_change"][market])
    gross_change = sum(abs(item["amount_delta"]) for item in nonzero)
    selected: list[dict] = []
    covered = 0.0
    for item in nonzero:
        if len(selected) >= maximum:
            break
        must_include = abs(item["amount_delta"]) >= threshold
        needs_coverage = covered / gross_change < coverage_target if gross_change else False
        needs_direction = not any(other["amount_delta"] * item["amount_delta"] > 0 for other in selected)
        if must_include or needs_coverage or needs_direction:
            selected.append(item)
            covered += abs(item["amount_delta"])
    return selected


def _format_monthly_series(monthly_amounts: dict[str, float], year: int, month: int, unit: str) -> str:
    values = [monthly_amounts.get(f"{year}{item_month:02d}", 0.0) for item_month in range(1, month + 1)]
    return " → ".join(f"{value:,.0f}" for value in values) + unit


def _trend_interpretation(monthly_amounts: dict[str, float], year: int, month: int) -> str:
    values = [monthly_amounts.get(f"{year}{item_month:02d}", 0.0) for item_month in range(1, month + 1)]
    active = [abs(value) > 0.5 for value in values]
    active_count = sum(active)
    comments: list[str] = []
    if active_count == month:
        comments.append("매월 실적이 이어졌습니다")
    elif active_count == 0:
        comments.append("당해 실적이 발생하지 않았습니다")
    elif active_count == 1:
        comments.append("실적이 특정 월에 집중됐습니다")
    elif 1 < active_count < month:
        comments.append("출고 월과 미출고 월이 섞인 간헐적 실적입니다")
    if len(values) >= 3 and all(values[index] > values[index - 1] for index in range(len(values) - 2, len(values))):
        comments.append("최근 3개월은 연속 증가했습니다")
    elif len(values) >= 3 and all(values[index] < values[index - 1] for index in range(len(values) - 2, len(values))):
        comments.append("최근 3개월은 연속 감소했습니다")
    positive_values = [abs(value) for value in values if abs(value) > 0.5]
    if len(positive_values) >= 3 and mean(positive_values) and pstdev(positive_values) / mean(positive_values) >= 0.55:
        comments.append("월별 판매금액 편차가 큰 편입니다")
    if len(values) >= 2 and values[-1] < values[-2] and values[-2] >= max(values[:-1]):
        comments.append("당월 감소에는 전월 고실적의 기저효과가 포함됐을 가능성이 있습니다")
    return " ".join(f"{comment}." for comment in comments[:2]) or "월별 흐름은 추가 관찰이 필요합니다."


def _select_secondary_drivers(item: dict, secondary_items: list[dict], config: dict) -> list[dict]:
    related = [
        row
        for row in secondary_items
        if row["primary"] == item["primary"]
        and row["secondary"] not in {"", "(미분류)", item["primary"]}
        and abs(row["amount_delta"]) > 0.5
    ]
    if not related:
        return []
    maximum = int(config["output"].get("focus_secondary_items_max", 3))
    coverage_target = float(config["output"].get("focus_secondary_coverage_ratio", 0.8))
    offset_share = float(config["output"].get("focus_secondary_offset_min_share", 0.15))
    same_direction = sorted(
        (row for row in related if row["amount_delta"] * item["amount_delta"] > 0),
        key=lambda row: abs(row["amount_delta"]),
        reverse=True,
    )
    opposite = sorted(
        (row for row in related if row["amount_delta"] * item["amount_delta"] < 0),
        key=lambda row: abs(row["amount_delta"]),
        reverse=True,
    )
    selected: list[dict] = []
    directional_total = sum(abs(row["amount_delta"]) for row in same_direction)
    covered = 0.0
    for row in same_direction:
        if len(selected) >= maximum:
            break
        if not selected or (directional_total and covered / directional_total < coverage_target):
            selected.append(row)
            covered += abs(row["amount_delta"])
    if opposite and len(selected) < maximum:
        minimum_offset = max(0.5, abs(item["amount_delta"]) * offset_share)
        if abs(opposite[0]["amount_delta"]) >= minimum_offset:
            selected.append(opposite[0])
    return selected


def _secondary_driver_paragraph(summary: dict, item: dict, drivers: list[dict]) -> str:
    if not drivers:
        return ""
    unit = summary["currency_unit"]
    main = [row for row in drivers if row["amount_delta"] * item["amount_delta"] > 0]
    offsets = [row for row in drivers if row["amount_delta"] * item["amount_delta"] < 0]
    parts: list[str] = []
    if main:
        main_text = ", ".join(
            f"{row['secondary']}{_subject_particle(row['secondary'])} {abs(row['amount_delta']):,.0f}{unit} {_change_word(row['amount_delta'])}"
            for row in main
        )
        direction = _change_word(item["amount_delta"])
        parts.append(f"하위 분류에서는 {main_text}하면서 {item['primary']} {direction}{_object_particle(direction)} 주도했습니다.")
    if offsets:
        offset_text = ", ".join(
            f"{row['secondary']}{_subject_particle(row['secondary'])} {abs(row['amount_delta']):,.0f}{unit} {_change_word(row['amount_delta'])}"
            for row in offsets
        )
        parts.append(f"반면 {offset_text}해 {item['primary']}의 {_change_word(item['amount_delta'])}폭을 일부 상쇄했습니다.")
    return " ".join(parts)


def _select_recipient_drivers(secondary: dict, recipients: list[dict], config: dict) -> list[dict]:
    related = [
        row for row in recipients
        if row["primary"] == secondary["primary"]
        and row["secondary"] == secondary["secondary"]
        and abs(row["amount_delta"]) > 0.5
    ]
    maximum = int(config["output"].get("narrative_recipients_per_secondary", 3))
    main_maximum = int(config["output"].get("narrative_main_recipients_per_secondary", 2))
    coverage_target = float(config["output"].get("recipient_driver_coverage_ratio", 0.75))
    offset_share = float(config["output"].get("recipient_offset_min_share", 0.2))
    same_direction = sorted(
        (row for row in related if row["amount_delta"] * secondary["amount_delta"] > 0),
        key=lambda row: abs(row["amount_delta"]),
        reverse=True,
    )
    opposite = sorted(
        (row for row in related if row["amount_delta"] * secondary["amount_delta"] < 0),
        key=lambda row: abs(row["amount_delta"]),
        reverse=True,
    )
    selected: list[dict] = []
    directional_total = sum(abs(row["amount_delta"]) for row in same_direction)
    covered = 0.0
    for row in same_direction:
        if len(selected) >= min(main_maximum, maximum):
            break
        if not selected or (directional_total and covered / directional_total < coverage_target):
            selected.append(row)
            covered += abs(row["amount_delta"])
    if opposite and len(selected) < maximum:
        minimum_offset = max(0.5, abs(secondary["amount_delta"]) * offset_share)
        if abs(opposite[0]["amount_delta"]) >= minimum_offset:
            selected.append(opposite[0])
    return selected


def _trend_details(row: dict, year: int, month: int, unit: str) -> str:
    values = [row["monthly_amounts"].get(f"{year}{item_month:02d}", 0.0) for item_month in range(1, month + 1)]
    active_values = [abs(value) for value in values if abs(value) > 0.5]
    active_count = len(active_values)
    volatile = len(active_values) >= 3 and mean(active_values) and pstdev(active_values) / mean(active_values) >= 0.55
    exceptional_status = row["status"] not in {"증가", "감소"}
    if volatile or exceptional_status:
        series = " → ".join(f"{value:,.0f}" for value in values) + unit
        interpretations: list[str] = []
        if active_count == 1:
            interpretations.append("실적이 특정 월에 집중됐습니다")
        elif 1 < active_count < month:
            interpretations.append("출고 월과 미출고 월이 섞인 간헐적 실적입니다")
        if volatile:
            interpretations.append("월별 판매금액 편차가 큰 편입니다")
        if row["status"] in {"신규 실적", "당해 신규"}:
            interpretations.append("보유자료 범위상 신규 실적입니다")
        elif row["status"] not in {"증가", "감소"}:
            interpretations.append(f"{row['status']}{_status_particle(row['status'])} 분류됩니다")
        detail = " ".join(f"{text}." for text in dict.fromkeys(interpretations))
        particle = _destination_particle(unit)
        return f"올해 월별 판매금액은 {series}{particle}, {detail}" if detail else f"올해 월별 판매금액은 {series}입니다."
    if active_count < month:
        return f"올해 1~{month}월 중 {active_count}개월에 출고가 발생했습니다."
    recent = values[-3:]
    if len(recent) == 3 and recent[0] < recent[1] < recent[2]:
        return f"올해 1~{month}월 매월 출고가 이어졌고 최근 3개월 판매금액도 연속 증가했습니다."
    if len(recent) == 3 and recent[0] > recent[1] > recent[2]:
        return f"올해 1~{month}월 매월 출고가 이어졌지만 최근 3개월 판매금액은 연속 감소했습니다."
    return f"올해 1~{month}월 매월 출고가 이어졌습니다."


def _recipient_context_paragraph(summary: dict, row: dict, year: int, month: int) -> str:
    unit = summary["currency_unit"]
    if summary["comparison"] == "전월 대비":
        period_change = f"전월 {row['previous_amount']:,.0f}에서 당월 {row['current_amount']:,.0f}{unit}{_destination_particle(unit)} {_change_word(row['amount_delta'])}"
        ytd_change = f"1~{month}월 누계도 전년 동기 {row['prior_ytd']:,.0f}에서 당해 {row['current_ytd']:,.0f}{unit}{_destination_particle(unit)} {_change_word(row['current_ytd'] - row['prior_ytd'])}"
        context = f"{row['recipient']}향은 {period_change}했고, {ytd_change}했습니다."
    else:
        context = (
            f"{row['recipient']}향 1~{month}월 누계는 전년 동기 {row['previous_amount']:,.0f}에서 "
            f"당해 {row['current_amount']:,.0f}{unit}{_destination_particle(unit)} {_change_word(row['amount_delta'])}했습니다."
        )
    if row["prior_year_exists"] == "없음":
        context += " 보유자료 범위상 전년 동기 실적은 없습니다."
    return f"{context} {_trend_details(row, year, month, unit)}"


def _secondary_recipient_paragraphs(summary: dict, secondary: dict, recipients: list[dict], config: dict, year: int, month: int) -> list[str]:
    drivers = _select_recipient_drivers(secondary, recipients, config)
    if not drivers:
        return []
    unit = summary["currency_unit"]
    main = [row for row in drivers if row["amount_delta"] * secondary["amount_delta"] > 0]
    offsets = [row for row in drivers if row["amount_delta"] * secondary["amount_delta"] < 0]
    parts: list[str] = []
    if main:
        main_text = ", ".join(f"{row['recipient']}향 {signed_number(row['amount_delta'])}{unit}" for row in main)
        parts.append(f"{secondary['secondary']} {_change_word(secondary['amount_delta'])}분은 {main_text} 등이 주요 원인입니다.")
    if offsets:
        offset_text = ", ".join(f"{row['recipient']}향 {signed_number(row['amount_delta'])}{unit}" for row in offsets)
        parts.append(f"반면 {offset_text} 등은 반대 방향으로 작용했습니다.")
    parts.extend(_recipient_context_paragraph(summary, row, year, month) for row in main)
    return parts


def _mix_shift_product_name(shift: dict) -> str:
    return shift["secondary"] if shift["secondary"] != shift["primary"] else shift["primary"]


def _mix_shift_driver_text(rows: list[dict], unit: str) -> str:
    return ", ".join(f"{row['recipient']}향 {abs(row['amount_delta']):,.0f}{unit}" for row in rows)


def _amount_weight_divergence_note(summary: dict, row: dict) -> str:
    unit = summary["currency_unit"]
    price_unit = "천원/kg" if unit == "백만원" else "달러/kg"
    amount_word = _change_word(row["amount_delta"])
    weight_word = _change_word(row["weight_delta"])
    price_word = "상승" if row["current_price"] >= row["previous_price"] else "하락"
    if row["amount_delta"] < 0 < row["weight_delta"]:
        interpretation = "판매금액 감소는 물량 감소보다 평균단가 또는 제품 구성 변화의 영향이 컸던 것으로 보입니다."
    elif row["amount_delta"] > 0 > row["weight_delta"]:
        interpretation = "판매금액 증가는 물량 증가보다 평균단가 또는 제품 구성 변화의 영향이 컸던 것으로 보입니다."
    else:
        interpretation = "판매금액과 제품판매중량이 반대 방향으로 움직여 평균단가 또는 제품 구성 변화의 영향이 컸던 것으로 보입니다."
    return (
        f"특히 {row['recipient']}향 판매금액은 {row['previous_amount']:,.0f}에서 {row['current_amount']:,.0f}{unit}{_destination_particle(unit)} {amount_word}했지만, "
        f"제품판매중량은 {row['previous_weight']:,.1f}에서 {row['current_weight']:,.1f}톤으로 {weight_word}했습니다. "
        f"평균단가는 {row['previous_price']:.2f}에서 {row['current_price']:.2f}{price_unit}{_destination_particle(unit)} {price_word}해, "
        f"{interpretation}"
    )


def _recipient_mix_shift_paragraphs(summary: dict, shifts: list[dict], detailed_products: set[tuple[str, str]]) -> list[str]:
    paragraphs: list[str] = []
    unit = summary["currency_unit"]
    for shift in shifts:
        product_key = (shift["primary"], shift["secondary"])
        if product_key in detailed_products:
            continue
        product = _mix_shift_product_name(shift)
        product_delta = shift["product_amount_delta"]
        if abs(product_delta) > 0.5:
            opening = (
                f"{product}{_topic_particle(product)} {abs(product_delta):,.0f}{unit} {_change_word(product_delta)}했지만, "
                "인수처별 실적 변동은 컸습니다."
            )
        else:
            opening = f"{product} 판매금액은 큰 변화가 없었지만, 인수처별 실적 변동은 컸습니다."
        increases = _mix_shift_driver_text(shift["increase_drivers"], unit)
        decreases = _mix_shift_driver_text(shift["decrease_drivers"], unit)
        if product_delta > 0.5:
            movement = f"{decreases} 등이 감소한 반면, {increases} 등이 증가해 감소분을 상쇄했습니다."
        elif product_delta < -0.5:
            movement = f"{increases} 등이 증가한 반면, {decreases} 등이 감소해 증가분을 상회했습니다."
        else:
            movement = f"{increases} 등이 증가하고 {decreases} 등이 감소해 서로 상쇄했습니다."
        details = " ".join(_amount_weight_divergence_note(summary, row) for row in shift["divergent_recipients"])
        paragraphs.append(" ".join(part for part in (opening, movement, details) if part))
    return paragraphs


def _recipient_analysis_excluded(segment: str, item: dict, config: dict) -> bool:
    exclusions = config["segments"][segment].get("recipient_analysis_exclusions", {})
    excluded_level2 = {str(value).strip().upper() for value in exclusions.get("level2", [])}
    return item["primary"].strip().upper() in excluded_level2


def _uses_secondary_drilldown(segment: str, config: dict) -> bool:
    segment_config = config["segments"][segment]
    return int(segment_config["secondary_level"]) != int(segment_config["primary_level"])


def _focus_paragraphs(
    summary: dict,
    item: dict,
    secondary_items: list[dict],
    recipients: list[dict],
    config: dict,
    segment: str,
    year: int,
    month: int,
) -> list[str]:
    unit = summary["currency_unit"]
    if item["amount_pct"] is None:
        text = (
            f"{item['primary']}의 판매금액은 {item['previous_amount']:,.0f}{unit}에서 {item['current_amount']:,.0f}{unit}{_destination_particle(unit)} "
            f"{_change_word(item['amount_delta'])}했으나, 기준기간 실적이 없어 증감률은 산출하지 않았습니다. "
        )
    else:
        text = (
            f"{item['primary']}의 판매금액은 {item['previous_amount']:,.0f}{unit}에서 {item['current_amount']:,.0f}{unit}{_destination_particle(unit)} "
            f"{_pct_statement(item['amount_pct'], item['amount_delta'])}했습니다. "
        )
    if item["weight_pct"] is None:
        text += "제품판매중량은 기준기간 실적이 없어 증감률을 산출하지 않았습니다."
    else:
        text += f"제품판매중량은 {_pct_statement(item['weight_pct'], item['weight_delta'])}했습니다."
    if item["previous_price"] is not None and item["current_price"] is not None:
        if item["price_pct"] is None:
            text += (
                f" 평균단가는 {item['previous_price']:.2f}에서 {item['current_price']:.2f}{_number_destination_particle(item['current_price'])} "
                "변동했으나 기준단가가 0이어서 증감률은 산출하지 않았습니다."
            )
        else:
            price_change = f"{abs(item['price_pct']) * 100:.1f}% {_change_word(item['current_price'] - item['previous_price'])}"
            text += f" 평균단가는 {item['previous_price']:.2f}에서 {item['current_price']:.2f}{_number_destination_particle(item['current_price'])} {price_change}했습니다."
    paragraphs = [text]
    detail_parts: list[str] = []
    uses_secondary = _uses_secondary_drilldown(segment, config)
    secondary_drivers = _select_secondary_drivers(item, secondary_items, config) if uses_secondary else []
    if uses_secondary:
        secondary_text = _secondary_driver_paragraph(summary, item, secondary_drivers)
        if secondary_text:
            detail_parts.append(secondary_text)
    if _recipient_analysis_excluded(segment, item, config):
        detail_parts.append("제강 CONTROL CABLE은 누계파일 기준 품목 분석에는 포함하되, 인수처 원자료의 품목 분류 이슈로 인수처별 분석에서는 제외했습니다.")
    elif uses_secondary:
        for secondary in secondary_drivers:
            if secondary["amount_delta"] * item["amount_delta"] > 0:
                detail_parts.extend(_secondary_recipient_paragraphs(summary, secondary, recipients, config, year, month))
    else:
        level2_item = {
            "primary": item["primary"],
            "secondary": item["primary"],
            "amount_delta": item["amount_delta"],
        }
        detail_parts.extend(_secondary_recipient_paragraphs(summary, level2_item, recipients, config, year, month))
    if detail_parts:
        paragraphs.append(" ".join(detail_parts))
    return paragraphs


def _region_interpretation(region: dict) -> str:
    amount_pct = region["amount_pct"]
    weight_pct = region["weight_pct"]
    price_pct = region["price_pct"]
    if amount_pct is None or weight_pct is None or price_pct is None:
        return "기준기간 실적이 없어 증감 요인을 추가로 확인해야 합니다."
    if abs(price_pct) < 0.03 and abs(weight_pct) >= 0.05:
        return "평균단가 변동은 크지 않아 제품판매중량 변화가 주요 원인입니다."
    if abs(weight_pct) < 0.03 and abs(price_pct) >= 0.05:
        return "제품판매중량 변화보다 평균단가 및 제품 구성 변화의 영향이 컸습니다."
    if weight_pct > 0 and price_pct > 0:
        return "제품판매중량 증가와 평균단가 상승이 함께 작용했습니다."
    if weight_pct < 0 and price_pct < 0:
        return "제품판매중량 감소와 평균단가 하락이 함께 작용했습니다."
    if amount_pct > 0 and weight_pct < 0:
        return "제품판매중량은 감소했지만 평균단가 및 제품 구성 효과가 이를 상쇄했습니다."
    if amount_pct < 0 and weight_pct > 0:
        return "제품판매중량은 증가했지만 평균단가 및 제품 구성 효과가 판매금액을 낮췄습니다."
    return "제품판매중량과 평균단가·제품 구성 변화가 서로 다른 방향으로 작용했습니다."


def _region_paragraphs(summary: dict, regions: list[dict], config: dict) -> list[str]:
    if not regions:
        return []
    limit = int(config["output"].get("narrative_regions_per_direction", 3))
    increases = _directional(regions, True, limit)
    decreases = _directional(regions, False, limit)
    unit = summary["currency_unit"]
    parts = []
    if increases:
        parts.append(", ".join(f"{row['region']} {abs(row['amount_delta']):,.0f}{unit}" for row in increases) + " 증가")
    if decreases:
        parts.append(", ".join(f"{row['region']} {abs(row['amount_delta']):,.0f}{unit}" for row in decreases) + " 감소")
    paragraphs = ["지역별로는 " + ", 반면 ".join(parts) + "했습니다."] if parts else []
    detail_limit = int(config["output"].get("narrative_region_details_max", 2))
    focus_regions = sorted(increases + decreases, key=lambda row: abs(row["amount_delta"]), reverse=True)[:detail_limit]
    for region in focus_regions:
        amount_change = _pct_statement(region["amount_pct"], region["amount_delta"])
        weight_change = _pct_statement(region["weight_pct"], region["weight_delta"])
        price_change = _pct_statement(region["price_pct"], (region["current_price"] or 0) - (region["previous_price"] or 0))
        paragraphs.append(
            f"{region['region']}{_topic_particle(region['region'])} 판매금액이 {amount_change}했고, 제품판매중량은 {weight_change}, 평균단가는 {price_change}했습니다. "
            f"{_region_interpretation(region)}"
        )
    return paragraphs


def _names_for_conclusion(items: list[dict], positive: bool, limit: int = 3) -> str:
    return "·".join(item["primary"] for item in _directional(items, positive, limit))


def _conclusion_paragraph(summary: dict, items: list[dict], regions: list[dict], recipients: list[dict]) -> str:
    increases = _names_for_conclusion(items, True)
    decreases = _names_for_conclusion(items, False)
    period_text = f"{summary['label']} {summary['comparison']} 실적"
    if summary["amount_delta"] >= 0:
        core = f"{increases} 증가가 {decreases} 감소를 상쇄하면서 전체 판매금액이 증가했습니다" if decreases else f"{increases} 증가로 전체 판매금액이 확대됐습니다"
    else:
        core = f"{decreases} 감소가 {increases} 증가보다 크게 작용해 전체 판매금액이 감소했습니다" if increases else f"{decreases} 감소로 전체 판매금액이 줄었습니다"
    sentence = f"종합하면 {period_text}은 {core}."
    if regions:
        top_region = max(regions, key=lambda row: abs(row["amount_delta"]))
        sentence += f" 지역별로는 {top_region['region']}의 {abs(top_region['amount_delta']):,.0f}{summary['currency_unit']} {_change_word(top_region['amount_delta'])} 영향이 가장 컸습니다."
    volatile = [
        row["recipient"]
        for row in sorted(recipients, key=lambda value: abs(value["amount_delta"]), reverse=True)
        if row["status"] in {"전월 고실적 기저", "출고 재개", "당월 미출고", "당해 신규", "당해 미출고"}
    ]
    if volatile:
        names = "·".join(dict.fromkeys(volatile[:3]))
        sentence += f" 다만 {names}향은 출고 공백이나 월별 변동이 확인돼, 현재 흐름의 지속 여부는 담당자 확인이 필요합니다."
    return sentence


def _focus_recipients(focus: list[dict], secondary_items: list[dict], recipients: list[dict], config: dict, segment: str) -> list[dict]:
    selected: list[dict] = []
    for item in focus:
        if _recipient_analysis_excluded(segment, item, config):
            continue
        if _uses_secondary_drilldown(segment, config):
            drivers = _select_secondary_drivers(item, secondary_items, config)
        else:
            drivers = [{"primary": item["primary"], "secondary": item["primary"], "amount_delta": item["amount_delta"]}]
        for secondary in drivers:
            if secondary["amount_delta"] * item["amount_delta"] <= 0:
                continue
            selected.extend(
                row
                for row in _select_recipient_drivers(secondary, recipients, config)
                if row["amount_delta"] * secondary["amount_delta"] > 0
            )
    return selected


def _focus_recipient_product_keys(focus: list[dict], secondary_items: list[dict], config: dict, segment: str) -> set[tuple[str, str]]:
    selected: set[tuple[str, str]] = set()
    for item in focus:
        if _recipient_analysis_excluded(segment, item, config):
            continue
        if _uses_secondary_drilldown(segment, config):
            drivers = _select_secondary_drivers(item, secondary_items, config)
            selected.update(
                (row["primary"], row["secondary"])
                for row in drivers
                if row["amount_delta"] * item["amount_delta"] > 0
            )
        else:
            selected.add((item["primary"], item["primary"]))
    return selected


def build_markdown(analysis: dict, official, config: dict) -> str:
    year, month = analysis["year"], analysis["month"]
    lines = [
        f"# {year}년 {month}월 매출실적 분석 초안",
        "",
        f"> 검산 상태: **{analysis['model_status']}**  ",
        "> 판매금액·제품판매중량·평균단가와 품목·지역 증감은 전년·당해 누계파일을 기준으로 계산했습니다. 합섬·스텐은 레벨1명에서 레벨2명·인수처로 내려가고, 제강은 레벨2명에서 바로 인수처·월별 추이로 연결합니다. 품목 순증감이 작아도 인수처별 증가·감소가 동시에 큰 경우에는 구성 변화로 별도 표시했습니다.",
        "",
    ]
    for index, segment in enumerate(config["report_order"], 1):
        label = config["segments"][segment]["label"]
        market = config["segments"][segment]["market"]
        lines.extend([f"## {index}. {label}", ""])
        for comparison, heading in (("전월 대비", "전월 대비"), ("누계", "누계")):
            summary = next(row for row in analysis["summary"] if row["segment"] == segment and row["comparison"] == comparison)
            items = [row for row in analysis["items"] if row["segment"] == segment and row["comparison"] == comparison]
            secondary_items = [row for row in analysis["secondary_items"] if row["segment"] == segment and row["comparison"] == comparison]
            recipients = [row for row in analysis["recipients"] if row["segment"] == segment and row["comparison"] == comparison]
            mix_shifts = [row for row in analysis["recipient_mix_shifts"] if row["segment"] == segment and row["comparison"] == comparison]
            regions = [row for row in analysis["regions"] if row["segment"] == segment and row["comparison"] == comparison]
            lines.extend([f"### {heading}", "", _summary_paragraph(summary, month), "", _driver_paragraph(summary), "", _item_paragraph(summary, items), ""])
            focus = _select_focus_items(summary, items, config, market)
            for item in focus:
                for paragraph in _focus_paragraphs(summary, item, secondary_items, recipients, config, segment, year, month):
                    lines.extend([paragraph, ""])
            detailed_products = _focus_recipient_product_keys(focus, secondary_items, config, segment)
            for paragraph in _recipient_mix_shift_paragraphs(summary, mix_shifts, detailed_products):
                lines.extend([paragraph, ""])
            for paragraph in _region_paragraphs(summary, regions, config):
                lines.extend([paragraph, ""])
            focus_recipients = _focus_recipients(focus, secondary_items, recipients, config, segment)
            lines.extend([_conclusion_paragraph(summary, items, regions, focus_recipients), ""])
        warnings = [row for row in analysis["checks"] if row["segment"] == segment and row["status"] == "WARN"]
        if warnings:
            descriptions = ", ".join(f"{row['check']} 일치율 {row['match_pct'] * 100:.1f}%" if row["match_pct"] is not None else row["check"] for row in warnings)
            lines.extend([
                f"※ {descriptions}로 누계파일 계산값과 공식 실적표가 일치하지 않습니다. 계정·상품 제외 기준 또는 공식표 수식을 확인한 뒤 보고해야 합니다.",
                "",
            ])

    lines.extend(["## 추가 확인사항", ""])
    if analysis["questions"]:
        for question in analysis["questions"]:
            lines.append(f"{question['no']}. **{question['segment']} · {question['type']}** — {question['question']} ({question['basis']})")
    else:
        lines.append("추가 확인사항 없음")
    lines.extend(["", "---", "", "이 문안은 누계 수치자료와 인수처별 월별 출고 패턴을 기준으로 생성한 초안입니다. 일회성 수주, 실제 판매가격 조정, 프로젝트 여부와 향후 출고계획은 담당자 확인 후 별도로 보완해야 합니다."])
    return "\n".join(lines) + "\n"
