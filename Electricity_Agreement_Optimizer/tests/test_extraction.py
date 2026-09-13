"""Offline checks for grounding and SDK parsing; no API key or paid calls."""

import json
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from electricity_optimizer.agreements import AgreementTerms, ContractTerm, Citation
from electricity_optimizer.extraction import build_document_input, extract_agreement, validate_terms, ExtractionError
from electricity_optimizer.models import PDFDocument, PDFPage


def example():
    document = PDFDocument(source_file="synthetic.pdf", sha256="test-fingerprint", pages=[
        PDFPage(page_number=1, text="Contract term:\n12 months. Energy charge: 10 cents/kWh.", needs_review=False)
    ])
    terms = AgreementTerms(**{
        name: ContractTerm(status="not_stated", value=None, citations=[])
        for name in AgreementTerms.model_fields
    })
    terms.contract_length = ContractTerm(status="found", value="12 months", citations=[
        Citation(page_number=1, quote="Contract term: 12 months.")
    ])
    return document, terms


class GroundingTests(unittest.TestCase):
    def test_whitespace_normalization(self):
        doc, terms = example()
        self.assertFalse(any(i.severity == "error" for i in validate_terms(terms, doc)))

    def test_fabricated_quote(self):
        doc, terms = example()
        terms.contract_length.citations[0].quote = "Contract term: 36 months."
        self.assertTrue(any("Quote not found" in i.message for i in validate_terms(terms, doc)))

    def test_wrong_page(self):
        doc, terms = example()
        terms.contract_length.citations[0].page_number = 99
        self.assertTrue(any("does not exist" in i.message for i in validate_terms(terms, doc)))

    def test_missing_is_not_zero(self):
        doc, terms = example()
        terms.termination_fee.value = "0"
        self.assertTrue(any(i.field == "termination_fee" and i.severity == "error" for i in validate_terms(terms, doc)))

    def test_found_requires_evidence_and_value(self):
        doc, terms = example()
        terms.contract_length.value = None
        terms.contract_length.citations = []
        self.assertEqual(2, sum(i.severity == "error" for i in validate_terms(terms, doc)))

    def test_ambiguous_and_sparse_are_flagged(self):
        doc, terms = example()
        terms.contract_length.status = "ambiguous"
        doc.pages[0].needs_review = True
        issues = validate_terms(terms, doc)
        self.assertTrue(any(i.field == "contract_length" and i.severity == "warning" for i in issues))
        self.assertTrue(any(i.field == "source" for i in issues))

    def test_empty_and_oversized_input_rejected(self):
        doc, _ = example()
        doc.pages[0].text = ""
        with self.assertRaises(ValueError):
            build_document_input(doc)
        doc.pages[0].text = "x" * 150_001
        with self.assertRaises(ValueError):
            build_document_input(doc)

    def test_missing_key(self):
        doc, _ = example()
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ExtractionError):
                extract_agreement(doc)


class SDKTests(unittest.TestCase):
    def call_mock_api(self, content, status="completed"):
        doc, _ = example()

        def handler(request):
            payload = json.loads(request.content)
            self.assertFalse(payload["store"])
            self.assertEqual(payload["model"], "gpt-5")
            self.assertTrue(payload["text"]["format"]["strict"])
            return httpx.Response(200, json={
                "id": "resp_offline_test", "object": "response", "created_at": 0,
                "status": status, "model": "gpt-5",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                            "status": "completed", "content": content}],
            })

        with OpenAI(api_key="offline-test-key", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            return extract_agreement(doc, model="gpt-5", client=client)

    def test_real_sdk_parses_and_preserves_source(self):
        _, terms = example()
        result = self.call_mock_api([{"type": "output_text", "text": terms.model_dump_json(), "annotations": []}])
        self.assertEqual(result.source_sha256, "test-fingerprint")
        self.assertEqual(result.terms.contract_length.value, "12 months")
        self.assertEqual(result.review_status, "needs_human_review")

    def test_refusal_is_not_an_extraction(self):
        with self.assertRaisesRegex(ExtractionError, "refused"):
            self.call_mock_api([{"type": "refusal", "refusal": "test refusal"}])

    def test_incomplete_is_not_accepted(self):
        with self.assertRaises(ExtractionError):
            self.call_mock_api([], status="incomplete")


if __name__ == "__main__":
    unittest.main()
