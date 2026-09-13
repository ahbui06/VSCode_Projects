"""Graph routing tests use synthetic in-memory records, never live API calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from electricity_optimizer.agreements import ExtractionRecord
from electricity_optimizer.workflow import build_workflow
from electricity_optimizer.models import TableCell
from test_extraction import example


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.document, terms = example()
        self.record = ExtractionRecord(source_file=self.document.source_file,
            source_sha256=self.document.sha256, model="synthetic", response_id="test",
            extracted_at="2026-01-01T00:00:00Z", prompt_version="test", terms=terms, issues=[])

    def run_graph(self, record):
        extractor = Mock(return_value=record)
        with patch("electricity_optimizer.workflow.read_pdf", return_value=self.document):
            result = build_workflow(live=True, extractor=extractor).invoke({"pdf_path": "test.pdf"})
        extractor.assert_called_once()
        return result

    def test_warnings_route_to_human(self):
        result = self.run_graph(self.record)
        self.assertEqual(result["status"], "human_review_required")
        self.assertEqual(result["trace"], ["load_document", "extract_terms", "validate_evidence", "supervisor", "human_review"])
        self.assertTrue(result["record"].issues)

    def test_bad_quote_routes_to_correction(self):
        self.record.terms.contract_length.citations[0].quote = "Invented text"
        self.assertEqual(self.run_graph(self.record)["status"], "correction_required")

    def test_table_evidence_reaches_main_workflow(self):
        self.document.pages[0].text = "Contract term: question interrupts 12 months."
        self.document.pages[0].table_cells = [TableCell(table_number=1,
            row_number=1, column_number=2, bbox=(0, 0, 100, 100),
            text="Contract term: 12 months.")]
        with patch("electricity_optimizer.workflow.read_pdf", return_value=self.document) as reader:
            result = build_workflow(live=True, extractor=Mock(return_value=self.record)).invoke({"pdf_path": "test.pdf"})
        reader.assert_called_once_with(Path("test.pdf"), include_tables=True)
        self.assertEqual(result["status"], "human_review_required")
        self.assertFalse(any(i.severity == "error" for i in result["record"].issues))

    def test_mismatched_source_fails(self):
        self.record.source_sha256 = "different"
        result = self.run_graph(self.record)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["record"])

    def test_missing_pdf_skips_extractor(self):
        extractor = Mock()
        with patch("electricity_optimizer.workflow.read_pdf", side_effect=FileNotFoundError):
            result = build_workflow(live=True, extractor=extractor).invoke({"pdf_path": "missing.pdf"})
        extractor.assert_not_called()
        self.assertEqual(result["trace"], ["load_document", "failed"])

    def test_replay_never_calls_api_and_refreshes_flags(self):
        extractor = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(self.record.model_dump_json(), encoding="utf-8")
            with patch("electricity_optimizer.workflow.read_pdf", return_value=self.document):
                result = build_workflow(saved_record_path=path, extractor=extractor).invoke({"pdf_path": "test.pdf"})
            self.assertTrue(result["record"].issues)
            path.write_text("invalid JSON", encoding="utf-8")
            with patch("electricity_optimizer.workflow.read_pdf", return_value=self.document):
                result = build_workflow(saved_record_path=path, extractor=extractor).invoke(result)
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["record"])
        extractor.assert_not_called()

    def test_explicit_mode_required(self):
        with self.assertRaises(ValueError):
            build_workflow()
        with self.assertRaises(ValueError):
            build_workflow(live=True, saved_record_path=Path("record.json"))
