import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from comment_generator import (
    _product_driver_sentence,
    calculate_product_driver,
    decompose_unit_price,
    generate_brief_comment,
    generate_comment_with_customers,
    load_customer_data,
)
from sales_rules import report_product_rules


class RegionalProductBreakdownTest(unittest.TestCase):
    def test_region_change_includes_multiple_product_groups_and_details(self):
        rows = [
            ('5월', '합섬방사', 'SUPERFLEX', 100),
            ('6월', '합섬방사', 'SUPERFLEX', 220),
            ('5월', '합섬비방사', 'PP-8', 80),
            ('6월', '합섬비방사', 'PP-8', 170),
            ('5월', '합섬특수', 'SUPERMAX', 100),
            ('6월', '합섬특수', 'SUPERMAX', 170),
            ('5월', '합섬웨빙', 'PET R/S', 20),
            ('6월', '합섬웨빙', 'PET R/S', 10),
        ]
        df = pd.DataFrame([
            {
                '월': month,
                '부문': '합섬',
                '내수/수출': '수출',
                '담당자명': '홍길동',
                '담당자(세부)명': '북미',
                '레벨1명': lv1,
                '레벨2명': lv2,
                '달러금액': amount,
                '한국원화금액': 0,
            }
            for month, lv1, lv2, amount in rows
        ])

        result = generate_comment_with_customers(
            df, pd.DataFrame(), '합섬', ['5월', '6월']
        )['수출']

        self.assertIn('전체 실적은 300 → 570K (+270K, +90%)로 전월 대비 증가하였음.', result)
        self.assertIn('- 북미: 300 → 570K (+270K, +90%)', result)
        self.assertIn('  - 방사: 100 → 220K (+120K, +120%)', result)
        self.assertIn('  - 비방사: 80 → 170K (+90K, +112%)', result)
        self.assertIn('  - 특수: 100 → 170K (+70K, +70%)', result)
        self.assertIn('  - 웨빙: 20 → 10K (-10K, -50%)', result)
        self.assertIn('세부 품목: SUPERFLEX 100 → 220K', result)
        self.assertIn('세부 품목: PP-8 80 → 170K', result)

    def test_customer_name_is_written_only_as_destination_performance(self):
        df = pd.DataFrame([
            {
                '월': month,
                '부문': '합섬',
                '내수/수출': '수출',
                '담당자명': '홍길동',
                '담당자(세부)명': '유럽',
                '레벨1명': '합섬방사',
                '레벨2명': 'SP1',
                '달러금액': amount,
                '한국원화금액': 0,
            }
            for month, amount in [('5월', 100), ('6월', 250)]
        ])
        cdf = pd.DataFrame([
            {
                '부문': '합섬',
                '담당자 세부': '유럽',
                'LVL2NM': 'SP1',
                '월': '6월',
                '내수/수출': '수출',
                '달러금액': 250,
                'END_USER': 'Funi Attrezzature',
            }
        ])

        result = generate_comment_with_customers(
            df, cdf, '합섬', ['5월', '6월']
        )['수출']

        self.assertIn(
            'SP1 증가는 유럽 지역의 Funi Attrezzature(250K) 향 실적 증가가 주요하게 작용하였음.',
            result,
        )
        self.assertIn('Funi Attrezzature(250K) 향 실적', result)
        self.assertNotIn('END USER', result)
        self.assertNotIn('거래처', result)
        self.assertNotIn('인수처명', result)


class BriefingCommentTest(unittest.TestCase):
    @staticmethod
    def _raw_row(period, level1, product, amount, volume, rep='북미'):
        return {
            '요청월': period,
            '월': f"{str(period)[-2:]}월",
            '부문': 'STS',
            '내수/수출': '수출',
            '담당자명': rep,
            '담당자(세부)명': rep,
            '레벨1명': level1,
            '레벨2명': 'SSWR',
            '약어명': product,
            '달러금액': amount,
            '한국원화금액': 0,
            '중량': volume,
        }

    def _current_data(self):
        return pd.DataFrame([
            self._raw_row('202605', '스텐선재', 'SS SPRING', 100, 20),
            self._raw_row('202606', '스텐선재', 'SS SPRING', 103.4, 19.8),
            self._raw_row('202605', '스텐로프', 'HIGH ROPE', 8, 1, '유럽'),
            self._raw_row('202605', '스텐로프', 'LOW ROPE', 12, 3, '북미'),
            self._raw_row('202606', '스텐로프', 'LOW ROPE', 28.5, 6.896, '북미'),
        ])

    def _prior_data(self):
        return pd.DataFrame([
            self._raw_row('202505', '스텐선재', 'SS SPRING', 80, 16),
            self._raw_row('202506', '스텐선재', 'SS SPRING', 90, 18),
            self._raw_row('202506', '스텐로프', 'LOW ROPE', 18, 4),
        ])

    def _customer_data(self):
        return pd.DataFrame([
            {
                '부문': '스텐', '내수/수출': '수출', '연월': '202505',
                '담당자 세부': '북미', '담당자명': '북미',
                'END_USER': 'SILGAN', '달러금액': 120, '원화금액': 0,
            },
            {
                '부문': '스텐', '내수/수출': '수출', '연월': '202605',
                '담당자 세부': '북미', '담당자명': '북미',
                'END_USER': 'SILGAN', '달러금액': 160, '원화금액': 0,
            },
            {
                '부문': '스텐', '내수/수출': '수출', '연월': '202606',
                '담당자 세부': '북미', '담당자명': '북미',
                'END_USER': 'SILGAN', '달러금액': 212, '원화금액': 0,
            },
        ])

    def test_product_driver_uses_revenue_volume_and_weighted_price(self):
        wire_rule = report_product_rules('스텐', '수출')[1]
        driver = calculate_product_driver(
            self._current_data(), wire_rule, '202605', '202606'
        )

        self.assertAlmostEqual(driver['sales_pct'], 3.4, places=6)
        self.assertAlmostEqual(driver['volume_pct'], -1.0, places=6)
        self.assertGreater(driver['unit_price_pct'], 4.0)

    def test_unit_price_decomposition_reconciles_to_average_price_change(self):
        rope_rule = report_product_rules('스텐', '수출')[0]
        result = decompose_unit_price(
            self._current_data(), rope_rule, '202605', '202606'
        )

        self.assertLess(abs(result['reconciliation_delta']), 1e-9)
        self.assertTrue(
            any(cause['cause_type'] == '고단가 중단' for cause in result['causes'])
        )

    def test_brief_comment_includes_ytd_and_customer_delta_history(self):
        comment = generate_brief_comment(
            self._current_data(),
            self._prior_data(),
            self._customer_data(),
            '스텐',
            '수출',
            2026,
            6,
        )

        self.assertIn('2025년 1~6월', comment)
        self.assertIn('2026년 1~6월', comment)
        self.assertIn(
            '2025년 1~6월 188K 대비 2026년 1~6월 252K',
            comment,
        )
        self.assertIn('선재는 판매량이 1.0% 감소했으나 평균단가가', comment)
        self.assertIn('북미 SILGAN +52K', comment)
        self.assertIn('전월 및 전년 거래 이력이 있는 기존 거래처', comment)

    def test_customer_files_are_scaled_individually(self):
        with TemporaryDirectory() as temp_dir:
            synthetic_path = Path(temp_dir) / 'synthetic.xlsx'
            steel_path = Path(temp_dir) / 'steel.xlsx'
            pd.DataFrame([{
                '출고요청년월': 202606,
                '달러금액': 333.0,
                '인수처명': 'CUSTOMER A',
            }]).to_excel(synthetic_path, index=False)
            pd.DataFrame([{
                '출고요청년월': 202606,
                '달러금액': 189691.0,
                '인수처명': 'CUSTOMER B',
            }]).to_excel(steel_path, index=False)

            customer_data = load_customer_data({
                '합섬': {'수출': synthetic_path},
                '스텐': {'수출': steel_path},
            })

        totals = customer_data.groupby('부문')['달러금액'].sum()
        self.assertAlmostEqual(totals['합섬'], 333.0)
        self.assertAlmostEqual(totals['스텐'], 189.691)

    def test_discontinued_product_does_not_report_unit_price_drop(self):
        sentence = _product_driver_sentence({
            'rule': {'label': '로프'},
            'sales_pct': -100.0,
            'volume_pct': -100.0,
            'unit_price_pct': -100.0,
            'previous': {'sales': 10.0},
            'current': {'sales': 0.0},
        })

        self.assertIn('당월 매출 실적이 없어', sentence)
        self.assertNotIn('평균단가', sentence)


if __name__ == '__main__':
    unittest.main()
