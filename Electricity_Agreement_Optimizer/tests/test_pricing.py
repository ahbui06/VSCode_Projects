import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from electricity_optimizer.usage import MonthlyUsage, UsageYear, load_usage_csv
from electricity_optimizer.pricing import DemoPlan, calculate_month, compare_plans


def plan(**changes):
    return DemoPlan(**(dict(name="Fictional test", energy_usd_per_kwh="0.15",
        base_usd_per_month="5", delivery_usd_per_kwh="0.05", delivery_usd_per_month="5",
        credit_usd="50", credit_min_kwh="1000") | changes))


class PricingTests(unittest.TestCase):
    def test_threshold_and_line_items(self):
        for kwh, expected in [("999", "209.80"), ("1000", "160.00"), ("1001", "160.20")]:
            bill = calculate_month(MonthlyUsage(month="2025-01", kwh=kwh), plan())
            self.assertEqual(bill.total_usd, Decimal(expected))
            self.assertEqual(bill.total_usd, bill.energy_usd + bill.base_usd + bill.delivery_usd - bill.credit_usd)

    def test_rounding_and_credit_cap(self):
        bill = calculate_month(MonthlyUsage(month="2025-01", kwh="1"), plan(
            energy_usd_per_kwh="0.005", base_usd_per_month="0", delivery_usd_per_kwh="0", delivery_usd_per_month="0",
            credit_usd="0", credit_min_kwh=None))
        self.assertEqual(bill.total_usd, Decimal("0.01"))
        bill = calculate_month(MonthlyUsage(month="2025-01", kwh="0"), plan(credit_min_kwh="0"))
        self.assertEqual(bill.total_usd, Decimal("0.00"))

    def test_reject_bad_values_and_months(self):
        for value in ["-1", "NaN", "Infinity"]:
            with self.assertRaises(ValueError):
                MonthlyUsage(month="2025-01", kwh=value)
        with self.assertRaises(ValueError):
            MonthlyUsage(month="2025-13", kwh="5")
        for months in [tuple(MonthlyUsage(month="2025-01", kwh="5") for _ in range(12)), ()]:
            with self.assertRaises(ValueError):
                UsageYear(months=months)

    def test_csv_sort_and_annual_totals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "usage.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["month", "kwh"])
                writer.writerows((f"2025-{m:02d}", "1000") for m in range(12, 0, -1))
            usage = load_usage_csv(path)
        results = compare_plans(usage, [plan(), plan(name="No credit", credit_usd="0", credit_min_kwh=None)])
        self.assertEqual(results[0].annual_usd, Decimal("1920.00"))
        self.assertEqual(results[1].annual_usd, Decimal("2520.00"))
