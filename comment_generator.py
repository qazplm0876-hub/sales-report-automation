"""
comment_generator.py
====================
월별 실적 코멘트 자동 생성 모듈
"""

import pandas as pd

from sales_rules import COMMENT_THRESHOLDS, report_product_rules


# 본표의 수출판매 집계와 동일하게 국내 법인의 일반 수출만 포함한다.
# CABLE VINA-수출 등 해외법인 구분은 별도 현지실적이므로 코멘트에서 제외한다.
EXPORT_SALES_TYPES = ['수출']


def _preprocess(df):
    """부문 STS→스텐 변환 및 공통 전처리"""
    df = df.copy()
    df['부문'] = df['부문'].astype(str).str.strip().replace('STS', '스텐')
    for col in ['내수/수출', '담당자명', '담당자(세부)명', '레벨1명', '레벨2명']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    # 월 컬럼 없으면 생성
    if '월' not in df.columns:
        df['월'] = df['요청월'].astype(str).str[-2:] + '월'
    if '연월' not in df.columns and '요청월' in df.columns:
        df['연월'] = (
            df['요청월'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        )
    elif '연월' in df.columns:
        df['연월'] = (
            df['연월'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        )
    if '중량' in df.columns:
        df['중량'] = pd.to_numeric(df['중량'], errors='coerce').fillna(0)
    # 달러금액/원화금액 단위 변환 (이미 변환된 경우 스킵)
    df['달러금액'] = pd.to_numeric(df['달러금액'], errors='coerce').fillna(0)
    df['한국원화금액'] = pd.to_numeric(
        df['한국원화금액'], errors='coerce'
    ).fillna(0)
    if df['달러금액'].max() > 100000:
        df['달러금액'] = pd.to_numeric(df['달러금액'], errors='coerce') / 1000
    if df['한국원화금액'].max() > 100000:
        df['한국원화금액'] = pd.to_numeric(df['한국원화금액'], errors='coerce') / 1_000_000
    return df


def detect_base_effect(df, 부문, 구분_list, rep_col, months,
                        spike_ratio=2.0, drop_ratio=0.5):
    """기저효과 감지: 전전월 대비 전월 2배↑ + 전월 대비 당월 50%↓"""
    if len(months) < 3:
        return []

    prev2_m, prev_m, curr_m = months[-3], months[-2], months[-1]

    sub = df[
        (df['부문'] == 부문) &
        (df['내수/수출'].isin(구분_list))
    ].copy()

    if sub.empty:
        return []

    amt_col = '달러금액' if any('수출' in g for g in 구분_list) else '한국원화금액'
    grp = sub.groupby(['월', rep_col, '레벨2명'])[amt_col].sum().reset_index()
    grp.columns = ['월', rep_col, '레벨2명', '금액']

    results = []
    keys = grp[[rep_col, '레벨2명']].drop_duplicates()
    for _, row in keys.iterrows():
        rep, lv2name = row[rep_col], row['레벨2명']

        def get(m):
            v = grp[(grp['월'] == m) & (grp[rep_col] == rep) & (grp['레벨2명'] == lv2name)]['금액']
            return float(v.sum()) if len(v) else 0.0

        v2, v1, v0 = get(prev2_m), get(prev_m), get(curr_m)

        if v2 > 0 and v1 >= v2 * spike_ratio and v0 <= v1 * (1 - drop_ratio):
            results.append((rep, lv2name, v2, v1, v0))

    return results


def fmt_lv1(name):
    mapping = {
        '합섬방사': '방사', '합섬특수': '특수', '합섬비방사': '비방사',
        '합섬웨빙': '웨빙', '합섬상품': '상품',
        '스텐선재': '선재', '스텐로프': '로프', '스텐상품': '상품',
        '스틸선재': '선재', '스틸로프': '로프', '스틸상품': '상품', '스틸ＳＴ': 'ST선재',
    }
    return mapping.get(name, name)


def _pct_change(prev, curr):
    if prev > 0:
        return (curr - prev) / prev * 100
    return 100.0 if curr > 0 else 0.0


def _get_growth_factors(sub, rep_col, amt_col, prev_m, curr_m, top_n=3):
    """전월 대비 증가액이 큰 담당자/품목 조합을 반환"""
    required = {'월', rep_col, '레벨1명', '레벨2명', amt_col}
    if not required.issubset(set(sub.columns)):
        return []

    grp = (
        sub.groupby(['월', rep_col, '레벨1명', '레벨2명'])[amt_col]
        .sum()
        .unstack('월')
        .fillna(0)
    )
    if grp.empty:
        return []

    positive_rows = []
    for (rep, lv1, lv2), row in grp.iterrows():
        prev = float(row.get(prev_m, 0))
        curr = float(row.get(curr_m, 0))
        delta = curr - prev
        if delta <= 0:
            continue
        positive_rows.append({
            'rep': rep,
            'lv1': lv1,
            'lv2': lv2,
            'prev': prev,
            'curr': curr,
            'delta': delta,
            'pct': _pct_change(prev, curr),
        })

    total_positive_delta = sum(row['delta'] for row in positive_rows)
    for row in positive_rows:
        row['contribution'] = (
            row['delta'] / total_positive_delta * 100 if total_positive_delta else 0
        )

    positive_rows.sort(key=lambda row: row['delta'], reverse=True)
    return positive_rows[:top_n]


def _get_decline_factors(sub, rep_col, amt_col, prev_m, curr_m, top_n=3):
    """전월 대비 감소액이 큰 담당자/품목 조합을 반환"""
    required = {'월', rep_col, '레벨1명', '레벨2명', amt_col}
    if not required.issubset(set(sub.columns)):
        return []

    grp = (
        sub.groupby(['월', rep_col, '레벨1명', '레벨2명'])[amt_col]
        .sum()
        .unstack('월')
        .fillna(0)
    )
    if grp.empty:
        return []

    negative_rows = []
    for (rep, lv1, lv2), row in grp.iterrows():
        prev = float(row.get(prev_m, 0))
        curr = float(row.get(curr_m, 0))
        delta = curr - prev
        if delta >= 0:
            continue
        negative_rows.append({
            'rep': rep,
            'lv1': lv1,
            'lv2': lv2,
            'prev': prev,
            'curr': curr,
            'delta': delta,
            'pct': _pct_change(prev, curr),
        })

    total_decline = sum(abs(row['delta']) for row in negative_rows)
    for row in negative_rows:
        row['contribution'] = (
            abs(row['delta']) / total_decline * 100 if total_decline else 0
        )

    negative_rows.sort(key=lambda row: row['delta'])
    return negative_rows[:top_n]


def _get_lv1_changes(sub, amt_col, prev_m, curr_m):
    """품목군별 전월/당월 실적을 증감액 절댓값 순으로 반환"""
    grp = sub.groupby(['월', '레벨1명'])[amt_col].sum().unstack('월').fillna(0)
    changes = []
    for lv1, row in grp.iterrows():
        prev = float(row.get(prev_m, 0))
        curr = float(row.get(curr_m, 0))
        delta = curr - prev
        if prev == 0 and curr == 0:
            continue
        changes.append({
            'lv1': lv1,
            'prev': prev,
            'curr': curr,
            'delta': delta,
            'pct': _pct_change(prev, curr),
        })
    changes.sort(key=lambda row: abs(row['delta']), reverse=True)
    return changes


def _format_signed(value, unit):
    return f"{value:+,.0f}{unit}"


def _format_percent(value):
    precision = 1 if 0 < abs(value) < 1 else 0
    return f"{value:+.{precision}f}%"


def _format_change(prev, curr, unit):
    delta = curr - prev
    if prev == 0 and curr > 0:
        return f"0 → {curr:,.0f}{unit} ({_format_signed(delta, unit)}, 신규 출고)"
    pct = _pct_change(prev, curr)
    return (
        f"{prev:,.0f} → {curr:,.0f}{unit} "
        f"({_format_signed(delta, unit)}, {_format_percent(pct)})"
    )


def _format_growth_factors(factors, unit):
    if not factors:
        return ""

    parts = []
    for item in factors:
        lv1 = fmt_lv1(item['lv1'])
        parts.append(
            f"{item['rep']}의 {lv1}/{item['lv2']} "
            f"+{item['delta']:,.0f}{unit}({item['pct']:.0f}% 증가, "
            f"증가요인 내 비중 {item['contribution']:.0f}%)"
        )
    return "주요 증가 요인은 " + ", ".join(parts) + "임"


def generate_comment(df, 부문, months):
    """부문별 수출/내수 코멘트 생성"""
    df = _preprocess(df)

    if len(months) < 2:
        return {'수출': '데이터 부족', '내수': '데이터 부족'}

    prev_m, curr_m = months[-2], months[-1]
    result = {}

    for 구분 in ['수출', '내수']:
        if 구분 == '수출':
            구분_list = EXPORT_SALES_TYPES
            amt_col = '달러금액'
            unit = '$K'
            rep_col = '담당자(세부)명'
        else:
            구분_list = ['내수']
            amt_col = '한국원화금액'
            unit = '백만원'
            rep_col = '담당자명'

        sub = df[(df['부문'] == 부문) & (df['내수/수출'].isin(구분_list))].copy()

        if sub.empty:
            result[구분] = "데이터 없음."
            continue

        # 전월/당월 총액
        prev_tot = sub[sub['월'] == prev_m][amt_col].sum()
        curr_tot = sub[sub['월'] == curr_m][amt_col].sum()
        tot_pct = curr_tot / prev_tot * 100 if prev_tot else 0

        # 레벨1별 증감
        lv1_grp = sub.groupby(['월', '레벨1명'])[amt_col].sum().unstack('월').fillna(0)
        lv1_changes = {}
        for lv1 in lv1_grp.index:
            p = float(lv1_grp.loc[lv1].get(prev_m, 0))
            c = float(lv1_grp.loc[lv1].get(curr_m, 0))
            if p > 0:
                lv1_changes[lv1] = (c - p) / p * 100

        increases = sorted([(k, v) for k, v in lv1_changes.items() if v > 5], key=lambda x: -x[1])
        decreases = sorted([(k, v) for k, v in lv1_changes.items() if v < -5], key=lambda x: x[1])

        inc_str = ' / '.join([f"{fmt_lv1(k)} {abs(v):.0f}% 증가" for k, v in increases])
        dec_str = ' / '.join([f"{fmt_lv1(k)} {abs(v):.0f}% 감소" for k, v in decreases])

        if inc_str and dec_str:
            change_str = f"{inc_str}하며 {dec_str}하였음"
        elif inc_str:
            change_str = f"{inc_str}하였음"
        elif dec_str:
            change_str = f"{dec_str}하였음"
        else:
            change_str = ""

        # 기저효과 감지
        base_effects = detect_base_effect(df, 부문, 구분_list, rep_col, months)
        base_str = ""
        if base_effects:
            be_parts = [f"{rep}의 {lv2name} 전월 출고({v1:,.0f}{unit})에 따른 기저효과"
                        for rep, lv2name, v2, v1, v0 in base_effects]
            base_str = ". ".join(be_parts) + "가 작용하였음"

        # 주요 증가 요인
        growth_str = _format_growth_factors(
            _get_growth_factors(sub, rep_col, amt_col, prev_m, curr_m),
            unit,
        )

        # 담당자별 주요 증감 (수출)
        rep_str = ""
        if 구분 == '수출':
            rep_grp = sub.groupby(['월', rep_col])[amt_col].sum().unstack('월').fillna(0)
            rep_changes = []
            for rep in rep_grp.index:
                p = float(rep_grp.loc[rep].get(prev_m, 0))
                c = float(rep_grp.loc[rep].get(curr_m, 0))
                if p > 0 and abs((c - p) / p) > 0.3 and c > 50:
                    rep_changes.append((rep, p, c, (c - p) / p * 100))
            rep_changes.sort(key=lambda x: -abs(x[3]))
            if rep_changes:
                rep_parts = [f"{rep} {abs(pct):.0f}% {'증가' if pct > 0 else '감소'}"
                             for rep, p, c, pct in rep_changes[:3]]
                rep_str = ", ".join(rep_parts) + "함"

        # 코멘트 조합
        parts = [f"전체실적 전월대비 {tot_pct:.0f}% 수준으로"]
        if change_str:
            parts.append(change_str)
        if growth_str:
            parts.append(growth_str)
        if base_str:
            parts.append(base_str)
        if rep_str:
            parts.append(rep_str)

        result[구분] = ". ".join(parts) + "."

    return result


def generate_full_report(df, months):
    """합섬/스텐/제강 수출/내수 전체 코멘트 생성 (마크다운)"""
    df = _preprocess(df)
    curr_m = months[-1]

    lines = [
        f"# {curr_m} 매출실적 분석 코멘트 (자동 생성)\n",
        f"> 전월: {months[-2]} | 당월: {curr_m}\n",
        "---\n",
        "## 수출\n",
    ]
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment(df, 부문, months)
        lines.append(f"- **{부문}** : {c['수출']}")

    lines.append("\n## 내수\n")
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment(df, 부문, months)
        lines.append(f"- **{부문}** : {c['내수']}")

    lines += ["\n---", "> ⚠️ 자동 생성된 초안입니다. END USER·기저효과 맥락을 추가해 주세요."]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python comment_generator.py [raw파일경로.xlsx]")
        sys.exit(1)

    df = pd.read_excel(sys.argv[1], sheet_name=0)
    df = _preprocess(df)
    df = df[df['부문'].notna() & (df['부문'] != 'nan')]
    df = df[(df['회사'].astype(str).str.strip() != '6') & (df['계정'].astype(str).str.strip() != '6')]
    if '원화금액' in df.columns:
        df = df.drop(columns=['원화금액'])

    months = sorted(df['월'].unique())
    report = generate_full_report(df, months)
    print(report)

    out = f"코멘트_{months[-1]}.md"
    with open(out, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n저장 완료: {out}")


# ── 거래처 분석 (출고 상세 데이터용) ─────────────────────────────
def _read_customer_sheet(path):
    """여러 시트 중 출고 상세 원본 열이 있는 시트를 자동으로 선택한다."""
    with pd.ExcelFile(path) as workbook:
        sheet_names = list(workbook.sheet_names)
    required_common = {'출고요청년월'}
    amount_candidates = {'달러금액', '원화금액'}
    customer_candidates = {'인수처명', '거래처'}

    for sheet_name in sheet_names:
        columns = set(pd.read_excel(
            path, sheet_name=sheet_name, nrows=0
        ).columns)
        if (
            required_common.issubset(columns)
            and columns.intersection(amount_candidates)
            and columns.intersection(customer_candidates)
        ):
            return pd.read_excel(path, sheet_name=sheet_name)

    raise ValueError(
        f"{path}에서 출고요청년월·금액·인수처 열이 있는 상세 시트를 찾지 못했습니다."
    )


def load_customer_data(filepaths):
    """
    출고 상세 데이터 로드 및 전처리.
    기본 파일명:
      - 수출: 1.xlsx(합섬), 2.xlsx(스텐), 3.xlsx(제강)
      - 내수: 1_내수.xlsx, 2_내수.xlsx, 3_내수.xlsx 또는 부문명_내수.xlsx
    END USER는 AB열의 '인수처명'을 기준으로 한다.
    """
    if isinstance(filepaths, list):
        keys = ['합섬', '스텐', '제강']
        filepaths = dict(zip(keys, filepaths))

    frames = []
    for 부문, spec in filepaths.items():
        if isinstance(spec, dict):
            items = spec.items()
        else:
            items = [('수출', spec)]

        for 구분, path in items:
            if not path:
                continue
            df = _read_customer_sheet(path)
            if '달러금액' in df.columns:
                df['달러금액'] = pd.to_numeric(
                    df['달러금액'], errors='coerce'
                ).fillna(0)
                if df['달러금액'].abs().max() > 100000:
                    df['달러금액'] = df['달러금액'] / 1000
            if '원화금액' in df.columns:
                df['원화금액'] = pd.to_numeric(
                    df['원화금액'], errors='coerce'
                ).fillna(0)
                if df['원화금액'].abs().max() > 100000:
                    df['원화금액'] = df['원화금액'] / 1_000_000
            df['부문'] = 부문
            df['내수/수출'] = 구분
            frames.append(df)

    if not frames:
        raise FileNotFoundError("거래처/END USER 상세 파일을 찾을 수 없습니다.")

    df = pd.concat(frames, ignore_index=True)

    if '인수처명' in df.columns:
        df['END_USER'] = df['인수처명']
    elif '거래처' in df.columns:
        df['END_USER'] = df['거래처']
    else:
        df['END_USER'] = ''

    for col in ['담당자 세부', '담당자명', 'LVL2NM', 'LVL1NM', '거래처', '인수처명', 'END_USER', '내수/수출']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    df['연월'] = (
        df['출고요청년월'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    )
    df['월'] = df['연월'].str[-2:] + '월'
    df['달러금액'] = pd.to_numeric(df['달러금액'], errors='coerce').fillna(0)
    if '원화금액' in df.columns:
        df['원화금액'] = pd.to_numeric(df['원화금액'], errors='coerce').fillna(0)

    return df


def get_top_customers(cdf, 부문, rep, lv2, month, 구분='수출', n=3):
    """특정 담당자×품목×월의 상위 END USER(인수처명) 반환"""
    rep_col = '담당자 세부' if 구분 == '수출' else '담당자명'
    amt_col = '달러금액' if 구분 == '수출' else '원화금액'
    user_col = 'END_USER' if 'END_USER' in cdf.columns else '인수처명'
    if rep_col not in cdf.columns or amt_col not in cdf.columns or user_col not in cdf.columns:
        return []

    sub = cdf[
        (cdf['부문'] == 부문) &
        (cdf[rep_col] == rep) &
        (cdf['LVL2NM'] == lv2) &
        (cdf['월'] == month)
    ]
    if '내수/수출' in sub.columns:
        sub = sub[sub['내수/수출'] == 구분]
    if sub.empty:
        return []
    top = sub.groupby(user_col)[amt_col].sum().sort_values(ascending=False).head(n)
    return [(name, amt) for name, amt in top.items()]


def _format_customers(customers, unit):
    if not customers:
        return ""
    return ", ".join([f"{name}({amt:,.0f}{unit})" for name, amt in customers])


def _join_korean(items):
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " 및 " + items[-1]


def _get_rep_product_changes(
    sub, rep_col, rep, amt_col, prev_m, curr_m, max_lv1=4, max_lv2=3
):
    """지역/담당자 전체 변화를 품목군과 세부 품목 단위로 반환"""
    rep_sub = sub[sub[rep_col] == rep]
    if rep_sub.empty:
        return []

    changes = []
    for lv1, lv1_sub in rep_sub.groupby('레벨1명'):
        month_totals = lv1_sub.groupby('월')[amt_col].sum()
        prev = float(month_totals.get(prev_m, 0))
        curr = float(month_totals.get(curr_m, 0))
        delta = curr - prev
        if abs(delta) < 1e-9:
            continue

        lv2_grp = (
            lv1_sub.groupby(['월', '레벨2명'])[amt_col]
            .sum()
            .unstack('월')
            .fillna(0)
        )
        details = []
        for lv2, row in lv2_grp.iterrows():
            lv2_prev = float(row.get(prev_m, 0))
            lv2_curr = float(row.get(curr_m, 0))
            lv2_delta = lv2_curr - lv2_prev
            if abs(lv2_delta) < 1e-9:
                continue
            details.append({
                'lv2': lv2,
                'prev': lv2_prev,
                'curr': lv2_curr,
                'delta': lv2_delta,
                'pct': _pct_change(lv2_prev, lv2_curr),
            })

        details.sort(key=lambda item: abs(item['delta']), reverse=True)
        gross_change = sum(abs(item['delta']) for item in details)
        detail_threshold = max(gross_change * 0.1, 1)
        material_details = [
            item for item in details if abs(item['delta']) >= detail_threshold
        ][:max_lv2]
        if not material_details and details:
            material_details = details[:1]

        changes.append({
            'lv1': lv1,
            'prev': prev,
            'curr': curr,
            'delta': delta,
            'pct': _pct_change(prev, curr),
            'details': material_details,
        })

    changes.sort(key=lambda item: abs(item['delta']), reverse=True)
    return changes[:max_lv1]


def generate_comment_with_customers(df, cdf, 부문, months, top_n=2):
    """
    거래처 정보 포함 코멘트 생성
    df: raw 실적 데이터 (전처리 완료)
    cdf: 출고 상세 데이터 (load_customer_data 결과)
    """
    df = _preprocess(df)
    if len(months) < 2:
        return {'수출': '데이터 부족', '내수': '데이터 부족'}

    prev_m, curr_m = months[-2], months[-1]
    result = {}

    for 구분 in ['수출', '내수']:
        if 구분 == '수출':
            구분_list = EXPORT_SALES_TYPES
            amt_col = '달러금액'
            unit = 'K'
            rep_col = '담당자(세부)명'
        else:
            구분_list = ['내수']
            amt_col = '한국원화금액'
            unit = '백만원'
            rep_col = '담당자명'

        sub = df[(df['부문'] == 부문) & (df['내수/수출'].isin(구분_list))].copy()
        if sub.empty:
            result[구분] = '데이터 없음.'
            continue

        # 전월/당월 총액
        prev_tot = sub[sub['월'] == prev_m][amt_col].sum()
        curr_tot = sub[sub['월'] == curr_m][amt_col].sum()
        total_delta = curr_tot - prev_tot
        total_pct = _pct_change(prev_tot, curr_tot)
        lv1_changes = _get_lv1_changes(sub, amt_col, prev_m, curr_m)
        growth_factors = _get_growth_factors(sub, rep_col, amt_col, prev_m, curr_m)
        decline_factors = _get_decline_factors(sub, rep_col, amt_col, prev_m, curr_m)
        base_effects = detect_base_effect(df, 부문, 구분_list, rep_col, months)

        # 담당자/지역별 주요 증감
        rep_grp = sub.groupby(['월', rep_col])[amt_col].sum().unstack('월').fillna(0)
        rep_changes = []
        region_delta_threshold = max(abs(total_delta) * 0.1, 50)
        for rep in rep_grp.index:
            p = float(rep_grp.loc[rep].get(prev_m, 0))
            c = float(rep_grp.loc[rep].get(curr_m, 0))
            pct = _pct_change(p, c)
            large_rate_change = p > 0 and abs(pct) > 30
            large_amount_change = abs(c - p) >= region_delta_threshold
            if max(p, c) > 50 and (large_rate_change or large_amount_change):
                rep_changes.append((rep, p, c, pct))
        rep_changes.sort(key=lambda row: abs(row[2] - row[1]), reverse=True)

        def factor_clause(item, direction, customer_month):
            customers = get_top_customers(
                cdf, 부문, item['rep'], item['lv2'], customer_month,
                구분=구분, n=top_n,
            )
            destination = _format_customers(customers, unit)
            rep_text = f"{item['rep']} 지역" if 구분 == '수출' else item['rep']
            if destination:
                cause = f"{rep_text}의 {destination} 향 실적 {direction}"
            else:
                cause = f"{rep_text}의 실적 {direction}"
            return f"{item['lv2']} {direction}는 {cause}"

        total_direction = "증가" if total_delta >= 0 else "감소"
        narrative = (
            f"전체 실적은 {_format_change(prev_tot, curr_tot, unit)}로 "
            f"전월 대비 {total_direction}하였음."
        )
        if total_delta >= 0:
            main_factors = [
                factor_clause(item, "증가", curr_m)
                for item in growth_factors[:2]
            ]
            offset_factors = [
                factor_clause(item, "감소", prev_m)
                for item in decline_factors[:2]
            ]
        else:
            main_factors = [
                factor_clause(item, "감소", prev_m)
                for item in decline_factors[:2]
            ]
            offset_factors = [
                factor_clause(item, "증가", curr_m)
                for item in growth_factors[:2]
            ]

        if main_factors:
            narrative += f" {_join_korean(main_factors)}가 주요하게 작용하였음."
        if offset_factors:
            narrative += f" 반면 {_join_korean(offset_factors)}가 일부 상쇄하였음."

        lines = [
            "**한눈에 보기**",
            narrative,
        ]

        if lv1_changes:
            lines.extend(["", "**품목별 변화**"])
            for item in lv1_changes:
                if abs(item['pct']) < 5 and abs(item['delta']) < max(abs(total_delta) * 0.05, 1):
                    continue
                lines.append(
                    f"- {fmt_lv1(item['lv1'])}: "
                    f"{_format_change(item['prev'], item['curr'], unit)}"
                )

        def append_factor_section(title, factors, customer_month):
            if not factors:
                return
            lines.extend(["", f"**{title}**"])
            for index, item in enumerate(factors, 1):
                lines.append(
                    f"{index}. {item['rep']} · {fmt_lv1(item['lv1'])}/{item['lv2']}: "
                    f"{_format_change(item['prev'], item['curr'], unit)}, "
                    f"{title.replace('주요 ', '')} 내 비중 {item['contribution']:.0f}%"
                )
                customers = get_top_customers(
                    cdf, 부문, item['rep'], item['lv2'], customer_month,
                    구분=구분, n=top_n,
                )
                cust_str = _format_customers(customers, unit)
                if cust_str:
                    lines.append(f"   - {cust_str} 향 실적")

        append_factor_section("주요 증가 요인", growth_factors, curr_m)
        append_factor_section("주요 감소 요인", decline_factors, prev_m)

        if rep_changes:
            lines.extend(["", f"**주요 {'지역' if 구분 == '수출' else '담당자'} 변화**"])
            for rep, prev, curr, pct in rep_changes[:3]:
                lines.append(
                    f"- {rep}: {_format_change(prev, curr, unit)}"
                )
                product_changes = _get_rep_product_changes(
                    sub, rep_col, rep, amt_col, prev_m, curr_m
                )
                for product in product_changes:
                    lines.append(
                        f"  - {fmt_lv1(product['lv1'])}: "
                        f"{_format_change(product['prev'], product['curr'], unit)}"
                    )
                    if product['details']:
                        detail_text = "; ".join(
                            f"{item['lv2']} "
                            f"{_format_change(item['prev'], item['curr'], unit)}"
                            for item in product['details']
                        )
                        lines.append(f"    - 세부 품목: {detail_text}")

        if base_effects:
            lines.extend(["", "**기저효과 확인**"])
            for rep, lv2name, prev2, prev, curr in sorted(
                base_effects, key=lambda row: row[3] - row[4], reverse=True
            )[:3]:
                line = (
                    f"- {rep} · {lv2name}: {months[-3]} {prev2:,.0f} → "
                    f"{prev_m} {prev:,.0f} → {curr_m} {curr:,.0f}{unit}. "
                    f"전월 일시 출고 후 감소"
                )
                customers = get_top_customers(
                    cdf, 부문, rep, lv2name, prev_m, 구분=구분, n=top_n
                )
                cust_str = _format_customers(customers, unit)
                if cust_str:
                    line += f" ({cust_str} 향 전월 실적)"
                lines.append(line)

        driver = growth_factors[0] if total_delta >= 0 and growth_factors else (
            decline_factors[0] if decline_factors else None
        )
        if driver:
            direction = "증가" if total_delta >= 0 else "감소"
            offset = decline_factors[0] if total_delta >= 0 and decline_factors else None
            insight = (
                f"전체 실적은 전월보다 {_format_signed(total_delta, unit)}({_format_percent(total_pct)}) {direction}. "
                f"{driver['rep']}의 {fmt_lv1(driver['lv1'])}/{driver['lv2']} 변화가 가장 큰 요인"
            )
            if offset:
                insight += (
                    f"이며, {offset['rep']}의 {fmt_lv1(offset['lv1'])}/{offset['lv2']} "
                    f"감소가 일부 상쇄"
                )
            lines.extend(["", "**종합 해석**", f"- {insight}."])

        result[구분] = "\n".join(lines)

    return result


def generate_full_report_with_customers(df, cdf, months):
    """END USER 포함 전체 코멘트 생성"""
    df = _preprocess(df)
    curr_m = months[-1]

    lines = [
        f"# {curr_m} 매출실적 상세 분석\n",
        f"> 전월: {months[-2]} | 당월: {curr_m}\n",
        "---\n",
        "## 수출\n",
    ]
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment_with_customers(df, cdf, 부문, months)
        lines.append(f"### {부문}\n{c['수출']}\n")

    lines.append("\n## 내수\n")
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment_with_customers(df, cdf, 부문, months)
        lines.append(f"### {부문}\n{c['내수']}\n")

    lines += ["\n---", "> 자동 생성 초안입니다. 특이 출고와 일회성 요인은 최종 보고 전에 확인해 주세요."]
    return "\n".join(lines)


# ── 브리핑형 코멘트 및 가격·믹스 원인탐색 ──────────────────────
def _year_month(year, month):
    return f"{int(year):04d}{int(month):02d}"


def _previous_year_month(year, month):
    if month > 1:
        return year, month - 1
    return year - 1, 12


def _period_rows(df, year, month, ytd=False):
    """연월 기준 당월 또는 1월~당월 데이터를 반환한다."""
    if df.empty or '연월' not in df.columns:
        return df.iloc[0:0].copy()
    period = df['연월'].astype(str).str.replace(r'\.0$', '', regex=True)
    target = _year_month(year, month)
    if ytd:
        start = _year_month(year, 1)
        return df[(period >= start) & (period <= target)].copy()
    return df[period == target].copy()


def _division_rows(df, division, sales_type):
    sales_values = EXPORT_SALES_TYPES if sales_type == '수출' else ['내수']
    return df[
        (df['부문'] == division) &
        (df['내수/수출'].isin(sales_values))
    ].copy()


def _rule_rows(df, rule):
    sub = _division_rows(df, rule['division'], rule['sales_type'])
    sub = sub[sub['레벨1명'].isin(rule['level1'])]
    if rule['level2']:
        sub = sub[sub['레벨2명'].isin(rule['level2'])]
    return sub.copy()


def _metric_values(df, amount_col):
    sales = float(df[amount_col].sum()) if amount_col in df.columns else 0.0
    volume = float(df['중량'].sum()) if '중량' in df.columns else 0.0
    unit_price = sales / volume if volume else 0.0
    return {
        'sales': sales,
        'volume': volume,
        'unit_price': unit_price,
    }


def _metric_change(previous, current):
    return {
        'sales_pct': _pct_change(previous['sales'], current['sales']),
        'volume_pct': _pct_change(previous['volume'], current['volume']),
        'unit_price_pct': _pct_change(
            previous['unit_price'], current['unit_price']
        ),
        'sales_delta': current['sales'] - previous['sales'],
        'volume_delta': current['volume'] - previous['volume'],
        'unit_price_delta': current['unit_price'] - previous['unit_price'],
    }


def calculate_product_driver(df, rule, previous_period, current_period):
    """보고서 품목의 전월 대비 매출·물량·평균단가 변화를 계산한다."""
    df = _preprocess(df)
    sub = _rule_rows(df, rule)
    previous = _metric_values(
        sub[sub['연월'] == previous_period], rule['amount_col']
    )
    current = _metric_values(
        sub[sub['연월'] == current_period], rule['amount_col']
    )
    return {
        'rule': rule,
        'previous': previous,
        'current': current,
        **_metric_change(previous, current),
    }


def calculate_ytd_driver(
    current_df, prior_df, division, sales_type, current_year, through_month
):
    """전년 1~N월과 당년 1~N월 누계 매출·물량·평균단가를 비교한다."""
    amount_col = '달러금액' if sales_type == '수출' else '한국원화금액'
    current_df = _preprocess(current_df)
    prior_df = _preprocess(prior_df)
    current_sub = _division_rows(
        _period_rows(current_df, current_year, through_month, ytd=True),
        division,
        sales_type,
    )
    prior_sub = _division_rows(
        _period_rows(prior_df, current_year - 1, through_month, ytd=True),
        division,
        sales_type,
    )
    previous = _metric_values(prior_sub, amount_col)
    current = _metric_values(current_sub, amount_col)
    return {
        'previous': previous,
        'current': current,
        **_metric_change(previous, current),
    }


def _cause_type(status, mix_effect, price_effect, share_change, previous_price,
                current_price, previous_total_price):
    if status == '신규':
        return '고단가 신규' if current_price >= previous_total_price else '저단가 신규'
    if status == '중단':
        return '고단가 중단' if previous_price >= previous_total_price else '저단가 중단'
    if abs(price_effect) >= abs(mix_effect):
        return '제품단가 상승' if price_effect >= 0 else '제품단가 하락'
    if mix_effect >= 0:
        return '고단가 비중↑' if share_change >= 0 else '저단가 비중↓'
    return '저단가 비중↑' if share_change >= 0 else '고단가 비중↓'


def decompose_unit_price(df, rule, previous_period, current_period):
    """
    평균단가 변화를 제품가격 효과와 판매믹스 효과로 분해한다.

    계속 품목:
      믹스효과 = (당월비중-전월비중) × (전월제품단가-전월전체단가)
      가격효과 = 당월비중 × (당월제품단가-전월제품단가)
    신규·중단 품목은 전월 전체단가 대비 고·저단가 출고 효과로 처리한다.
    """
    df = _preprocess(df)
    sub = _rule_rows(df, rule)
    sub = sub[sub['연월'].isin([previous_period, current_period])].copy()
    if sub.empty or '중량' not in sub.columns:
        return {
            'previous_unit_price': 0.0,
            'current_unit_price': 0.0,
            'unit_price_delta': 0.0,
            'causes': [],
            'reconciliation_delta': 0.0,
        }

    product_col = '약어명' if '약어명' in sub.columns else '레벨2명'
    if rule['sales_type'] == '수출':
        rep_col = (
            '담당자(세부)명'
            if '담당자(세부)명' in sub.columns
            else '담당자명'
        )
    else:
        rep_col = '담당자명'

    sub['_분석품목'] = sub[product_col].fillna('미분류').astype(str).str.strip()
    if rep_col in sub.columns:
        sub['_분석담당자'] = (
            sub[rep_col].fillna('미분류').astype(str).str.strip()
        )
    else:
        sub['_분석담당자'] = '미분류'

    grouped = (
        sub.groupby(['연월', '_분석품목', '_분석담당자'], dropna=False)[
            [rule['amount_col'], '중량']
        ]
        .sum()
    )
    previous_total = _metric_values(
        sub[sub['연월'] == previous_period], rule['amount_col']
    )
    current_total = _metric_values(
        sub[sub['연월'] == current_period], rule['amount_col']
    )
    p0 = previous_total['unit_price']
    p1 = current_total['unit_price']
    q0_total = previous_total['volume']
    q1_total = current_total['volume']
    if not q0_total or not q1_total:
        return {
            'previous_unit_price': p0,
            'current_unit_price': p1,
            'unit_price_delta': p1 - p0,
            'causes': [],
            'reconciliation_delta': 0.0,
        }

    combinations = {
        (product, rep)
        for _, product, rep in grouped.index
    }
    causes = []
    for product, rep in combinations:
        def get(period):
            key = (period, product, rep)
            if key not in grouped.index:
                return 0.0, 0.0
            row = grouped.loc[key]
            return float(row[rule['amount_col']]), float(row['중량'])

        amount0, quantity0 = get(previous_period)
        amount1, quantity1 = get(current_period)
        price0 = amount0 / quantity0 if quantity0 else 0.0
        price1 = amount1 / quantity1 if quantity1 else 0.0
        share0 = quantity0 / q0_total if q0_total else 0.0
        share1 = quantity1 / q1_total if q1_total else 0.0
        share_change = share1 - share0

        if quantity0 and quantity1:
            status = '계속'
            mix_effect = share_change * (price0 - p0)
            price_effect = share1 * (price1 - price0)
        elif quantity1:
            status = '신규'
            mix_effect = share1 * (price1 - p0)
            price_effect = 0.0
        elif quantity0:
            status = '중단'
            mix_effect = -share0 * (price0 - p0)
            price_effect = 0.0
        else:
            continue

        total_effect = mix_effect + price_effect
        if abs(total_effect) < 1e-12:
            continue
        causes.append({
            'product': product,
            'rep': rep,
            'status': status,
            'previous_volume': quantity0,
            'current_volume': quantity1,
            'previous_share': share0,
            'current_share': share1,
            'share_change': share_change,
            'previous_product_price': price0,
            'current_product_price': price1,
            'mix_effect': mix_effect,
            'price_effect': price_effect,
            'total_effect': total_effect,
            'cause_type': _cause_type(
                status,
                mix_effect,
                price_effect,
                share_change,
                price0,
                price1,
                p0,
            ),
        })

    causes.sort(key=lambda row: abs(row['total_effect']), reverse=True)
    reconciled = sum(row['total_effect'] for row in causes)
    return {
        'previous_unit_price': p0,
        'current_unit_price': p1,
        'unit_price_delta': p1 - p0,
        'causes': causes,
        'reconciliation_delta': reconciled - (p1 - p0),
    }


def _customer_history(cdf, division, sales_type, customer, current_period,
                      previous_period, current_year):
    sub = cdf[
        (cdf['부문'] == division) &
        (cdf['내수/수출'] == sales_type) &
        (cdf['END_USER'] == customer)
    ].copy()
    periods = set(sub['연월'].astype(str)) if '연월' in sub.columns else set()
    previous_exists = previous_period in periods
    prior_year_exists = any(
        period.startswith(str(current_year - 1)) for period in periods
    )
    any_history = any(period < current_period for period in periods)
    return {
        'previous_exists': previous_exists,
        'prior_year_exists': prior_year_exists,
        'any_history': any_history,
    }


def get_customer_changes(
    cdf, division, sales_type, previous_period, current_period,
    current_year, direction='increase', top_n=4, factors=None
):
    """
    END USER별 전월 대비 증감액과 전월·전년 거래 이력을 반환한다.

    factors가 있으면 공식 원자료에서 선정한 담당지역×레벨2 주요 요인 안에서
    고객 증감액을 찾는다. 거래처 상세파일 자체로 전체 매출 원인을 선정하지 않는다.
    """
    if cdf is None or cdf.empty:
        return []

    cdf = cdf.copy()
    required = {'부문', '내수/수출', 'END_USER'}
    if not required.issubset(cdf.columns):
        return []
    if '연월' not in cdf.columns:
        if '출고요청년월' not in cdf.columns:
            return []
        cdf['연월'] = (
            cdf['출고요청년월']
            .astype(str)
            .str.replace(r'\.0$', '', regex=True)
            .str.strip()
        )

    rep_col = '담당자 세부' if sales_type == '수출' else '담당자명'
    amount_col = '달러금액' if sales_type == '수출' else '원화금액'
    if rep_col not in cdf.columns or amount_col not in cdf.columns:
        return []

    cdf['연월'] = cdf['연월'].astype(str)
    cdf[amount_col] = pd.to_numeric(cdf[amount_col], errors='coerce').fillna(0)
    period_sub = cdf[
        (cdf['부문'] == division) &
        (cdf['내수/수출'] == sales_type) &
        (cdf['연월'].isin([previous_period, current_period]))
    ].copy()
    if period_sub.empty:
        return []

    def collect(source, limit):
        grouped = (
            source.groupby(['연월', rep_col, 'END_USER'])[amount_col]
            .sum()
            .unstack('연월')
            .fillna(0)
        )
        rows = []
        for (rep, customer), row in grouped.iterrows():
            previous = float(row.get(previous_period, 0))
            current = float(row.get(current_period, 0))
            delta = current - previous
            if direction == 'increase' and delta <= 0:
                continue
            if direction == 'decrease' and delta >= 0:
                continue
            history = _customer_history(
                cdf,
                division,
                sales_type,
                customer,
                current_period,
                previous_period,
                current_year,
            )
            rows.append({
                'rep': rep,
                'customer': customer,
                'previous': previous,
                'current': current,
                'delta': delta,
                **history,
            })
        rows.sort(key=lambda row: abs(row['delta']), reverse=True)
        return rows[:limit]

    changes = []
    usable_factors = [
        factor for factor in (factors or [])
        if 'LVL2NM' in period_sub.columns
    ]
    if usable_factors:
        per_factor = max(1, top_n // len(usable_factors))
        for factor in usable_factors:
            factor_sub = period_sub[
                (period_sub[rep_col] == factor['rep']) &
                (period_sub['LVL2NM'] == factor['lv2'])
            ]
            changes.extend(collect(factor_sub, per_factor))
    else:
        changes = collect(period_sub, top_n)

    deduplicated = {}
    for row in changes:
        key = (row['rep'], row['customer'])
        if key not in deduplicated or abs(row['delta']) > abs(
            deduplicated[key]['delta']
        ):
            deduplicated[key] = row
    changes = list(deduplicated.values())
    changes.sort(key=lambda row: abs(row['delta']), reverse=True)
    return changes[:top_n]


def _format_abs_percent(value):
    return f"{abs(value):.1f}%"


def _format_direction_change(value, positive='증가', negative='감소'):
    if abs(value) < 0.05:
        return "전년과 유사"
    direction = positive if value > 0 else negative
    return f"{_format_abs_percent(value)} {direction}"


def _subject_particle(word):
    """한글로 끝나는 명사에 맞는 주제 조사(은/는)를 반환한다."""
    if not word:
        return "는"
    last = word[-1]
    if '가' <= last <= '힣':
        return "은" if (ord(last) - ord('가')) % 28 else "는"
    return "는"


def _format_unit_price_cause(cause):
    prefix = f"{cause['rep']} {cause['product']}"
    cause_type = cause['cause_type']
    mapping = {
        '제품단가 상승': f"{prefix}의 제품단가 상승",
        '제품단가 하락': f"{prefix}의 제품단가 하락",
        '고단가 비중↑': f"고단가 {prefix} 판매 비중 확대",
        '고단가 비중↓': f"고단가 {prefix} 판매 비중 축소",
        '저단가 비중↑': f"저단가 {prefix} 판매 비중 확대",
        '저단가 비중↓': f"저단가 {prefix} 판매 비중 축소",
        '고단가 신규': f"고단가 {prefix} 신규 출고",
        '저단가 신규': f"저단가 {prefix} 신규 출고",
        '고단가 중단': f"고단가 {prefix} 출고 중단",
        '저단가 중단': f"저단가 {prefix} 출고 중단",
    }
    return mapping.get(cause_type, f"{prefix} 변화")


def _product_driver_sentence(driver):
    label = driver['rule']['label']
    topic = f"{label}{_subject_particle(label)}"
    sales_pct = driver['sales_pct']
    volume_pct = driver['volume_pct']
    price_pct = driver['unit_price_pct']
    previous = driver['previous']
    current = driver['current']

    if previous['sales'] == 0 and current['sales'] > 0:
        return f"{topic} 당월 신규 출고로 {current['sales']:,.0f} 실적이 발생하였음."
    if previous['sales'] > 0 and current['sales'] == 0:
        return f"{topic} 당월 매출 실적이 없어 매출이 100.0% 감소하였음."
    if abs(sales_pct) < 0.05:
        return (
            f"{label} 매출은 전월과 유사한 수준이며, 판매량은 "
            f"{_format_percent(volume_pct)}, 평균단가는 {_format_percent(price_pct)} 변동하였음."
        )

    sales_direction = '증가' if sales_pct > 0 else '감소'
    if sales_pct > 0 and volume_pct < 0 < price_pct:
        return (
            f"{topic} 판매량이 {_format_abs_percent(volume_pct)} 감소했으나 "
            f"평균단가가 {_format_abs_percent(price_pct)} 상승하면서 매출이 "
            f"{_format_abs_percent(sales_pct)} 증가하였음."
        )
    if sales_pct > 0 and price_pct < 0 < volume_pct:
        return (
            f"{topic} 평균단가가 {_format_abs_percent(price_pct)} 하락했으나 "
            f"판매량이 {_format_abs_percent(volume_pct)} 증가하면서 매출이 "
            f"{_format_abs_percent(sales_pct)} 증가하였음."
        )
    if sales_pct < 0 and volume_pct < 0 < price_pct:
        return (
            f"{topic} 평균단가가 {_format_abs_percent(price_pct)} 상승했으나 "
            f"판매량이 {_format_abs_percent(volume_pct)} 감소하면서 매출이 "
            f"{_format_abs_percent(sales_pct)} 감소하였음."
        )
    if sales_pct < 0 and price_pct < 0 < volume_pct:
        return (
            f"{topic} 판매량이 {_format_abs_percent(volume_pct)} 증가했으나 "
            f"평균단가가 {_format_abs_percent(price_pct)} 하락하면서 매출이 "
            f"{_format_abs_percent(sales_pct)} 감소하였음."
        )
    return (
        f"{topic} 판매량 {_format_percent(volume_pct)}, 평균단가 "
        f"{_format_percent(price_pct)}의 영향으로 매출이 "
        f"{_format_abs_percent(sales_pct)} {sales_direction}하였음."
    )


def _price_cause_sentence(
    driver, decomposition, max_causes, minimum_price_pct=None
):
    price_pct = driver['unit_price_pct']
    minimum_price_pct = (
        COMMENT_THRESHOLDS['unit_price_pct']
        if minimum_price_pct is None
        else minimum_price_pct
    )
    if abs(price_pct) < minimum_price_pct:
        return ""

    causes = decomposition['causes']
    if not causes:
        return ""
    main_sign = 1 if price_pct > 0 else -1
    main = [
        cause for cause in causes
        if cause['total_effect'] * main_sign > 0
    ][:max_causes]
    offsets = [
        cause for cause in causes
        if cause['total_effect'] * main_sign < 0
    ][:1]
    if not main:
        return ""

    direction = '상승' if price_pct > 0 else '하락'
    sentence = (
        f"{driver['rule']['label']} 평균단가 {_format_abs_percent(price_pct)} "
        f"{direction}은 {_join_korean([_format_unit_price_cause(c) for c in main])} "
        "등을 주요 원인으로 판단함."
    )
    if offsets:
        offset_text = _format_unit_price_cause(offsets[0])
        sentence += (
            f" 반면 {offset_text}{_subject_particle(offset_text)} "
            "일부 상쇄 요인으로 작용하였음."
        )
    return sentence


def _customer_change_sentence(changes, unit, direction):
    if not changes:
        return ""
    direction_word = '증가' if direction == 'increase' else '감소'
    parts = [
        f"{row['rep']} {row['customer']} {row['delta']:+,.0f}{unit}"
        for row in changes
    ]
    sentence = (
        f"거래처별 주요 {direction_word} 요인은 {_join_korean(parts)}임."
    )

    if all(row['previous_exists'] and row['prior_year_exists'] for row in changes):
        return (
            sentence +
            " 해당 거래처는 모두 전월 및 전년 거래 이력이 있는 기존 거래처로 확인됨."
        )

    new_customers = [row['customer'] for row in changes if not row['any_history']]
    existing_customers = [row['customer'] for row in changes if row['any_history']]
    if new_customers:
        sentence += f" 신규 거래처는 {_join_korean(new_customers)}임."
    if existing_customers:
        sentence += (
            f" 과거 거래 이력이 있는 기존 거래처는 "
            f"{_join_korean(existing_customers)}임."
        )
    return sentence


def _select_product_drivers(drivers, total_pct, thresholds):
    available = [
        driver for driver in drivers
        if driver['previous']['sales'] or driver['current']['sales']
    ]
    if not available:
        return []
    ranked = sorted(
        available, key=lambda row: abs(row['sales_delta']), reverse=True
    )
    selected = []
    if abs(total_pct) >= thresholds['division_sales_pct']:
        selected.extend(ranked[:2])

    for driver in ranked:
        material = (
            abs(driver['sales_pct']) >= thresholds['product_sales_pct']
            or abs(driver['volume_pct']) >= thresholds['volume_pct']
            or abs(driver['unit_price_pct']) >= thresholds['unit_price_pct']
        )
        if (
            material
            and driver not in selected
            and len(selected) < thresholds['max_products']
        ):
            selected.append(driver)
    if not selected:
        selected.append(ranked[0])
    return selected[:thresholds['max_products']]


def generate_brief_comment(
    current_df, prior_df, cdf, division, sales_type, current_year,
    current_month, thresholds=None
):
    """부문별 전월·전년누계·물량·단가·거래처를 한 문단으로 생성한다."""
    thresholds = {**COMMENT_THRESHOLDS, **(thresholds or {})}
    current_df = _preprocess(current_df)
    prior_df = _preprocess(prior_df)
    previous_year, previous_month = _previous_year_month(
        current_year, current_month
    )
    previous_period = _year_month(previous_year, previous_month)
    current_period = _year_month(current_year, current_month)
    amount_col = '달러금액' if sales_type == '수출' else '한국원화금액'
    unit = 'K' if sales_type == '수출' else '백만원'

    division_sub = _division_rows(current_df, division, sales_type)
    previous_total = _metric_values(
        division_sub[division_sub['연월'] == previous_period], amount_col
    )
    current_total = _metric_values(
        division_sub[division_sub['연월'] == current_period], amount_col
    )
    total_change = _metric_change(previous_total, current_total)

    if previous_total['sales'] == 0 and current_total['sales'] == 0:
        return "데이터 없음."
    if previous_total['sales']:
        total_direction = '증가' if total_change['sales_pct'] >= 0 else '감소'
        subject = f"{division} {sales_type}{_subject_particle(sales_type)}"
        headline = (
            f"{subject} {previous_total['sales']:,.0f}K에서 "
            f"{current_total['sales']:,.0f}K로 전월 대비 "
            f"{_format_abs_percent(total_change['sales_pct'])} "
            f"{total_direction}하였음."
            if sales_type == '수출'
            else
            f"{subject} {previous_total['sales']:,.0f}백만원에서 "
            f"{current_total['sales']:,.0f}백만원으로 전월 대비 "
            f"{_format_abs_percent(total_change['sales_pct'])} "
            f"{total_direction}하였음."
        )
    else:
        headline = (
            f"{division} {sales_type}은 당월 {current_total['sales']:,.0f}{unit}의 "
            "신규 실적이 발생하였음."
        )

    ytd = calculate_ytd_driver(
        current_df,
        prior_df,
        division,
        sales_type,
        current_year,
        current_month,
    )
    ytd_direction = '증가' if ytd['sales_pct'] >= 0 else '감소'
    current_unit_suffix = '로' if sales_type == '수출' else '으로'
    ytd_sentence = (
        f"누계 기준으로는 {current_year - 1}년 1~{current_month}월 "
        f"{ytd['previous']['sales']:,.0f}{unit} 대비 {current_year}년 "
        f"1~{current_month}월 {ytd['current']['sales']:,.0f}{unit}{current_unit_suffix} "
        f"{_format_abs_percent(ytd['sales_pct'])} {ytd_direction}하였으며, "
        f"판매량은 {_format_direction_change(ytd['volume_pct'])}, 평균단가는 "
        f"{_format_direction_change(ytd['unit_price_pct'], '상승', '하락')}하였음."
    )

    rules = report_product_rules(division, sales_type)
    drivers = [
        calculate_product_driver(
            current_df, rule, previous_period, current_period
        )
        for rule in rules
    ]
    selected = _select_product_drivers(
        drivers, total_change['sales_pct'], thresholds
    )
    product_sentences = [_product_driver_sentence(driver) for driver in selected]

    price_sentences = []
    for driver in selected:
        if (
            not driver['previous']['sales']
            or not driver['current']['sales']
            or not driver['previous']['volume']
            or not driver['current']['volume']
        ):
            continue
        if abs(driver['unit_price_pct']) < thresholds['unit_price_pct']:
            continue
        decomposition = decompose_unit_price(
            current_df,
            driver['rule'],
            previous_period,
            current_period,
        )
        sentence = _price_cause_sentence(
            driver,
            decomposition,
            thresholds['max_price_causes'],
            minimum_price_pct=thresholds['unit_price_pct'],
        )
        if sentence:
            price_sentences.append(sentence)

    direction = 'increase' if total_change['sales_delta'] >= 0 else 'decrease'
    rep_col = (
        '담당자(세부)명' if sales_type == '수출' else '담당자명'
    )
    if direction == 'increase':
        customer_factors = _get_growth_factors(
            division_sub,
            rep_col,
            amount_col,
            f"{previous_period[-2:]}월",
            f"{current_period[-2:]}월",
            top_n=2,
        )
    else:
        customer_factors = _get_decline_factors(
            division_sub,
            rep_col,
            amount_col,
            f"{previous_period[-2:]}월",
            f"{current_period[-2:]}월",
            top_n=2,
        )
    customer_changes = get_customer_changes(
        cdf,
        division,
        sales_type,
        previous_period,
        current_period,
        current_year,
        direction=direction,
        top_n=thresholds['max_customers'],
        factors=customer_factors,
    )
    customer_sentence = _customer_change_sentence(
        customer_changes, unit, direction
    )

    sentences = [headline, ytd_sentence, *product_sentences, *price_sentences]
    if customer_sentence:
        sentences.append(customer_sentence)
    return " ".join(sentence for sentence in sentences if sentence)


def generate_brief_report_with_customers(
    current_df, prior_df, cdf, current_year, current_month,
    include_domestic=True, thresholds=None
):
    """향후 월별 실행에 사용하는 브리핑형 매출실적 코멘트."""
    previous_year, previous_month = _previous_year_month(
        current_year, current_month
    )
    lines = [
        f"# {current_year}년 {current_month}월 매출실적 분석",
        "",
        (
            f"> 전월 비교: {previous_year}년 {previous_month}월 → "
            f"{current_year}년 {current_month}월 | 누계 비교: "
            f"{current_year - 1}년 1~{current_month}월 → "
            f"{current_year}년 1~{current_month}월"
        ),
        "",
        "## 수출",
        "",
    ]
    for division in ['합섬', '스텐', '제강']:
        comment = generate_brief_comment(
            current_df,
            prior_df,
            cdf,
            division,
            '수출',
            current_year,
            current_month,
            thresholds=thresholds,
        )
        lines.extend([f"### {division}", "", comment, ""])

    if include_domestic:
        lines.extend(["## 내수", ""])
        for division in ['합섬', '스텐', '제강']:
            comment = generate_brief_comment(
                current_df,
                prior_df,
                cdf,
                division,
                '내수',
                current_year,
                current_month,
                thresholds=thresholds,
            )
            lines.extend([f"### {division}", "", comment, ""])

    lines.extend([
        "---",
        (
            "> 공식 원자료 기준 자동 생성 초안입니다. 거래처 상세파일은 "
            "고객별 증감액과 거래 이력 확인에만 사용합니다."
        ),
    ])
    return "\n".join(lines)
