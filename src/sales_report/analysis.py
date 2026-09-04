from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .models import CumulativeDataset, OfficialReport, RecipientDataset
from .utils import pct_change, previous_period, safe_unit_price


def _blank_aggregate() -> dict:
    return {"amount": 0.0, "weight": 0.0, "rows": 0}


def aggregate(rows: Iterable[dict], predicate: Callable[[dict], bool], key_fn: Callable[[dict], object]) -> dict:
    result = defaultdict(_blank_aggregate)
    for row in rows:
        if not predicate(row):
            continue
        key = key_fn(row)
        target = result[key]
        target["amount"] += row.get("amount", 0.0)
        target["weight"] += row.get("weight", 0.0)
        target["rows"] += 1
    return dict(result)


def compare_groups(previous: dict, current: dict) -> list[dict]:
    compared = []
    for key in previous.keys() | current.keys():
        previous_values = previous.get(key, _blank_aggregate())
        current_values = current.get(key, _blank_aggregate())
        previous_price = safe_unit_price(previous_values["amount"], previous_values["weight"])
        current_price = safe_unit_price(current_values["amount"], current_values["weight"])
        compared.append(
            {
                "key": key,
                "previous_amount": previous_values["amount"],
                "current_amount": current_values["amount"],
                "amount_delta": current_values["amount"] - previous_values["amount"],
                "amount_pct": pct_change(current_values["amount"], previous_values["amount"]),
                "previous_weight": previous_values["weight"],
                "current_weight": current_values["weight"],
                "weight_delta": current_values["weight"] - previous_values["weight"],
                "weight_pct": pct_change(current_values["weight"], previous_values["weight"]),
                "previous_price": previous_price,
                "current_price": current_price,
                "price_pct": (
                    pct_change(current_price, previous_price)
                    if previous_price is not None and current_price is not None
                    else None
                ),
                "previous_rows": previous_values["rows"],
                "current_rows": current_values["rows"],
            }
        )
    return sorted(compared, key=lambda item: item["amount_delta"], reverse=True)


def _period_predicates(target_period: str):
    year, month = int(target_period[:4]), int(target_period[4:])
    previous = previous_period(target_period)
    return {
        "전월 대비": (
            lambda row: row["period"] == previous,
            lambda row: row["period"] == target_period,
        ),
        "누계": (
            lambda row: row["year"] == year - 1 and row["month"] <= month,
            lambda row: row["year"] == year and row["month"] <= month,
        ),
    }


def _totals(rows: list[dict], predicate: Callable[[dict], bool]) -> dict:
    return aggregate(rows, predicate, lambda _: "TOTAL").get("TOTAL", _blank_aggregate())


def _summary_row(segment: str, label: str, comparison: str, currency_unit: str, previous: dict, current: dict) -> dict:
    previous_price = safe_unit_price(previous["amount"], previous["weight"])
    current_price = safe_unit_price(current["amount"], current["weight"])
    amount_delta = current["amount"] - previous["amount"]
    volume_effect = (current["weight"] - previous["weight"]) * previous_price if previous_price is not None else 0.0
    return {
        "segment": segment,
        "label": label,
        "comparison": comparison,
        "currency_unit": currency_unit,
        "previous_amount": previous["amount"],
        "current_amount": current["amount"],
        "amount_delta": amount_delta,
        "amount_pct": pct_change(current["amount"], previous["amount"]),
        "previous_weight": previous["weight"],
        "current_weight": current["weight"],
        "weight_delta": current["weight"] - previous["weight"],
        "weight_pct": pct_change(current["weight"], previous["weight"]),
        "previous_price": previous_price,
        "current_price": current_price,
        "price_pct": pct_change(current_price, previous_price) if previous_price is not None and current_price is not None else None,
        "volume_effect": volume_effect,
        "price_mix_effect": amount_delta - volume_effect,
    }


def _status_for_monthly(item: dict, monthly_amounts: dict[str, float], target_period: str) -> str:
    current, previous = item["current_amount"], item["previous_amount"]
    target_year, target_month = int(target_period[:4]), int(target_period[4:])
    earlier_current_year = sum(
        value
        for period, value in monthly_amounts.items()
        if period.isdigit() and int(period[:4]) == target_year and int(period[4:]) < target_month
    )
    prior_ytd = sum(
        value
        for period, value in monthly_amounts.items()
        if period.isdigit() and int(period[:4]) == target_year - 1 and int(period[4:]) <= target_month
    )
    if abs(current) > 1e-12 and abs(previous) < 1e-12:
        if abs(earlier_current_year) > 1e-12:
            return "출고 재개"
        if abs(prior_ytd) < 1e-12:
            return "신규 실적"
        return "전월 미출고 후 당월 실적"
    if abs(current) < 1e-12 and abs(previous) > 1e-12:
        return "당월 미출고"
    before_target = [
        value
        for period, value in monthly_amounts.items()
        if period.isdigit() and int(period[:4]) == target_year and int(period[4:]) < target_month
    ]
    if current < previous and before_target and previous >= max(before_target):
        return "전월 고실적 기저"
    return "증가" if item["amount_delta"] >= 0 else "감소"


def _status_for_ytd(item: dict) -> str:
    if abs(item["current_amount"]) > 1e-12 and abs(item["previous_amount"]) < 1e-12:
        return "당해 신규"
    if abs(item["current_amount"]) < 1e-12 and abs(item["previous_amount"]) > 1e-12:
        return "당해 미출고"
    return "증가" if item["amount_delta"] >= 0 else "감소"


def _select_both_directions(items: list[dict], count: int) -> list[dict]:
    increases = [item for item in items if item["amount_delta"] > 0][:count]
    decreases = sorted((item for item in items if item["amount_delta"] < 0), key=lambda item: item["amount_delta"])[:count]
    return sorted(increases + decreases, key=lambda item: abs(item["amount_delta"]), reverse=True)


def _mix_driver_payload(item: dict, name_lookup: dict[tuple[str, str, str], str]) -> dict:
    primary, secondary, recipient_key = item["key"]
    return {
        "primary": primary,
        "secondary": secondary,
        "recipient": name_lookup.get((primary, secondary, recipient_key), "(미지정)"),
        "recipient_key": recipient_key,
        **{key: value for key, value in item.items() if key != "key"},
    }


def _select_mix_drivers(items: list[dict], side_total: float, maximum: int, minimum_share: float) -> list[dict]:
    selected = [item for item in items if abs(item["amount_delta"]) >= max(0.5, side_total * minimum_share)]
    return selected[:maximum] or items[:1]


def _detect_recipient_mix_shift(
    segment: str,
    label: str,
    comparison: str,
    primary: str,
    secondary: str,
    product: dict,
    recipient_items: list[dict],
    name_lookup: dict[tuple[str, str, str], str],
    config: dict,
) -> dict | None:
    rules = config.get("output", {}).get("recipient_mix_shift", {})
    if not rules.get("enabled", True):
        return None
    if comparison not in rules.get("comparisons", ["전월 대비"]):
        return None
    market = config["segments"][segment]["market"]
    increases = sorted(
        (item for item in recipient_items if item["amount_delta"] > 0.5),
        key=lambda item: item["amount_delta"],
        reverse=True,
    )
    decreases = sorted(
        (item for item in recipient_items if item["amount_delta"] < -0.5),
        key=lambda item: item["amount_delta"],
    )
    gross_increase = sum(item["amount_delta"] for item in increases)
    gross_decrease = -sum(item["amount_delta"] for item in decreases)
    gross_movement = gross_increase + gross_decrease
    if not increases or not decreases or gross_movement <= 0:
        return None
    minimum_side = float(rules.get("minimum_side_amount", {}).get(market, 50))
    minimum_gross = float(rules.get("minimum_gross_amount", {}).get(market, 200))
    balance_ratio = min(gross_increase, gross_decrease) / max(gross_increase, gross_decrease)
    recipient_net = gross_increase - gross_decrease
    net_share = abs(recipient_net) / gross_movement
    if (
        min(gross_increase, gross_decrease) < minimum_side
        or gross_movement < minimum_gross
        or balance_ratio < float(rules.get("minimum_balance_ratio", 0.35))
        or net_share > float(rules.get("maximum_net_share", 0.45))
    ):
        return None

    minimum_driver_share = float(rules.get("minimum_driver_share", 0.08))
    increase_drivers = _select_mix_drivers(
        increases,
        gross_increase,
        int(rules.get("increase_recipients_max", 3)),
        minimum_driver_share,
    )
    decrease_drivers = _select_mix_drivers(
        decreases,
        gross_decrease,
        int(rules.get("decrease_recipients_max", 2)),
        minimum_driver_share,
    )
    increase_payload = [_mix_driver_payload(item, name_lookup) for item in increase_drivers]
    decrease_payload = [_mix_driver_payload(item, name_lookup) for item in decrease_drivers]
    divergence_threshold = float(rules.get("price_divergence_min_pct", 0.10))
    divergent = [
        row
        for row in decrease_payload + increase_payload
        if row["amount_delta"] * row["weight_delta"] < 0
        and row["previous_price"] is not None
        and row["current_price"] is not None
        and row["price_pct"] is not None
        and abs(row["price_pct"]) >= divergence_threshold
    ][: int(rules.get("price_divergence_notes_max", 1))]
    return {
        "segment": segment,
        "label": label,
        "comparison": comparison,
        "primary": primary,
        "secondary": secondary,
        "product_previous_amount": product["previous_amount"],
        "product_current_amount": product["current_amount"],
        "product_amount_delta": product["amount_delta"],
        "gross_increase": gross_increase,
        "gross_decrease": gross_decrease,
        "gross_movement": gross_movement,
        "recipient_net": recipient_net,
        "net_share": net_share,
        "balance_ratio": balance_ratio,
        "increase_drivers": increase_payload,
        "decrease_drivers": decrease_payload,
        "divergent_recipients": divergent,
    }


def _subject_particle(value: str) -> str:
    if not value:
        return "이"
    last = value[-1]
    if "가" <= last <= "힣":
        return "이" if (ord(last) - ord("가")) % 28 else "가"
    return "이"


def _check_row(segment: str, label: str, check: str, calculated: float, official_value: float, unit: str, source: str, warning_pct: float) -> dict:
    difference = calculated - official_value
    gap_pct = abs(difference) / max(abs(official_value), 1.0)
    status = "PASS" if gap_pct <= warning_pct else "WARN"
    return {
        "segment": segment,
        "label": label,
        "check": check,
        "official": official_value,
        "calculated": calculated,
        "difference": difference,
        "match_pct": calculated / official_value if abs(official_value) > 1e-12 else None,
        "unit": unit,
        "status": status,
        "where_to_fix": source if status == "WARN" else "-",
        "notes": "누계파일 계산값과 공식표 비교",
    }


def build_analysis(
    official: OfficialReport,
    cumulative_datasets: dict[str, CumulativeDataset],
    recipient_datasets: dict[str, RecipientDataset],
    target_period: str,
    config: dict,
) -> dict:
    year, month = int(target_period[:4]), int(target_period[4:])
    predicates = _period_predicates(target_period)
    previous_month = previous_period(target_period)
    summary_rows: list[dict] = []
    item_rows: list[dict] = []
    secondary_rows: list[dict] = []
    recipient_rows: list[dict] = []
    recipient_mix_shift_rows: list[dict] = []
    region_rows: list[dict] = []
    trend_rows: list[dict] = []
    checks: list[dict] = []
    questions: list[dict] = []
    sources: list[dict] = []
    comparison_cache: dict[tuple[str, str], list[dict]] = {}

    warning_pct = config["thresholds"]["official_reconciliation_warning_pct"] / 100
    top_recipients = int(config["output"]["top_recipients_per_item_direction"])
    trend_limit = int(config["output"]["monthly_trend_recipients_per_segment"])

    for segment in config["report_order"]:
        cumulative = cumulative_datasets[segment]
        recipients = recipient_datasets[segment]
        metric = official.metrics[segment]
        rows = cumulative.rows
        unit = metric.currency_unit
        source_label = ", ".join(source["file"] for source in cumulative.sources)
        primary_monthly = aggregate(
            rows,
            lambda row: row["year"] == year and row["month"] <= month,
            lambda row: (row["primary"], row["period"]),
        )
        primary_monthly_lookup: dict[str, dict[str, float]] = defaultdict(dict)
        for (primary, period), values in primary_monthly.items():
            primary_monthly_lookup[primary][period] = values["amount"]

        period_totals = {
            "previous_month": _totals(rows, lambda row: row["period"] == previous_month),
            "current_month": _totals(rows, lambda row: row["period"] == target_period),
            "prior_ytd": _totals(rows, lambda row: row["year"] == year - 1 and row["month"] <= month),
            "current_ytd": _totals(rows, lambda row: row["year"] == year and row["month"] <= month),
        }
        summary_rows.extend(
            [
                _summary_row(segment, metric.label, "전월 대비", unit, period_totals["previous_month"], period_totals["current_month"]),
                _summary_row(segment, metric.label, "누계", unit, period_totals["prior_ytd"], period_totals["current_ytd"]),
            ]
        )

        check_specs = [
            ("전월 판매금액", period_totals["previous_month"]["amount"], metric.previous_amount, unit),
            ("전월 제품판매중량", period_totals["previous_month"]["weight"], metric.previous_weight, "톤"),
            ("당월 판매금액", period_totals["current_month"]["amount"], metric.current_amount, unit),
            ("당월 제품판매중량", period_totals["current_month"]["weight"], metric.current_weight, "톤"),
            ("전년동기 누계 판매금액", period_totals["prior_ytd"]["amount"], metric.prior_ytd_amount, unit),
            ("전년동기 누계 제품판매중량", period_totals["prior_ytd"]["weight"], metric.prior_ytd_weight, "톤"),
            ("당해 누계 판매금액", period_totals["current_ytd"]["amount"], metric.current_ytd_amount, unit),
            ("당해 누계 제품판매중량", period_totals["current_ytd"]["weight"], metric.current_ytd_weight, "톤"),
        ]
        for check, calculated, official_value, check_unit in check_specs:
            checks.append(_check_row(segment, metric.label, check, calculated, official_value, check_unit, source_label, warning_pct))

        for source in cumulative.sources + recipients.sources:
            sources.append({"segment": segment, "label": metric.label, **source, "period": target_period})

        for comparison, (previous_predicate, current_predicate) in predicates.items():
            primary_comparison = compare_groups(
                aggregate(rows, previous_predicate, lambda row: row["primary"]),
                aggregate(rows, current_predicate, lambda row: row["primary"]),
            )
            comparison_cache[(segment, comparison)] = primary_comparison
            for rank, item in enumerate(primary_comparison, 1):
                primary = item["key"]
                item_rows.append(
                    {
                        "segment": segment,
                        "label": metric.label,
                        "comparison": comparison,
                        "rank": rank,
                        "primary": primary,
                        "monthly_amounts": {
                            f"{year}{item_month:02d}": primary_monthly_lookup[primary].get(f"{year}{item_month:02d}", 0.0)
                            for item_month in range(1, month + 1)
                        },
                        **{key: value for key, value in item.items() if key != "key"},
                    }
                )

            if int(config["segments"][segment]["secondary_level"]) != int(config["segments"][segment]["primary_level"]):
                secondary_comparison = compare_groups(
                    aggregate(rows, previous_predicate, lambda row: (row["primary"], row["secondary"])),
                    aggregate(rows, current_predicate, lambda row: (row["primary"], row["secondary"])),
                )
                for rank, item in enumerate(secondary_comparison, 1):
                    primary, secondary = item["key"]
                    secondary_rows.append(
                        {"segment": segment, "label": metric.label, "comparison": comparison, "rank": rank, "primary": primary, "secondary": secondary, **{key: value for key, value in item.items() if key != "key"}}
                    )

            if metric.market == "export":
                region_comparison = compare_groups(
                    aggregate(rows, previous_predicate, lambda row: row["region"]),
                    aggregate(rows, current_predicate, lambda row: row["region"]),
                )
                for rank, item in enumerate(region_comparison, 1):
                    region_rows.append(
                        {"segment": segment, "label": metric.label, "comparison": comparison, "rank": rank, "region": item["key"], **{key: value for key, value in item.items() if key != "key"}}
                    )

        recipient_monthly = aggregate(
            recipients.rows,
            lambda row: True,
            lambda row: (row["primary"], row["secondary"], row["recipient_key"], row["period"]),
        )
        monthly_lookup: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
        name_lookup: dict[tuple[str, str, str], str] = {}
        for row in sorted(recipients.rows, key=lambda value: value["year"]):
            name_lookup[(row["primary"], row["secondary"], row["recipient_key"])] = row["recipient_name"]
        for (primary, secondary, recipient_key, period), values in recipient_monthly.items():
            monthly_lookup[(primary, secondary, recipient_key)][period] = values["amount"]

        selected_for_trend: list[dict] = []
        for comparison, (previous_predicate, current_predicate) in predicates.items():
            recipient_comparison = compare_groups(
                aggregate(recipients.rows, previous_predicate, lambda row: (row["primary"], row["secondary"], row["recipient_key"])),
                aggregate(recipients.rows, current_predicate, lambda row: (row["primary"], row["secondary"], row["recipient_key"])),
            )
            by_secondary: dict[tuple[str, str], list[dict]] = defaultdict(list)
            for item in recipient_comparison:
                by_secondary[item["key"][:2]].append(item)
            mix_candidates: list[dict] = []
            for (primary, secondary), secondary_items in by_secondary.items():
                uses_secondary = int(config["segments"][segment]["secondary_level"]) != int(config["segments"][segment]["primary_level"])
                product_rows = secondary_rows if uses_secondary else item_rows
                product = next(
                    (
                        row
                        for row in product_rows
                        if row["segment"] == segment
                        and row["comparison"] == comparison
                        and row["primary"] == primary
                        and (not uses_secondary or row["secondary"] == secondary)
                    ),
                    None,
                )
                if product is not None:
                    mix_shift = _detect_recipient_mix_shift(
                        segment,
                        metric.label,
                        comparison,
                        primary,
                        secondary,
                        product,
                        secondary_items,
                        name_lookup,
                        config,
                    )
                    if mix_shift is not None:
                        mix_candidates.append(mix_shift)
                for rank, item in enumerate(_select_both_directions(secondary_items, top_recipients), 1):
                    _, _, recipient_key = item["key"]
                    monthly_amounts = monthly_lookup[(primary, secondary, recipient_key)]
                    recipient_name = name_lookup.get((primary, secondary, recipient_key), "(미지정)")
                    prior_same_month = monthly_amounts.get(f"{year - 1}{month:02d}", 0.0)
                    prior_ytd = sum(monthly_amounts.get(f"{year - 1}{item_month:02d}", 0.0) for item_month in range(1, month + 1))
                    current_ytd = sum(monthly_amounts.get(f"{year}{item_month:02d}", 0.0) for item_month in range(1, month + 1))
                    status = _status_for_monthly(item, monthly_amounts, target_period) if comparison == "전월 대비" else _status_for_ytd(item)
                    record = {
                        "segment": segment,
                        "label": metric.label,
                        "comparison": comparison,
                        "rank": rank,
                        "primary": primary,
                        "secondary": secondary,
                        "recipient": recipient_name,
                        "recipient_key": recipient_key,
                        "status": status,
                        "prior_same_month": prior_same_month,
                        "prior_ytd": prior_ytd,
                        "current_ytd": current_ytd,
                        "prior_year_exists": "있음" if abs(prior_ytd) > 1e-12 else "없음",
                        "monthly_amounts": {
                            f"{year}{item_month:02d}": monthly_amounts.get(f"{year}{item_month:02d}", 0.0)
                            for item_month in range(1, month + 1)
                        },
                        **{key: value for key, value in item.items() if key != "key"},
                    }
                    recipient_rows.append(record)
                    selected_for_trend.append(record)
            mix_limit = int(config.get("output", {}).get("recipient_mix_shift", {}).get("max_products_per_segment_comparison", 2))
            recipient_mix_shift_rows.extend(
                sorted(mix_candidates, key=lambda row: row["gross_movement"], reverse=True)[:mix_limit]
            )

        unique_trends: list[tuple[str, str, str, str]] = []
        for record in sorted(selected_for_trend, key=lambda item: abs(item["amount_delta"]), reverse=True):
            key = (record["primary"], record["secondary"], record["recipient_key"], record["recipient"])
            if key not in unique_trends:
                unique_trends.append(key)
            if len(unique_trends) >= trend_limit:
                break
        for primary, secondary, recipient_key, recipient_name in unique_trends:
            values = monthly_lookup[(primary, secondary, recipient_key)]
            trend = {
                "segment": segment,
                "label": metric.label,
                "primary": primary,
                "secondary": secondary,
                "recipient": recipient_name,
                "prior_ytd": sum(values.get(f"{year - 1}{item_month:02d}", 0.0) for item_month in range(1, month + 1)),
                "current_ytd": sum(values.get(f"{year}{item_month:02d}", 0.0) for item_month in range(1, month + 1)),
            }
            trend["ytd_delta"] = trend["current_ytd"] - trend["prior_ytd"]
            for trend_year in (year - 1, year):
                for item_month in range(1, month + 1):
                    trend[f"{trend_year}{item_month:02d}"] = values.get(f"{trend_year}{item_month:02d}", 0.0)
            trend_rows.append(trend)

    question_number = 1
    for check in checks:
        if check["status"] == "WARN":
            questions.append(
                {
                    "no": question_number,
                    "segment": check["label"],
                    "type": "공식표 검산",
                    "question": f"{check['check']}이 공식표와 누계파일 간 {abs(check['difference']):,.1f}{check['unit']} 차이 납니다. 계정·상품 제외 기준 또는 공식표 수식을 확인해야 합니다.",
                    "basis": f"일치율 {(check['match_pct'] or 0) * 100:.1f}%",
                }
            )
            question_number += 1

    price_threshold = config["thresholds"]["unit_price_question_pct"] / 100
    for summary in summary_rows:
        if summary["price_pct"] is not None and abs(summary["price_pct"]) >= price_threshold:
            questions.append(
                {
                    "no": question_number,
                    "segment": summary["label"],
                    "type": "평균단가",
                    "question": f"{summary['comparison']} 평균단가가 {summary['price_pct'] * 100:+.1f}% 변동했습니다. 실제 판매가격 조정인지, 제품·규격 구성 변화인지 확인이 필요합니다.",
                    "basis": f"{summary['previous_price']:.2f} → {summary['current_price']:.2f}",
                }
            )
            question_number += 1

    for segment in config["report_order"]:
        market = config["segments"][segment]["market"]
        threshold = config["thresholds"]["large_amount_change"][market]
        notable = [
            row
            for row in recipient_rows
            if row["segment"] == segment
            and row["comparison"] == "전월 대비"
            and row["status"] in {"신규 실적", "출고 재개", "당월 미출고"}
            and abs(row["amount_delta"]) >= threshold
        ]
        for row in sorted(notable, key=lambda item: abs(item["amount_delta"]), reverse=True)[:4]:
            has_secondary_drilldown = (
                int(config["segments"][segment]["secondary_level"])
                != int(config["segments"][segment]["primary_level"])
            )
            product_label = f"{row['primary']} 중 {row['secondary']}" if has_secondary_drilldown else row["primary"]
            if row["status"] == "당월 미출고":
                question = f"{row['recipient']}향 {product_label} 실적이 당월 발생하지 않았습니다. 이후 출고 재개 시점 확인이 필요합니다."
            else:
                question = f"{row['recipient']}향 {product_label} {row['status']}{_subject_particle(row['status'])} 확인됩니다. 반복 출고 여부를 확인할 필요가 있습니다."
            questions.append(
                {
                    "no": question_number,
                    "segment": row["label"],
                    "type": row["status"],
                    "question": question,
                    "basis": f"인수처 파일 기준 증감 {row['amount_delta']:+,.0f}{official.metrics[segment].currency_unit}",
                }
            )
            question_number += 1

    model_status = "WARN" if any(check["status"] == "WARN" for check in checks) else "PASS"
    return {
        "target_period": target_period,
        "year": year,
        "month": month,
        "model_status": model_status,
        "summary": summary_rows,
        "items": item_rows,
        "secondary_items": secondary_rows,
        "recipients": recipient_rows,
        "recipient_mix_shifts": recipient_mix_shift_rows,
        "regions": region_rows,
        "trends": trend_rows,
        "checks": checks,
        "questions": questions,
        "sources": sources,
        "comparison_cache": comparison_cache,
        "data_roles": [
            {"source": "전년·당해 누계파일", "used_for": "전체·품목·지역의 판매금액, 제품판매중량, 평균단가, 증감 분석", "not_used_for": "인수처 식별"},
            {"source": "전년·당해 인수처 파일 12개", "used_for": "인수처별 판매금액·중량·평균단가, 전년 실적 존재 여부, 신규·재개·미출고, 월별 추이, 인수처 구성 변화", "not_used_for": "전체 KPI·평균단가 계산 및 공식표 검산"},
            {"source": "사업계획대비매출실적분석", "used_for": "누계파일 계산값의 공식 검산", "not_used_for": "인수처별 원인 추정"},
        ],
    }
