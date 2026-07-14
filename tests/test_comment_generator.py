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

        self.assertIn('- 북미: 300 → 570$K (+270$K, +90%)', result)
        self.assertIn('  - 방사: 100 → 220$K (+120$K, +120%)', result)
        self.assertIn('  - 비방사: 80 → 170$K (+90$K, +112%)', result)
        self.assertIn('  - 특수: 100 → 170$K (+70$K, +70%)', result)
        self.assertIn('  - 웨빙: 20 → 10$K (-10$K, -50%)', result)
        self.assertIn('세부 품목: SUPERFLEX 100 → 220$K', result)
        self.assertIn('세부 품목: PP-8 80 → 170$K', result)


if __name__ == '__main__':
    unittest.main()
