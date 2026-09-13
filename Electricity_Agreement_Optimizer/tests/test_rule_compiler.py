"""Compilation checks use fictional candidates and independent expected arithmetic."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from electricity_optimizer.agreements import Citation
from electricity_optimizer.compiled_workflow import build_compilation_workflow
from electricity_optimizer.pricing import calculate_month
from electricity_optimizer.pricing_examples import teaching_examples
from electricity_optimizer.pricing_schema import PricingRule
from electricity_optimizer.rule_compiler import (
    ComparisonScope, compile_scenario, compare_compiled, fingerprint, load_saved_candidates,
)
from electricity_optimizer.usage import MonthlyUsage, UsageYear


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.document, self.record = teaching_examples()[0]
        self.scope = ComparisonScope(country="United States", territory="Fictional Demo Zone",
                                     customer_type="residential", document_date="2026-09-01")
        self.usage = UsageYear(months=tuple(MonthlyUsage(month=f"2025-{m:02d}", kwh=1000) for m in range(1, 13)))

    def compile(self, exclusions=None):
        return compile_scenario(self.record, self.document, self.scope, exclusions)

    def add_credit(self):
        quote = "A monthly credit of USD 30 applies at or above 1000 kWh."
        self.document.pages[0].text += "\n" + quote
        citations = [Citation(page_number=1, quote=quote)]
        coverage = next(c for c in self.record.candidate.coverage if c.component == "credit")
        coverage.status, coverage.citations = "present", citations
        rule = PricingRule(label="Monthly credit", component="credit", kind="usage_credit", status="found",
            amount="30", unit="currency_per_billing_cycle", lower_kwh="1000", upper_kwh=None,
            lower_inclusive=True, upper_inclusive=None, bands=[], tier_method=None,
            time_window=None, conditions=None, citations=citations)
        self.record.candidate.rules.append(rule)
        return rule

    def test_provider_independent_conversion_and_annual_arithmetic(self):
        plan = self.compile()
        self.assertEqual(plan.energy_usd_per_kwh, Decimal("0.10"))
        self.assertEqual(plan.delivery_usd_per_kwh, 0)  # Explicit absence with citations.
        result = compare_compiled(self.usage, [plan])
        self.assertEqual(result["results"][0]["annual_subtotal_usd"], "1260.00")
        self.assertEqual(result["status"], "insufficient_comparable_plans")

    def test_credit_boundary_and_cap(self):
        rule = self.add_credit()
        plan = self.compile()
        for kwh, credit, total in [(999, "0.00", "104.90"), (1000, "30.00", "75.00"), (1001, "30.00", "75.10")]:
            bill = calculate_month(MonthlyUsage(month="2025-01", kwh=kwh), plan)
            self.assertEqual(bill.credit_usd, Decimal(credit))
            self.assertEqual(bill.total_usd, Decimal(total))
        # Semantic changes require human review even when a quote still matches.
        rule.amount = "300"
        bill = calculate_month(MonthlyUsage(month="2025-01", kwh=1000), self.compile())
        self.assertEqual(bill.total_usd, 0)
        self.assertEqual(bill.credit_usd, Decimal("105.00"))

    def test_unsupported_boundaries_and_daily_time_rules_fail(self):
        rule = self.add_credit()
        rule.lower_inclusive = False
        with self.assertRaisesRegex(ValueError, "inclusive lower"):
            self.compile()
        rule.lower_inclusive = True
        rule.upper_kwh, rule.upper_inclusive = "2000", True
        with self.assertRaisesRegex(ValueError, "inclusive lower"):
            self.compile()
        self.setUp()
        self.record.candidate.rules[0].unit = "currency_per_day"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.compile()
        document, record = teaching_examples()[1]
        with self.assertRaisesRegex(ValueError, "time windows"):
            compile_scenario(record, document, self.scope)

    def test_unknown_zero_and_duplicate_rules_are_rejected(self):
        coverage = next(c for c in self.record.candidate.coverage if c.component == "delivery")
        coverage.status, coverage.citations = "not_stated", []
        with self.assertRaisesRegex(ValueError, "missing is not zero"):
            self.compile()
        self.setUp()
        self.record.candidate.rules.append(self.record.candidate.rules[0].model_copy(deep=True))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.compile()

    def test_extra_rule_requires_explicit_exclusion_and_changes_review_id(self):
        rule = self.record.candidate.rules[0].model_copy(deep=True)
        rule.label, rule.kind, rule.status, rule.amount, rule.unit = "Unpriced adjustment", "other", "ambiguous", None, "unknown"
        self.record.candidate.rules.append(rule)
        with self.assertRaisesRegex(ValueError, "unresolved amount"):
            self.compile()
        plan = self.compile({fingerprint(rule): "Scenario excludes this unpriced adjustment."})
        self.assertTrue(any(e.get("rule_id") == fingerprint(rule) for e in plan.exclusions))
        revised = self.compile({fingerprint(rule): "Different explicit scope justification."})
        self.assertNotEqual(plan.review_fingerprint, revised.review_fingerprint)
        rule.conditions = "Changed condition"
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.compile({plan.exclusions[-1]["rule_id"]: "Old decision"})

    def test_stale_evidence_and_conflicting_scope_block(self):
        self.document.sha256 = "changed"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.compile()
        self.setUp()
        self.record.candidate.rules[0].citations[0].quote = "Invented quote"
        with self.assertRaisesRegex(ValueError, "Quote not found"):
            self.compile()
        self.setUp()
        self.scope = self.scope.model_copy(update={"territory": "Different area"})
        with self.assertRaisesRegex(ValueError, "territory"):
            self.compile()
        self.setUp()
        self.record.candidate.identity.currency.value = "GBP"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.compile()

    def test_duplicate_sources_incompatible_scopes_and_ties(self):
        plan = self.compile()
        with self.assertRaisesRegex(ValueError, "Duplicate source"):
            compare_compiled(self.usage, [plan, plan])
        other = plan.model_copy(update={"name": "Other plan", "source_sha256": "different"})
        tied = compare_compiled(self.usage, [plan, other])
        self.assertIn("Other plan", tied["explanation"])
        self.assertNotIn("Difference", tied["explanation"])
        other = other.model_copy(update={"scope": self.scope.model_copy(update={"country": "Canada"})})
        with self.assertRaisesRegex(ValueError, "same territory"):
            compare_compiled(self.usage, [plan, other])

    def test_workflow_keeps_blocked_plan_in_inventory(self):
        bad_document, bad_record = teaching_examples()[1]
        result = build_compilation_workflow(self.scope, self.usage).invoke({"entries": [
            {"record": self.record, "document": self.document},
            {"record": bad_record, "document": bad_document}]})
        self.assertEqual(len(result["compilation"]), 2)
        self.assertEqual(len(result["plans"]), 1)
        self.assertEqual(result["comparison"]["status"], "insufficient_comparable_plans")

    def test_discovery_chooses_latest_and_reports_bad_records(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.record.origin = "live"
            self.record.source_file = "source.pdf"
            self.document.source_file = "source.pdf"
            (root / "older.json").write_text(self.record.model_dump_json(), encoding="utf-8")
            self.record.created_at = "2026-09-02T00:00:00+00:00"
            (root / "newer.json").write_text(self.record.model_dump_json(), encoding="utf-8")
            (root / "bad.json").write_text("{}", encoding="utf-8")
            with patch("electricity_optimizer.rule_compiler.read_pdf", return_value=self.document):
                loaded = load_saved_candidates(root, root)
            self.assertEqual(len(loaded["selected"]), 1)
            self.assertTrue(loaded["selected"][0]["record_file"].endswith("newer.json"))
            self.assertEqual(sorted(r["status"] for r in loaded["inventory"]), ["invalid", "older_matching_record", "selected"])
