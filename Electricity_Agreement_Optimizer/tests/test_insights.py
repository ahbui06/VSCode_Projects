"""Offline report-integrity, reasoning-reference and mocked SDK checks."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from electricity_optimizer.extraction import ExtractionError
from electricity_optimizer.insight_context import build_insight_context, InsightPreferences
from electricity_optimizer.insights import (
    InsightRecord, build_insight_workflow, generate_insights, load_insight_record,
    offline_draft, save_insight_record, validate_insights,
)
from electricity_optimizer.pricing_examples import teaching_examples
from electricity_optimizer.rule_compiler import ComparisonScope, compile_scenario, compare_compiled, fingerprint
from electricity_optimizer.usage import MonthlyUsage, UsageYear


def example_report():
    scope = ComparisonScope(country="United States", territory="Fictional Demo Zone",
                            customer_type="residential", document_date="2026-09-01")
    usage = UsageYear(months=tuple(MonthlyUsage(month=f"2025-{m:02d}", kwh=1000) for m in range(1, 13)))
    plans, records, documents = [], [], {}
    for index in (1, 2):
        doc, record = teaching_examples()[0]
        changes = [("Simple 12", "Long Plan" if index == 1 else "Short Plan")]
        if index == 1:
            changes.append(("12 months", "24 months"))
        else:
            changes.append(("10 cents", "12 cents"))
        doc_json, record_json = doc.model_dump_json(), record.model_dump_json()
        for before, after in changes:
            doc_json, record_json = doc_json.replace(before, after), record_json.replace(before, after)
        doc = type(doc).model_validate_json(doc_json)
        record = type(record).model_validate_json(record_json)
        doc.source_file = record.source_file = f"plan{index}.pdf"
        doc.sha256 = record.source_sha256 = sha256(doc.pages[0].text.encode()).hexdigest()
        if index == 2:
            record.candidate.rules[-1].amount = "12"
        documents[doc.source_file] = doc
        records.append(record)
        plans.append(compile_scenario(record, doc, scope))
    report = {"lesson": "10_general_rule_comparison", "status": "unreviewed_scenario_preview",
              "synthetic_usage": True, "scope": scope.model_dump(mode="json"),
              "usage": usage.model_dump(mode="json"), "plans": [p.model_dump(mode="json") for p in plans],
              "source_records": [r.model_dump(mode="json") for r in records],
              "comparison": compare_compiled(usage, plans), "review_decisions": []}
    return report, documents


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.report, self.documents = example_report()

    def context(self, preferences=None):
        with patch("electricity_optimizer.insight_context.read_pdf", side_effect=lambda p, **kw: self.documents[p.name]):
            return build_insight_context(self.report, Path("contracts"), preferences or InsightPreferences())

    def test_calculated_facts_and_offline_draft(self):
        context = self.context()
        self.assertIn("$240.00", context["comparison"]["explanation"])
        self.assertTrue(context["synthetic_usage"])
        self.assertEqual(context["review_status"], "unreviewed_scenario_preview")
        result = build_insight_workflow().invoke({"context": context})
        self.assertEqual(result["route"], "draft_for_human_review")
        self.assertFalse(result["issues"])
        self.assertFalse(context["approved_for_real_plan_recommendation"])

    def test_changed_total_compiled_rate_and_pdf_are_rejected(self):
        self.report["comparison"]["results"][0]["annual_subtotal_usd"] = "1.00"
        with self.assertRaisesRegex(ValueError, "recalculated"):
            self.context()
        self.setUp()
        self.report["plans"][0]["energy_usd_per_kwh"] = "0.01"
        with self.assertRaisesRegex(ValueError, "Compiled values"):
            self.context()
        self.setUp()
        self.documents["plan1.pdf"].sha256 = "changed"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.context()

    def test_stale_review_is_not_promoted(self):
        self.report["status"] = "reviewed_scenario_subtotals"
        self.report["review_decisions"] = [{"source_file": "plan1.pdf", "status": "reviewed_for_this_scenario",
            "reviewer": "PRIVATE REVIEWER NAME", "review_date": "2026-09-01", "review_fingerprint": "stale"}]
        context = self.context()
        self.assertEqual(context["review_status"], "unreviewed_scenario_preview")
        self.assertTrue(context["review_warnings"])
        self.assertNotIn("PRIVATE REVIEWER NAME", json.dumps(context))

    def test_preferences_do_not_change_costs_and_no_match_is_explicit(self):
        baseline = self.context()
        limited = self.context(InsightPreferences(priority="modeled_cost", max_contract_months=12))
        self.assertEqual(baseline["comparison"], limited["comparison"])
        text = next(f["text"] for f in limited["facts"] if f["id"] == "preferences")
        self.assertIn("Short Plan", text)
        self.assertNotIn("Long Plan", text)
        none = self.context(InsightPreferences(max_contract_months=6))
        self.assertIn("No compiled plan", next(f["text"] for f in none["facts"] if f["id"] == "preferences"))

    def test_tie_and_singleton_handling(self):
        # Rebuild the second plan and its source evidence at the same energy price.
        raw = json.dumps(self.report["source_records"][1]).replace("12 cents", "10 cents")
        self.report["source_records"][1] = json.loads(raw)
        self.report["source_records"][1]["candidate"]["rules"][-1]["amount"] = "10"
        doc = self.documents["plan2.pdf"]
        doc.pages[0].text = doc.pages[0].text.replace("12 cents", "10 cents")
        doc.sha256 = sha256(doc.pages[0].text.encode()).hexdigest()
        self.report["source_records"][1]["source_sha256"] = doc.sha256
        from electricity_optimizer.pricing_extraction import PricingRecord
        from electricity_optimizer.rule_compiler import CompiledScenarioPlan
        record = PricingRecord.model_validate(self.report["source_records"][1])
        plan = compile_scenario(record, doc, ComparisonScope.model_validate(self.report["scope"]))
        self.report["plans"][1] = plan.model_dump(mode="json")
        usage = UsageYear.model_validate(self.report["usage"])
        self.report["comparison"] = compare_compiled(usage, [CompiledScenarioPlan.model_validate(p) for p in self.report["plans"]])
        context = self.context()
        self.assertIn("Long Plan, Short Plan", context["comparison"]["explanation"])
        self.report["plans"] = self.report["plans"][:1]
        self.report["comparison"] = compare_compiled(usage, [CompiledScenarioPlan.model_validate(self.report["plans"][0])])
        context = self.context()
        self.assertEqual(build_insight_workflow().invoke({"context": context})["route"], "needs_comparable_plans")
        with self.assertRaisesRegex(ValueError, "At least two"):
            generate_insights(context)


class DraftTests(unittest.TestCase):
    def setUp(self):
        fixture = ContextTests()
        fixture.setUp()
        self.context = fixture.context()
        self.draft = offline_draft(self.context)

    def test_unknown_reference_invented_amount_and_overconfident_claim(self):
        self.draft.explanation[0].fact_ids = ["invented"]
        self.assertIn("Unknown evidence", validate_insights(self.draft, self.context)[0]["message"])
        self.draft.explanation[0].fact_ids = ["comparison"]
        self.draft.explanation[0].text = "You receive guaranteed savings of USD 999999.99."
        issues = validate_insights(self.draft, self.context)
        self.assertTrue(any("Numbers absent" in i["message"] for i in issues))
        self.assertTrue(any("Overconfident" in i["message"] for i in issues))

    def test_replay_matching_and_changed_preferences(self):
        record = build_insight_workflow().invoke({"context": self.context})["record"]
        with TemporaryDirectory() as tmp:
            path = save_insight_record(record, Path(tmp))
            loaded = load_insight_record(path, self.context)
            with patch("openai.resources.responses.responses.Responses.parse", side_effect=AssertionError("No API")):
                result = build_insight_workflow("replay").invoke({"context": self.context, "record": loaded})
            self.assertEqual(result["record"], record)
            changed = deepcopy(self.context)
            changed["preferences"]["priority"] = "modeled_cost"
            with self.assertRaisesRegex(ValueError, "do not match"):
                load_insight_record(path, changed)

    def call_api(self, content, status="completed"):
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-5")
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertNotIn("reviewer", payload["input"][1]["content"])
            return httpx.Response(200, json={"id": "resp_test", "object": "response", "created_at": 0,
                "status": status, "model": "gpt-5", "output": [{"id": "msg_test", "type": "message",
                "role": "assistant", "status": "completed", "content": content}]})
        with OpenAI(api_key="offline-test", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
            return generate_insights(self.context, client=client)

    def test_real_sdk_parses_and_live_graph_flags_invalid_draft(self):
        record = self.call_api([{"type": "output_text", "text": self.draft.model_dump_json(), "annotations": []}])
        self.assertEqual(record.context_fingerprint, fingerprint(self.context))
        self.assertEqual(record.origin, "live")
        record.draft.explanation[0].fact_ids = ["invented"]
        result = build_insight_workflow("live", generator=lambda context, **kw: record).invoke({"context": self.context})
        self.assertEqual(result["route"], "needs_output_review")

    def test_refusal_incomplete_malformed_and_missing_key(self):
        with self.assertRaisesRegex(ExtractionError, "refused"):
            self.call_api([{"type": "refusal", "refusal": "test"}])
        with self.assertRaises(ExtractionError):
            self.call_api([], "incomplete")
        with self.assertRaises(ExtractionError):
            self.call_api([{"type": "output_text", "text": "{}", "annotations": []}])
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ExtractionError):
                generate_insights(self.context)
