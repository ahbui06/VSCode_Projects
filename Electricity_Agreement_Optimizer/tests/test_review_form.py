import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electricity_optimizer.agreements import AgreementTerms, ContractTerm, Citation, ExtractionRecord
from electricity_optimizer.models import PDFDocument, PDFPage
from electricity_optimizer.review import PricingReview, ReviewedValue, Evidence
from electricity_optimizer.review_form import prefill_candidates, show_review_form, save_review


class ReviewFormTests(unittest.TestCase):
    def setUp(self):
        text = "Energy Charge: 18.2499 cents per kWh"
        self.doc = PDFDocument(source_file="test", sha256="test", pages=[PDFPage(
            page_number=1, text=text, needs_review=False)])
        terms = AgreementTerms(**{name: ContractTerm(status="not_stated", value=None, citations=[])
                                  for name in AgreementTerms.model_fields})
        terms.energy_charges = ContractTerm(status="found", value=text,
            citations=[Citation(page_number=1, quote=text)])
        self.record = ExtractionRecord(source_file="test", source_sha256="test", model="test",
            response_id="test", extracted_at="test", prompt_version="test", terms=terms, issues=[])
        self.review = PricingReview(source_file="test", source_sha256="test")

    def test_candidate_conversion_without_approval(self):
        result = prefill_candidates(self.review, self.record, self.doc)
        self.assertEqual(result.energy_usd_per_kwh.value, "0.182499")
        self.assertIsNone(result.energy_usd_per_kwh.reviewer)
        self.assertIsNone(result.currency.value)
        self.assertIsNone(result.base_usd_per_month.value)
        self.assertIsNone(self.review.energy_usd_per_kwh.value)

    def test_manual_value_preserved_and_unmatched_quote_ignored(self):
        self.review.energy_usd_per_kwh.value = "0.2"
        self.assertEqual(prefill_candidates(self.review, self.record, self.doc).energy_usd_per_kwh.value, "0.2")
        self.review.energy_usd_per_kwh.value = None
        self.doc.pages[0].text = "Unrelated page"
        self.assertIsNone(prefill_candidates(self.review, self.record, self.doc).energy_usd_per_kwh.value)

    def test_form_does_not_write_until_save_and_edits_clear_review(self):
        self.review.plan_name = ReviewedValue(value="Test plan", reviewer="Existing", reviewed_on="2026-09-10")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            before = self.review.model_dump_json(indent=2)
            path.write_text(before, encoding="utf-8")
            with patch("electricity_optimizer.review_form.display"), contextlib.redirect_stdout(io.StringIO()):
                form = show_review_form(path, self.record, [self.doc])
                self.assertEqual(path.read_text(encoding="utf-8"), before)
                form["save"].click()
                saved = PricingReview.model_validate_json(path.read_text(encoding="utf-8"))
                self.assertEqual(saved.plan_name.reviewer, "Existing")
                self.assertIsNone(saved.energy_usd_per_kwh.reviewer)
                form["controls"]["plan_name"][0].value = "Edited plan"
                form["save"].click()
                saved = PricingReview.model_validate_json(path.read_text(encoding="utf-8"))
                self.assertIsNone(saved.plan_name.reviewer)
                self.assertTrue(path.with_name("review.before_form_save.json").exists())

    def test_external_edits_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                save_review(path, "old", self.review)
            self.assertEqual(path.read_text(encoding="utf-8"), "changed")
