import unittest
from decimal import Decimal

from electricity_optimizer.comparison_workflow import build_comparison_workflow


def inputs():
    plan = dict(name="Fictional A", energy_usd_per_kwh="0.10", base_usd_per_month="0",
        delivery_usd_per_kwh="0", delivery_usd_per_month="0", credit_usd="0", credit_min_kwh=None)
    return {"synthetic": True,
        "usage": {"months": [{"month": f"2025-{m:02d}", "kwh": "1000"} for m in range(1, 13)]},
        "plans": [plan, plan | {"name": "Fictional B", "energy_usd_per_kwh": "0.12"}]}


class ComparisonWorkflowTests(unittest.TestCase):
    def test_calculation_and_explanation(self):
        state = build_comparison_workflow().invoke({"inputs": inputs()})
        self.assertEqual(state["status"], "comparison_complete")
        self.assertEqual(state["results"][0].annual_usd, Decimal("1200.00"))
        self.assertIn("$240.00 less", state["explanation"])
        self.assertEqual(state["trace"], ["validate_inputs", "calculate_costs", "explain_results"])

    def test_tie(self):
        raw = inputs()
        raw["plans"][1]["energy_usd_per_kwh"] = "0.10"
        state = build_comparison_workflow().invoke({"inputs": raw})
        self.assertIn("Tie:", state["explanation"])
        self.assertNotIn("less than", state["explanation"])

    def test_invalid_usage_and_non_demo_input_stop(self):
        for raw in [inputs() | {"synthetic": False}, inputs() | {"usage": {"months": []}}]:
            state = build_comparison_workflow().invoke({"inputs": raw})
            self.assertEqual(state["trace"], ["validate_inputs", "failed"])
            self.assertIsNone(state["explanation"])

    def test_rerun_clears_old_results(self):
        graph = build_comparison_workflow()
        state = graph.invoke({"inputs": inputs()})
        state["inputs"] = inputs() | {"plans": []}
        state = graph.invoke(state)
        self.assertEqual(state["results"], [])
        self.assertIsNone(state["explanation"])
