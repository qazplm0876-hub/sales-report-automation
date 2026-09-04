"""매출실적 보고서와 보조 분석에서 공통으로 사용하는 집계 규칙."""

STEEL_GS_LEVEL1 = ["스틸로프", "스틸선재", "스틸ＳＴ"]

# 월간 브리핑에서 중요 변동을 선별하는 기본 기준.
# 계산은 모든 품목에 대해 수행하고, 아래 기준은 코멘트 출력 여부에만 사용한다.
COMMENT_THRESHOLDS = {
    "division_sales_pct": 5.0,
    "product_sales_pct": 5.0,
    "volume_pct": 20.0,
    "unit_price_pct": 10.0,
    "max_products": 3,
    "max_customers": 4,
    "max_price_causes": 2,
}


def plan_month_row(month):
    """월별 사업계획 시트에서 해당 월의 행번호를 반환한다."""
    if not 1 <= month <= 12:
        raise ValueError("month 값은 1부터 12 사이여야 합니다.")
    return 5 + month + (month - 1) // 3


def ytd_monthly_plan(ws, base_month_row, column, month):
    """분기 합계행을 제외하고 1월부터 대상 월까지 월별 계획을 합산한다."""
    section_offset = base_month_row - plan_month_row(month)
    return sum(
        ws.cell(
            row=plan_month_row(plan_month) + section_offset,
            column=column,
        ).value or 0
        for plan_month in range(1, month + 1)
    )


# 제품판매단가 보고서 83~106행과 동일한 본사 품목 매핑.
# 원자료 집계와 코멘트 원인탐색이 같은 분류를 사용하도록 한 곳에서 관리한다.
REPORT_PRODUCT_RULES = [
    {
        "row": 83, "division": "합섬", "sales_type": "수출", "label": "방사",
        "level1": ("합섬방사",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 84, "division": "합섬", "sales_type": "수출", "label": "비방사",
        "level1": ("합섬비방사",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 85, "division": "합섬", "sales_type": "수출", "label": "웨빙",
        "level1": ("합섬웨빙",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 86, "division": "합섬", "sales_type": "수출", "label": "슈퍼맥스",
        "level1": ("합섬특수",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 87, "division": "합섬", "sales_type": "내수", "label": "방사",
        "level1": ("합섬방사",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 88, "division": "합섬", "sales_type": "내수", "label": "비방사",
        "level1": ("합섬비방사",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 89, "division": "합섬", "sales_type": "내수", "label": "웨빙",
        "level1": ("합섬웨빙",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 90, "division": "합섬", "sales_type": "내수", "label": "슈퍼맥스",
        "level1": ("합섬특수",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 91, "division": "스텐", "sales_type": "수출", "label": "로프",
        "level1": ("스텐로프",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 92, "division": "스텐", "sales_type": "수출", "label": "선재",
        "level1": ("스텐선재",), "level2": None, "amount_col": "달러금액",
    },
    {
        "row": 93, "division": "스텐", "sales_type": "내수", "label": "로프",
        "level1": ("스텐로프",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 94, "division": "스텐", "sales_type": "내수", "label": "선재",
        "level1": ("스텐선재",), "level2": None, "amount_col": "한국원화금액",
    },
    {
        "row": 95, "division": "제강", "sales_type": "수출", "label": "WR",
        "level1": ("스틸로프",),
        "level2": ("WIRE ROPE", "SPECIAL ROPE 1", "SPECIAL ROPE 2"),
        "amount_col": "달러금액",
    },
    {
        "row": 96, "division": "제강", "sales_type": "수출", "label": "C/C",
        "level1": ("스틸로프",), "level2": ("CONTROL CABLE",),
        "amount_col": "달러금액",
    },
    {
        "row": 97, "division": "제강", "sales_type": "수출", "label": "G/S",
        "level1": ("스틸ＳＴ",), "level2": ("GUY STRAND",),
        "amount_col": "달러금액",
    },
    {
        "row": 98, "division": "제강", "sales_type": "수출", "label": "WIRE",
        "level1": ("스틸선재",), "level2": ("WIRE",),
        "amount_col": "달러금액",
    },
    {
        "row": 99, "division": "제강", "sales_type": "수출", "label": "OT",
        "level1": ("스틸선재",), "level2": ("OT WIRE",),
        "amount_col": "달러금액",
    },
    {
        "row": 100, "division": "제강", "sales_type": "수출", "label": "IT",
        "level1": ("스틸선재",), "level2": ("IT WIRE",),
        "amount_col": "달러금액",
    },
    {
        "row": 101, "division": "제강", "sales_type": "내수", "label": "WR",
        "level1": ("스틸로프",),
        "level2": ("WIRE ROPE", "SPECIAL ROPE 1", "SPECIAL ROPE 2"),
        "amount_col": "한국원화금액",
    },
    {
        "row": 102, "division": "제강", "sales_type": "내수", "label": "C/C",
        "level1": ("스틸로프",), "level2": ("CONTROL CABLE",),
        "amount_col": "한국원화금액",
    },
    {
        "row": 103, "division": "제강", "sales_type": "내수", "label": "G/S",
        "level1": ("스틸ＳＴ",), "level2": ("GUY STRAND",),
        "amount_col": "한국원화금액",
    },
    {
        "row": 104, "division": "제강", "sales_type": "내수", "label": "WIRE",
        "level1": ("스틸선재",), "level2": ("WIRE",),
        "amount_col": "한국원화금액",
    },
    {
        "row": 105, "division": "제강", "sales_type": "내수", "label": "OT",
        "level1": ("스틸선재",), "level2": ("OT WIRE",),
        "amount_col": "한국원화금액",
    },
    {
        "row": 106, "division": "제강", "sales_type": "내수", "label": "IT",
        "level1": ("스틸선재",), "level2": ("IT WIRE",),
        "amount_col": "한국원화금액",
    },
]


def report_product_rules(division=None, sales_type=None):
    """조건에 맞는 제품판매단가 보고서 품목 매핑을 반환한다."""
    rules = REPORT_PRODUCT_RULES
    if division is not None:
        rules = [rule for rule in rules if rule["division"] == division]
    if sales_type is not None:
        rules = [rule for rule in rules if rule["sales_type"] == sales_type]
    return rules


def steel_gs_weight(df, sales_type):
    """원자료의 내수/수출 구분을 그대로 적용한 제강 G/S 중량 합계."""
    mask = (
        (df["부문"] == "제강")
        & (df["내수/수출"] == sales_type)
        & (df["레벨1명"].isin(STEEL_GS_LEVEL1))
        & (df["레벨2명"] == "GUY STRAND")
    )
    return df.loc[mask, "중량"].sum()
