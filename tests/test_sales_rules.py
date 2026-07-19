import unittest

import pandas as pd

from sales_rules import steel_gs_weight


class SteelGuyStrandRuleTest(unittest.TestCase):
    def test_gs_uses_exact_sales_type_without_double_counting(self):
        df = pd.DataFrame([
            {
                "부문": "제강",
                "내수/수출": "내수",
                "레벨1명": "스틸ＳＴ",
                "레벨2명": "GUY STRAND",
                "중량": 12.715,
            },
            {
                "부문": "제강",
                "내수/수출": "수출",
                "레벨1명": "스틸ＳＴ",
                "레벨2명": "GUY STRAND",
                "중량": 3.5,
            },
            {
                "부문": "제강",
                "내수/수출": "CABLE VINA-내수",
                "레벨1명": "스틸ＳＴ",
                "레벨2명": "GUY STRAND",
                "중량": 99.0,
            },
        ])

        self.assertEqual(steel_gs_weight(df, "내수"), 12.715)
        self.assertEqual(steel_gs_weight(df, "수출"), 3.5)


if __name__ == "__main__":
    unittest.main()
