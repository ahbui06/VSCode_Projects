from decimal import Decimal
from pathlib import Path
import unittest

from electricity_optimizer.efl_comparison import parse_power_savings, compare_efls
from electricity_optimizer.ingestion import read_pdf
from electricity_optimizer.models import PDFDocument, PDFPage
from electricity_optimizer.extraction import citation_matches
from electricity_optimizer.pricing import calculate_month
from electricity_optimizer.usage import MonthlyUsage, UsageYear


class EFLTests(unittest.TestCase):
    def setUp(self):
        self.doc = PDFDocument(source_file="test.pdf", sha256="test", pages=[PDFPage(
            page_number=1, needs_review=False, text="""Reliant Power Savings 2,000 kWh 12 plan
AEP Texas Central service area Date: 09/01/2026
Base Charge: $0.00 per billing cycle Energy Charge: 16.6483¢ per kWh
AEP Texas Central Delivery Charges: $3.24 per billing cycle and 5.7554¢ per kWh
A Usage Credit of $150.00 will be included for each billing cycle when your usage on this plan is above or equal to 2,000 kWh
Contract Term 12 months Yes. $150. Applies through the end of the contract term.""")])

    def test_units_evidence_and_threshold(self):
        plan = parse_power_savings(self.doc)
        self.assertEqual(plan.delivery_usd_per_kwh, Decimal("0.057554"))
        self.assertTrue(all(citation_matches(e.quote, self.doc.pages[0]) for e in plan.evidence.values()))
        for kwh, credit, total in [(1999, "0", "451.09"), (2000, "150", "301.32"), (2001, "150", "301.54")]:
            bill = calculate_month(MonthlyUsage(month="2025-01", kwh=kwh), plan)
            self.assertEqual(bill.credit_usd, Decimal(credit))
            self.assertEqual(bill.total_usd, Decimal(total))

    def test_missing_or_conflicting_rates_rejected(self):
        self.doc.pages[0].text += " Energy Charge: 10.0¢ per kWh"
        with self.assertRaises(ValueError):
            parse_power_savings(self.doc)
        self.doc.pages[0].text = "no price information"
        with self.assertRaises(ValueError):
            parse_power_savings(self.doc)

    def test_incompatible_dates_rejected(self):
        first = parse_power_savings(self.doc)
        second = first.model_copy(update={"name": "Other", "document_date": "01/01/2025"})
        usage = UsageYear(months=tuple(MonthlyUsage(month=f"2025-{m:02d}", kwh=1000) for m in range(1, 13)))
        with self.assertRaises(ValueError):
            compare_efls(usage, [first, second])
