"""
comment_generator.py
====================
월별 실적 코멘트 자동 생성 모듈
"""

import pandas as pd


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
    # 달러금액/원화금액 단위 변환 (이미 변환된 경우 스킵)
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
            df = pd.read_excel(path, sheet_name=0)
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
    df['월'] = df['출고요청년월'].astype(str).str[-2:] + '월'
    df['달러금액'] = pd.to_numeric(df['달러금액'], errors='coerce').fillna(0)
    if df['달러금액'].max() > 100000:
        df['달러금액'] = df['달러금액'] / 1000
    if '원화금액' in df.columns:
        df['원화금액'] = pd.to_numeric(df['원화금액'], errors='coerce').fillna(0)
        if df['원화금액'].max() > 100000:
            df['원화금액'] = df['원화금액'] / 1_000_000

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
            unit = '$K'
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

        lines = [
            "**한눈에 보기**",
            f"- 실적: {_format_change(prev_tot, curr_tot, unit)}",
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
                    lines.append(f"   - END USER: {cust_str}")

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
                    line += f" (전월 END USER: {cust_str})"
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
