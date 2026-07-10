"""
comment_generator.py
====================
월별 실적 코멘트 자동 생성 모듈
"""

import pandas as pd


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
            구분_list = [c for c in df['내수/수출'].unique()
                        if '수출' in str(c) and '현지내수' not in str(c) and 'TRADING' not in str(c)]
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


def _top_changed_lv2(sub, rep_col, rep, amt_col, prev_m, curr_m, pct):
    """증가는 당월, 감소는 전월 기여가 큰 품목을 우선 선택"""
    rep_sub = sub[sub[rep_col] == rep]
    if rep_sub.empty:
        return None, curr_m

    grp = rep_sub.groupby(['월', '레벨2명'])[amt_col].sum().unstack('월').fillna(0)
    if grp.empty:
        return None, curr_m

    if pct >= 0:
        target_month = curr_m
        sort_key = grp.get(curr_m, 0)
    else:
        target_month = prev_m
        sort_key = grp.get(prev_m, 0) - grp.get(curr_m, 0)

    sort_key = sort_key.sort_values(ascending=False)
    if sort_key.empty:
        return None, target_month
    return sort_key.index[0], target_month


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
            구분_list = [c for c in df['내수/수출'].unique()
                        if '수출' in str(c) and '현지내수' not in str(c) and 'TRADING' not in str(c)]
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

        # 기저효과
        base_effects = detect_base_effect(df, 부문, 구분_list, rep_col, months)
        base_str = ""
        if base_effects:
            be_parts = []
            for rep, lv2name, v2, v1, v0 in base_effects:
                customers = get_top_customers(cdf, 부문, rep, lv2name, prev_m, 구분=구분, n=top_n)
                cust_str = _format_customers(customers, unit)
                suffix = f" - 주요 END USER: {cust_str}" if cust_str else ""
                be_parts.append(f"{rep}의 {lv2name} 전월 출고({v1:,.0f}{unit})에 따른 기저효과{suffix}")
            base_str = ". ".join(be_parts) + "가 작용하였음"

        # 주요 증가 요인
        growth_factors = _get_growth_factors(sub, rep_col, amt_col, prev_m, curr_m)
        growth_lines = []
        for item in growth_factors:
            lv1 = fmt_lv1(item['lv1'])
            line = (
                f"{item['rep']}의 {lv1}/{item['lv2']} "
                f"+{item['delta']:,.0f}{unit}({item['pct']:.0f}% 증가, "
                f"증가요인 내 비중 {item['contribution']:.0f}%)"
            )
            customers = get_top_customers(
                cdf, 부문, item['rep'], item['lv2'], curr_m, 구분=구분, n=top_n
            )
            cust_str = _format_customers(customers, unit)
            if cust_str:
                line += f" - 주요 END USER: {cust_str}"
            growth_lines.append(line)
        growth_str = "주요 증가 요인은 " + ", ".join(growth_lines) + "임" if growth_lines else ""

        # 담당자별 주요 증감 + 거래처
        rep_grp = sub.groupby(['월', rep_col])[amt_col].sum().unstack('월').fillna(0)
        rep_changes = []
        for rep in rep_grp.index:
            p = float(rep_grp.loc[rep].get(prev_m, 0))
            c = float(rep_grp.loc[rep].get(curr_m, 0))
            if p > 0 and abs((c - p) / p) > 0.3 and max(p, c) > 50:
                rep_changes.append((rep, p, c, (c - p) / p * 100))
        rep_changes.sort(key=lambda x: -abs(x[3]))

        rep_lines = []
        for rep, p, c, pct in rep_changes[:3]:
            arrow = "증가" if pct > 0 else "감소"
            line = f"{rep} {abs(pct):.0f}% {arrow}"

            best_lv2, customer_month = _top_changed_lv2(sub, rep_col, rep, amt_col, prev_m, curr_m, pct)
            if best_lv2:
                customers = get_top_customers(cdf, 부문, rep, best_lv2, customer_month, 구분=구분, n=top_n)
                cust_str = _format_customers(customers, unit)
                if cust_str:
                    line += f" ({best_lv2} 중심 - 주요 END USER: {cust_str})"

            rep_lines.append(line)

        rep_str = ", ".join(rep_lines) + "함" if rep_lines else ""

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


def generate_full_report_with_customers(df, cdf, months):
    """END USER 포함 전체 코멘트 생성"""
    df = _preprocess(df)
    curr_m = months[-1]

    lines = [
        f"# {curr_m} 매출실적 분석 코멘트 (END USER 포함, 자동 생성)\n",
        f"> 전월: {months[-2]} | 당월: {curr_m}\n",
        "---\n",
        "## 수출 (END USER 포함)\n",
    ]
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment_with_customers(df, cdf, 부문, months)
        lines.append(f"- **{부문}** : {c['수출']}")

    lines.append("\n## 내수 (END USER 포함)\n")
    for 부문 in ['합섬', '스텐', '제강']:
        c = generate_comment_with_customers(df, cdf, 부문, months)
        lines.append(f"- **{부문}** : {c['내수']}")

    lines += ["\n---", "> ⚠️ 자동 생성된 초안입니다. END USER·기저효과 맥락을 추가해 주세요."]
    return "\n".join(lines)
