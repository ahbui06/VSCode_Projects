"""Offline schema, evidence, replay and real-SDK integration checks."""
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI
from pydantic import ValidationError

from electricity_optimizer.extraction import ExtractionError
from electricity_optimizer.models import TableCell
from electricity_optimizer.pricing_examples import teaching_examples
from electricity_optimizer.pricing_extraction import (
    build_pricing_workflow, extract_pricing, load_pricing_record,
    pricing_document_input, save_pricing_record,
)
from electricity_optimizer.pricing_schema import assess_pricing, normalized_kwh_rate


class GeneralPricingTests(unittest.TestCase):
    def setUp(self):
        self.document, self.record = teaching_examples()[0]
        self.candidate = self.record.candidate

    def test_examples_route_and_never_approve(self):
        routes = []
        for document, record in teaching_examples():
            result = build_pricing_workflow().invoke({"document": document, "record": record})
            routes.append(result["route"])
            self.assertFalse(result["assessment"]["approved_for_comparison"])
        self.assertEqual(routes, ["candidate_for_pricing_review", "needs_pricing_engine"])
        document, record = teaching_examples()[1]
        self.assertTrue(any("monthly kWh alone" in x for x in assess_pricing(record.candidate, document)["engine_work"]))

    def test_decimal_units_and_missing_amount(self):
        rule = self.candidate.rules[-1]
        self.assertEqual(normalized_kwh_rate(rule), Decimal("0.10"))
        rule.amount = None
        with self.assertRaises(ValueError):
            normalized_kwh_rate(rule)
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "needs_evidence_review")
        data = self.record.candidate.model_dump()
        data["rules"][0]["amount"] = "NaN"
        with self.assertRaises(ValidationError):
            type(self.candidate).model_validate(data)

    def test_missing_is_not_zero_and_conflicts_detected(self):
        delivery = next(c for c in self.candidate.coverage if c.component == "delivery")
        delivery.status = "not_stated"
        delivery.citations = []
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "needs_information")
        base = next(c for c in self.candidate.coverage if c.component == "base")
        base.status = "explicit_none"
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "needs_evidence_review")

    def test_wrong_quote_wrong_page_and_cell_match(self):
        cite = self.candidate.rules[0].citations[0]
        cite.page_number = 99
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "needs_evidence_review")
        cite.page_number = 1
        cite.quote = "Invented charge: 123.45"
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "needs_evidence_review")
        # Isolated cell quotes are accepted and those same cells reach the model.
        self.document.pages[0].table_cells.append(TableCell(table_number=1, row_number=1,
            column_number=1, bbox=(0, 0, 10, 10), text=cite.quote))
        self.assertEqual(assess_pricing(self.candidate, self.document)["route"], "candidate_for_pricing_review")
        self.assertIn(cite.quote, pricing_document_input(self.document))

    def test_replay_fingerprint_versions_and_no_live_fallback(self):
        with TemporaryDirectory() as tmp:
            destination = save_pricing_record(self.record, Path(tmp))
            loaded = load_pricing_record(destination, self.document)
            self.assertEqual(loaded, self.record)
            with patch("electricity_optimizer.pricing_extraction.extract_pricing", side_effect=AssertionError("network")):
                result = build_pricing_workflow().invoke({"document": self.document, "record": loaded})
                self.assertEqual(result["route"], "candidate_for_pricing_review")
            self.document.sha256 = "changed"
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                load_pricing_record(destination, self.document)
        self.document, self.record = teaching_examples()[0]
        self.record.prompt_version = "old"
        with self.assertRaisesRegex(ValueError, "version"):
            build_pricing_workflow().invoke({"document": self.document, "record": self.record})

    def test_empty_oversized_and_duplicate_pages_rejected(self):
        self.document.pages[0].text = ""
        with self.assertRaisesRegex(ValueError, "No extracted text"):
            pricing_document_input(self.document)
        self.document.pages[0].text = "x" * 150_001
        with self.assertRaisesRegex(ValueError, "limit"):
            pricing_document_input(self.document)
        self.document.pages.append(self.document.pages[0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            pricing_document_input(self.document)

    def test_live_missing_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ExtractionError):
                extract_pricing(self.document)


class PricingSDKTests(unittest.TestCase):
    def call_api(self, content, status="completed"):
        document, _ = teaching_examples()[0]

        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-5")
            self.assertFalse(payload["store"])
            fmt = payload["text"]["format"]
            self.assertTrue(fmt["strict"])
            # Every object in the submitted schema forbids extras and requires its keys.
            def visit(value):
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertFalse(value["additionalProperties"])
                        self.assertEqual(set(value["properties"]), set(value["required"]))
                    for item in value.values(): visit(item)
                elif isinstance(value, list):
                    for item in value: visit(item)
            visit(fmt["schema"])
            return httpx.Response(200, json={"id": "resp_offline", "object": "response",
                "created_at": 0, "status": status, "model": "gpt-5", "output": [
                    {"id": "msg_test", "type": "message", "role": "assistant",
                     "status": "completed", "content": content}]})

        with OpenAI(api_key="offline-test-key", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            return extract_pricing(document, client=client)

    def test_real_sdk_structured_parsing(self):
        document, record = teaching_examples()[0]
        result = self.call_api([{"type": "output_text", "text": record.candidate.model_dump_json(), "annotations": []}])
        self.assertEqual(result.candidate, record.candidate)
        self.assertEqual(result.source_sha256, document.sha256)
        self.assertEqual(result.origin, "live")

    def test_refusal_incomplete_and_malformed_not_accepted(self):
        with self.assertRaisesRegex(ExtractionError, "refused"):
            self.call_api([{"type": "refusal", "refusal": "offline refusal"}])
        with self.assertRaises(ExtractionError):
            self.call_api([], "incomplete")
        with self.assertRaises(ExtractionError):
            self.call_api([{"type": "output_text", "text": "{}", "annotations": []}])
