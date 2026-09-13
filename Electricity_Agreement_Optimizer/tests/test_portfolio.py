from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from electricity_optimizer.models import PDFDocument, PDFPage
from electricity_optimizer.portfolio import scan_portfolio, compare_portfolio
from electricity_optimizer.efl_comparison import parse_power_savings
from electricity_optimizer.usage import MonthlyUsage, UsageYear
import test_efl_comparison


class PortfolioTests(unittest.TestCase):
    def test_scan_keeps_failed_unsupported_duplicate_and_uppercase(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["a.PDF", "b.pdf", "broken.pdf"]:
                (root / name).touch()
            (root / "bad.json").write_text("not json")
            def reader(path, **kwargs):
                if path.name == "broken.pdf":
                    raise ValueError("broken PDF")
                return PDFDocument(source_file=path.name, sha256="same", pages=[
                    PDFPage(page_number=1, text="General terms", needs_review=False)])
            with patch("electricity_optimizer.portfolio.read_pdf", side_effect=reader):
                result = scan_portfolio(root, root)
            self.assertEqual([r["status"] for r in result["inventory"]],
                             ["unsupported_or_incomplete", "duplicate", "unreadable"])
            self.assertEqual(len(result["saved_record_errors"]), 1)

    def test_incompatible_group_is_not_ranked_and_duplicate_names_block(self):
        fixture = test_efl_comparison.EFLTests()
        fixture.setUp()
        plan = parse_power_savings(fixture.doc)
        other = plan.model_copy(update={"document_date": "01/01/2025"})
        usage = UsageYear(months=tuple(MonthlyUsage(month=f"2025-{m:02d}", kwh=1000) for m in range(1, 13)))
        groups = compare_portfolio({"plans": [plan, other]}, usage)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(g["status"] == "waiting_for_comparable_plan" for g in groups))
        self.assertEqual(compare_portfolio({"plans": [plan, plan]}, usage)[0]["status"], "needs_review")
