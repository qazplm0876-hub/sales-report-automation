"""매출실적 보고서와 보조 분석에서 공통으로 사용하는 집계 규칙."""

STEEL_GS_LEVEL1 = ["스틸로프", "스틸선재", "스틸ＳＴ"]


def steel_gs_weight(df, sales_type):
    """원자료의 내수/수출 구분을 그대로 적용한 제강 G/S 중량 합계."""
    mask = (
        (df["부문"] == "제강")
        & (df["내수/수출"] == sales_type)
        & (df["레벨1명"].isin(STEEL_GS_LEVEL1))
        & (df["레벨2명"] == "GUY STRAND")
    )
    return df.loc[mask, "중량"].sum()
