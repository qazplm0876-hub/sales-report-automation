import unittest

import pandas as pd

from comment_generator import generate_comment_with_customers


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


if __name__ == '__main__':
    unittest.main()
