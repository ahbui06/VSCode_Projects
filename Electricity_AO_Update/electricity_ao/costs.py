from decimal import Decimal, ROUND_HALF_UP

from .models import Estimate, MonthlyCost, PlanTerms, Preferences, UsageHistory

PRICING_FIELDS = (
    "pricing_type", "currency", "term_months", "energy_cents_per_kwh",
    "delivery_cents_per_kwh", "monthly_base_usd", "monthly_delivery_usd",
)


def eligibility_issues(plan: PlanTerms, preferences: Preferences) -> list[str]:
    # The specialist records disclosures and ambiguities here; the independent
    # supervisor decides whether they block the estimate. Deterministic pricing
    # requirements below remain hard failures.
    issues = []
    if plan.pricing_type != "fixed" or plan.currency != "USD":
        issues.append("Only fixed USD pricing is supported")
    for field in PRICING_FIELDS:
        if getattr(plan, field) is None:
            issues.append(f"Missing required term: {field}")
    if plan.term_months is not None and not 12 <= plan.term_months <= preferences.max_term_months:
        issues.append("Term must cover 12 months and satisfy the maximum term preference")
    if preferences.minimum_renewable_percent > 0:
        if plan.renewable_percent is None or plan.renewable_percent < preferences.minimum_renewable_percent:
            issues.append("Renewable preference is not met or verified")
    return issues


def estimate(provider_id: str, plan: PlanTerms, usage: UsageHistory, preferences: Preferences) -> Estimate:
    issues = eligibility_issues(plan, preferences)
    if issues:
        raise ValueError("; ".join(issues))
    d = lambda value: Decimal(str(value))
    money = lambda value: value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    monthly = []
    for row in usage.months:
        charge = (d(plan.energy_cents_per_kwh) + d(plan.delivery_cents_per_kwh)) * d(row.kwh) / 100
        charge += d(plan.monthly_base_usd) + d(plan.monthly_delivery_usd)
        if plan.credit_usd and row.kwh >= plan.credit_min_kwh:
            if plan.credit_max_kwh is None or row.kwh <= plan.credit_max_kwh:
                charge -= d(plan.credit_usd)
        if charge < 0:
            raise ValueError("Negative bill requires explicit credit carryover rules; manual review needed")
        monthly.append(MonthlyCost(month=row.month, kwh=row.kwh, cost_usd=float(money(charge))))
    annual = sum((d(row.cost_usd) for row in monthly), Decimal(0))
    kwh = sum(d(row.kwh) for row in usage.months)
    return Estimate(
        provider_id=provider_id, plan_name=plan.plan_name, monthly=monthly,
        annual_usd=float(annual), first_year_usd=float(money(annual + d(preferences.switching_cost_usd))),
        effective_cents_per_kwh=float(annual / kwh * 100) if kwh else None,
    )
