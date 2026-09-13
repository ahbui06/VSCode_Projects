import unittest
from decimal import Decimal

from electricity_optimizer.models import PDFDocument, PDFPage
from electricity_optimizer.review import (PricingReview, ReviewedValue, Evidence,
    review_blockers, compile_reviewed_plan, SUPPORTED_STRUCTURE)
from electricity_optimizer.pricing import calculate_month
from electricity_optimizer.usage import MonthlyUsage


class ReviewTests(unittest.TestCase):
    def setUp(self):
        # Explicit synthetic test evidence. No real agreement is approved here.
        self.doc = PDFDocument(source_file="test-only", sha256="test", pages=[
            PDFPage(page_number=1, text="Synthetic test fixture: flat rates and no extra charges.", needs_review=False)])
        self.review = PricingReview(source_file="test-only", source_sha256="test")

    def complete(self):
        values = dict(plan_name="Test plan", territory="Test territory", currency="USD",
            energy_usd_per_kwh="0.12", base_usd_per_month="0", delivery_usd_per_kwh="0.05",
            delivery_usd_per_month="5", pricing_structure=SUPPORTED_STRUCTURE)
        for name, value in values.items():
            setattr(self.review, name, ReviewedValue(value=value, reviewer="test-only",
                reviewed_on="2026-09-10", evidence=[Evidence(source_sha256="test",
                page_number=1, quote=self.doc.pages[0].text)]))
        self.review.accept_scenario_assumptions = True

    def test_missing_review_blocks(self):
        with self.assertRaises(ValueError):
            compile_reviewed_plan(self.review, [self.doc])

    def test_completed_fixture_connects_to_arithmetic(self):
        self.complete()
        plan = compile_reviewed_plan(self.review, [self.doc])
        bill = calculate_month(MonthlyUsage(month="2025-01", kwh="1000"), plan)
        self.assertEqual(bill.total_usd, Decimal("175.00"))
        self.assertFalse(plan.fictional)

    def test_zero_requires_evidence(self):
        self.complete()
        self.review.base_usd_per_month.evidence = []
        self.assertTrue(any("base_usd_per_month" in b for b in review_blockers(self.review, [self.doc])))

    def test_bad_number_and_source_and_structure(self):
        self.complete()
        self.review.energy_usd_per_kwh.value = "NaN"
        self.review.pricing_structure.value = "time_of_use"
        self.review.currency.evidence[0].source_sha256 = "wrong"
        blockers = review_blockers(self.review, [self.doc])
        self.assertTrue(any("finite" in b for b in blockers))
        self.assertTrue(any("different engine" in b for b in blockers))
        self.assertTrue(any("evidence does not match" in b for b in blockers))
