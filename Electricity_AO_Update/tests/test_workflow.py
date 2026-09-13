from pathlib import Path

import pytest
from pydantic import ValidationError

from electricity_ao.costs import estimate
from electricity_ao.demo import create_demo, demo_terms
from electricity_ao.documents import load_usage, read_pdf
from electricity_ao.models import Preferences, UsageHistory
from electricity_ao.workflow import build_graph

ROOT = Path(__file__).resolve().parents[1]


def test_monthly_credit_and_totals():
    usage = load_usage(ROOT / "data/usage_example.csv")
    plan = demo_terms("Test", 10.5, 30)
    result = estimate("test", plan, usage, Preferences(switching_cost_usd=75))
    # Exactly 1,000 kWh qualifies; 750 does not.
    assert result.monthly[1].cost_usd == 134.5
    assert result.monthly[2].cost_usd == 125.75
    # 13,400 kWh * $0.155 + 12 * $9.50 - 6 * $30.
    assert result.annual_usd == 2011.0
    assert result.first_year_usd == 2086.0


def test_usage_requires_consecutive_unique_months():
    usage = load_usage(ROOT / "data/usage_example.csv").model_dump()
    usage["months"][1] = usage["months"][0]
    with pytest.raises(ValidationError):
        UsageHistory.model_validate(usage)


def test_unsupported_plan_not_calculated():
    plan = demo_terms("Test", 8)
    plan.pricing_type = "time_of_use"
    with pytest.raises(ValueError, match="fixed USD"):
        estimate("test", plan, load_usage(ROOT / "data/usage_example.csv"), Preferences())


def test_demo_pdf_graph_and_supervisor(tmp_path):
    providers, backend = create_demo(tmp_path)
    assert "FICTIONAL" in read_pdf(providers[0].contract_path)[0]
    report = build_graph(providers, backend, "demo").invoke({
        "usage": load_usage(ROOT / "data/usage_example.csv"), "preferences": Preferences(), "results": [],
    })["report"]
    assert len(report.reviews) == 3
    assert all(r.approved for r in report.reviews)
    assert report.recommended_provider_id == "prairie"
    assert report.ranking[0].annual_usd == 1923


@pytest.mark.parametrize("failure", ["provider", "evidence", "supervisor", "coverage"])
def test_failures_are_visible_and_not_ranked(tmp_path, failure):
    providers, backend = create_demo(tmp_path)
    if failure == "provider":
        providers[0].contract_path = str(tmp_path / "missing.pdf")
    elif failure == "evidence":
        backend.plans["prairie"].evidence[0].quote = "invented text"
    elif failure == "supervisor":
        def fail(*args):
            raise RuntimeError("API unavailable")
        backend.review = fail
    else:
        original = backend.review
        def incomplete(*args):
            notes = original(*args)
            notes.reviews = notes.reviews[:1]
            return notes
        backend.review = incomplete
    report = build_graph(providers, backend, "demo").invoke({
        "usage": load_usage(ROOT / "data/usage_example.csv"), "preferences": Preferences(), "results": [],
    })["report"]
    assert not next(r for r in report.reviews if r.provider_id == "prairie").approved
    if failure in ("supervisor", "coverage"):
        assert report.ranking == []
    else:
        assert len(report.ranking) == 2


def test_missing_rate_and_short_term_are_rejected():
    plan = demo_terms("Test", 8)
    plan.energy_cents_per_kwh = None
    plan.term_months = 6
    with pytest.raises(ValueError, match="Missing required term"):
        estimate("test", plan, load_usage(ROOT / "data/usage_example.csv"), Preferences())
