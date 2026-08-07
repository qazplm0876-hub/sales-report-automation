import unittest
from types import SimpleNamespace

import pandas as pd

from sales_rules import plan_month_row, steel_gs_weight, ytd_monthly_plan


class FakeWorksheet:
    def __init__(self, values):
        self.values = values

    def cell(self, row, column):
        return SimpleNamespace(value=self.values.get((row, column)))


class MonthlyPlanRuleTest(unittest.TestCase):
    def test_month_rows_skip_quarter_total_rows(self):
        self.assertEqual(
            [plan_month_row(month) for month in range(1, 13)],
            [6, 7, 8, 10, 11, 12, 14, 15, 16, 18, 19, 20],
        )

    def test_july_ytd_includes_first_quarter_months(self):
        values = {
            (plan_month_row(month), 4): month
            for month in range(1, 13)
        }
        values[(9, 4)] = 600
        values[(13, 4)] = 1_500
        ws = FakeWorksheet(values)

        self.assertEqual(
            ytd_monthly_plan(ws, plan_month_row(7), 4, 7),
            sum(range(1, 8)),
        )

    def test_october_ytd_includes_all_prior_months_with_section_offset(self):
        section_offset = 23
        values = {
            (plan_month_row(month) + section_offset, 7): month * 10
            for month in range(1, 13)
        }
        ws = FakeWorksheet(values)

        self.assertEqual(
            ytd_monthly_plan(
                ws,
                plan_month_row(10) + section_offset,
                7,
                10,
            ),
            sum(range(1, 11)) * 10,
        )


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
