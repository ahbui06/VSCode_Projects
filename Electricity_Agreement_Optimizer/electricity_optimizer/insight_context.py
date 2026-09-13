"""Revalidate a Notebook 10 report and build facts for explanations, without an API."""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from .agreements import StrictModel
from .ingestion import read_pdf
from .pricing_extraction import PricingRecord
from .rule_compiler import (
    ComparisonScope, CompiledScenarioPlan, compile_scenario, compare_compiled, fingerprint,
)
from .usage import UsageYear


class InsightPreferences(StrictModel):
    priority: Literal["balanced", "modeled_cost", "shorter_commitment"] = "balanced"
    max_contract_months: int | None = Field(default=None, ge=1)


def build_insight_context(report: dict, contracts: Path, preferences: InsightPreferences) -> dict:
    """Recompile from source records and recalculate bills; reject changed report/PDF data."""
    if report.get("lesson") != "10_general_rule_comparison":
        raise ValueError("Select the Notebook 10 general_rule_comparison.json report.")
    if not isinstance(report.get("synthetic_usage"), bool):
        raise ValueError("The usage provenance flag is missing or invalid.")
    scope = ComparisonScope.model_validate(report["scope"])
    usage = UsageYear.model_validate(report["usage"])
    plans = [CompiledScenarioPlan.model_validate(p) for p in report["plans"]]
    records = [PricingRecord.model_validate(r) for r in report["source_records"]]
    if len({r.source_file for r in records}) != len(records):
        raise ValueError("Duplicate source records in the report.")
    by_source = {r.source_file: r for r in records}
    for plan in plans:
        if plan.scope != scope:
            raise ValueError("Compiled plan scope does not match the report scope.")
        record = by_source.get(plan.source_file)
        if record is None:
            raise ValueError("A compiled plan has no source pricing record.")
        pdf = (contracts / plan.source_file).resolve()
        if pdf.parent != contracts.resolve() or pdf.suffix.lower() != ".pdf":
            raise ValueError("Sources must be top-level PDFs in contracts/.")
        document = read_pdf(pdf, include_tables=True)
        exclusions = {e["rule_id"]: e["reason"] for e in plan.exclusions
                      if e.get("rule", {}).get("component") in {"energy", "base", "delivery", "credit"}}
        rebuilt = compile_scenario(record, document, scope, exclusions)
        if rebuilt != plan:
            raise ValueError(f"Compiled values or review fingerprint changed for {plan.source_file}. Rerun Notebook 10.")
    recalculated = compare_compiled(usage, plans)
    if recalculated != report["comparison"]:
        raise ValueError("Saved comparison differs from recalculated bills. Rerun Notebook 10.")

    review_states, review_warnings = [], []
    for plan in plans:
        decisions = [d for d in report.get("review_decisions", []) if d.get("source_file") == plan.source_file]
        reviewed = False
        if len(decisions) == 1:
            decision = decisions[0]
            try:
                date.fromisoformat(decision.get("review_date") or "")
                reviewed = (decision.get("status") == "reviewed_for_this_scenario"
                            and decision.get("review_fingerprint") == plan.review_fingerprint
                            and bool(str(decision.get("reviewer") or "").strip()))
            except (ValueError, TypeError):
                pass
            if decision.get("status") == "reviewed_for_this_scenario" and not reviewed:
                review_warnings.append(f"{plan.source_file}: incomplete or stale scenario review treated as unreviewed.")
        review_states.append({"source_file": plan.source_file, "reviewed_for_scenario": reviewed})
    all_reviewed = bool(plans) and all(r["reviewed_for_scenario"] for r in review_states)
    review_status = "reviewed_scenario_subtotals" if all_reviewed else "unreviewed_scenario_preview"
    if report.get("status") != review_status:
        review_warnings.append("Report review label differs from the current review records; effective status was recomputed.")

    facts = []
    def fact(identifier, kind, text, source=None, citations=None):
        facts.append({"id": identifier, "kind": kind, "text": text,
                      "source_file": source, "citations": citations or []})

    fact("scope", "scenario_assumption", "; ".join(scope.assumptions) +
         f" Territory: {scope.territory}. Currency assumption: {scope.currency}. Snapshot date: {scope.document_date}.")
    fact("review", "review_status", f"Effective input status: {review_status}. Scenario review is not full-contract approval or verified eligibility.")
    fact("usage", "calculated", f"{'Synthetic' if report['synthetic_usage'] else 'User-provided'} usage: "
         f"{sum(m.kwh for m in usage.months)} kWh across 12 months, {usage.months[0].month} through {usage.months[-1].month}. "
         "These monthly totals do not establish time-of-use or demand consumption.")
    fact("comparison", "calculated", recalculated["explanation"])
    summaries = []
    plan_map = {p.source_file: p for p in plans}
    for index, result in enumerate(recalculated["results"], 1):
        prefix = f"P{index}"
        plan = plan_map[result["source_file"]]
        record = by_source[plan.source_file]
        identity = record.candidate.identity
        summary = {"id": prefix, "source_file": plan.source_file, "name": plan.name,
                   "provider": plan.provider, "annual_subtotal_usd": result["annual_subtotal_usd"],
                   "contract_months": plan.contract_months}
        summaries.append(summary)
        fact(prefix + ".cost", "calculated", f"{plan.name}: modeled 12-month subtotal USD {result['annual_subtotal_usd']}; "
             f"contract commitment {plan.contract_months} months. Not the total cost of the entire commitment.", plan.source_file)
        for field in ("contract_length", "termination_terms"):
            term = getattr(identity, field)
            fact(prefix + "." + field, "source_interpretation", f"{plan.name}: {term.value or 'Not stated'}",
                 plan.source_file, [c.model_dump() for c in term.citations])
        credited = sum(Decimal(b["credit_usd"]) > 0 for b in result["bills"])
        total_credit = sum((Decimal(b["credit_usd"]) for b in result["bills"]), Decimal("0"))
        credit_cites = [c.model_dump() for r in record.candidate.rules if r.component == "credit" for c in r.citations]
        fact(prefix + ".credit", "calculated", f"{plan.name}: credit applied in {credited} of 12 modeled months; "
             f"total applied USD {total_credit:.2f}; configured monthly credit USD {plan.credit_usd}, "
             f"inclusive threshold {plan.credit_min_kwh if plan.credit_min_kwh is not None else 'not applicable'} kWh. "
             "This is an outcome for the supplied usage, not a reason to consume more electricity.", plan.source_file, credit_cites)
        for i, rule in enumerate(record.candidate.rules):
            fact(f"{prefix}.rule{i}", "source_interpretation",
                 f"{rule.label}: original amount={rule.amount}; unit={rule.unit}; status={rule.status}; "
                 f"conditions={rule.conditions}; bounds={rule.lower_kwh}, {rule.upper_kwh}.", plan.source_file,
                 [c.model_dump() for c in rule.citations])
        fact(prefix + ".limitations", "unresolved", " | ".join(plan.review_notes) +
             " | Exclusions: " + json.dumps(plan.exclusions, ensure_ascii=False), plan.source_file)

    eligible = [p for p in summaries if preferences.max_contract_months is None
                or p["contract_months"] <= preferences.max_contract_months]
    preference_text = f"User priority: {preferences.priority}; maximum contract months: {preferences.max_contract_months}. "
    if not eligible:
        preference_text += "No compiled plan satisfies this term limit. Obtain another quote; no candidate selected."
    elif len(summaries) < 2:
        preference_text += "Insufficient comparable plans for a relative recommendation."
    elif preferences.priority == "shorter_commitment":
        shortest = min(p["contract_months"] for p in eligible)
        preference_text += "Shortest-term candidate(s) to investigate: " + ", ".join(p["name"] for p in eligible if p["contract_months"] == shortest) + "."
    elif preferences.priority == "modeled_cost":
        lowest = min(Decimal(p["annual_subtotal_usd"]) for p in eligible)
        preference_text += "Lowest modeled-subtotal candidate(s) within the term limit: " + ", ".join(p["name"] for p in eligible if Decimal(p["annual_subtotal_usd"]) == lowest) + "."
    else:
        preference_text += "Compare modeled cost with commitment length; no weighted score or automatic best-fit choice is assigned."
    fact("preferences", "user_preference", preference_text)
    return {"report_fingerprint": fingerprint(report), "preferences": preferences.model_dump(mode="json"),
            "comparison": recalculated, "plan_summaries": summaries,
            "synthetic_usage": report["synthetic_usage"], "review_status": review_status,
            "review_states": review_states, "review_warnings": review_warnings,
            "facts": facts, "approved_for_real_plan_recommendation": False}


def load_insight_context(report_path: Path, contracts: Path, preferences=None) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return build_insight_context(report, contracts, preferences or InsightPreferences())
