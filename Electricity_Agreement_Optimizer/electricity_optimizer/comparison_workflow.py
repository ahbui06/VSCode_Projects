"""A local comparison graph for explicitly fictional plans and usage."""

from decimal import Decimal
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .pricing import DemoPlan, PlanComparison, compare_plans
from .usage import UsageYear


class ComparisonState(TypedDict, total=False):
    inputs: dict
    usage: UsageYear | None
    plans: list[DemoPlan]
    results: list[PlanComparison]
    explanation: str | None
    error: str | None
    status: str
    trace: list[str]


def explain_results(results: list[PlanComparison]) -> str:
    """Generate prose only from computed values; ties are not arbitrary winners."""
    if len(results) < 2:
        raise ValueError("An explanation requires at least two plans.")
    ordered = sorted(results, key=lambda r: (r.annual_usd, r.plan.name))
    minimum = ordered[0].annual_usd
    winners = [r.plan.name for r in ordered if r.annual_usd == minimum]
    lines = ["Synthetic teaching comparison only; not a recommendation for a real household."]
    if len(winners) > 1:
        lines.append(f"Tie: {', '.join(winners)} each cost ${minimum:,.2f} for the supplied year.")
    else:
        difference = ordered[1].annual_usd - minimum
        lines.append(f"{winners[0]} has the lowest annual cost at ${minimum:,.2f}, "
                     f"${difference:,.2f} less than the next cheapest plan, {ordered[1].plan.name}.")
    for result in ordered:
        months = [b.month for b in result.bills if b.credit_usd > 0]
        credits = sum((b.credit_usd for b in result.bills), Decimal("0.00"))
        lines.append(f"{result.plan.name}: ${result.annual_usd:,.2f} annually; "
                     f"${credits:,.2f} in credits across {len(months)} months "
                     f"({', '.join(months) if months else 'none'}).")
    lines.append("Totals include energy, base and delivery charges, less credits. "
                 "Taxes and switching fees are excluded. Rates are fixed for all 12 months; "
                 "components round to cents half up and credits cannot exceed the monthly subtotal. "
                 "Different usage can change the ranking.")
    return "\n\n".join(lines)


def build_comparison_workflow():
    def update(state, node, **changes):
        return {"trace": [*state.get("trace", []), node], **changes}

    def validate_inputs(state):
        fresh = dict(usage=None, plans=[], results=[], explanation=None, error=None,
                     status="validating", trace=["validate_inputs"])
        try:
            raw = state["inputs"]
            if raw.get("synthetic") is not True:
                raise ValueError("This lesson only accepts explicitly synthetic inputs.")
            usage = UsageYear.model_validate(raw["usage"])
            plans = [DemoPlan.model_validate(p) for p in raw["plans"]]
            if len(plans) < 2 or len({p.name for p in plans}) != len(plans):
                raise ValueError("Provide at least two fictional plans with unique names.")
            fresh.update(usage=usage, plans=plans, status="validated")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            fresh.update(error=f"Invalid comparison inputs ({type(error).__name__}): {error}")
        return fresh

    def calculate_costs(state):
        results = compare_plans(state["usage"], state["plans"])
        return update(state, "calculate_costs", results=results, status="calculated")

    def explain(state):
        return update(state, "explain_results", explanation=explain_results(state["results"]),
                      status="comparison_complete")

    def failed(state):
        return update(state, "failed", status="failed", results=[], explanation=None)

    def route(state) -> Literal["calculate_costs", "failed"]:
        return "failed" if state["error"] else "calculate_costs"

    builder = StateGraph(ComparisonState)
    builder.add_node("validate_inputs", validate_inputs)
    builder.add_node("calculate_costs", calculate_costs)
    builder.add_node("explain_results", explain)
    builder.add_node("failed", failed)
    builder.add_edge(START, "validate_inputs")
    builder.add_conditional_edges("validate_inputs", route)
    builder.add_edge("calculate_costs", "explain_results")
    builder.add_edge("explain_results", END)
    builder.add_edge("failed", END)
    return builder.compile()
