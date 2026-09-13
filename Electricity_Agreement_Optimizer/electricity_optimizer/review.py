"""Human-reviewed boundary for a narrow fixed-rate, no-credit pricing model."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .extraction import citation_matches
from .models import PDFDocument


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1)


class ReviewedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_on: str | None = None


class PricingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file: str
    source_sha256: str
    plan_name: ReviewedValue = Field(default_factory=ReviewedValue)
    territory: ReviewedValue = Field(default_factory=ReviewedValue)
    currency: ReviewedValue = Field(default_factory=ReviewedValue)
    energy_usd_per_kwh: ReviewedValue = Field(default_factory=ReviewedValue)
    base_usd_per_month: ReviewedValue = Field(default_factory=ReviewedValue)
    delivery_usd_per_kwh: ReviewedValue = Field(default_factory=ReviewedValue)
    delivery_usd_per_month: ReviewedValue = Field(default_factory=ReviewedValue)
    # This lesson only supports flat rates with no credits, tiers or minimum bills.
    pricing_structure: ReviewedValue = Field(default_factory=ReviewedValue)
    # Scope is an explicit hypothetical calculation, not a historical tariff forecast.
    accept_scenario_assumptions: bool = False


class ReviewedFixedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    market: str
    currency: Literal["USD"] = "USD"
    fictional: Literal[False] = False
    source_sha256: str
    energy_usd_per_kwh: Decimal
    base_usd_per_month: Decimal
    delivery_usd_per_kwh: Decimal
    delivery_usd_per_month: Decimal
    credit_usd: Decimal = Decimal("0")
    credit_min_kwh: None = None


SCENARIO_ASSUMPTIONS = (
    "Hypothetical 12-month scenario with constant reviewed rates; not a current offer or forecast. "
    "Energy, base and delivery only; taxes, switching/termination charges and deposits excluded. "
    "Round each component to cents half up. No tiers, time-of-use, credits or minimum bills."
)
NUMERIC_FIELDS = ("energy_usd_per_kwh", "base_usd_per_month",
                  "delivery_usd_per_kwh", "delivery_usd_per_month")
SUPPORTED_STRUCTURE = "flat_no_credits_no_tiers_no_minimum_bill"


def review_blockers(review: PricingReview, documents: list[PDFDocument]) -> list[str]:
    from datetime import date
    sources = {d.sha256: d for d in documents}
    blockers = []
    source = sources.get(review.source_sha256)
    if source is None or source.source_file != review.source_file:
        blockers.append("Primary agreement does not match the supplied source.")
    for name in PricingReview.model_fields:
        item = getattr(review, name)
        if not isinstance(item, ReviewedValue):
            continue
        if item.value is None or not item.value.strip():
            blockers.append(f"{name}: missing value.")
        if not item.reviewer or not item.reviewer.strip():
            blockers.append(f"{name}: human review not recorded.")
        try:
            date.fromisoformat(item.reviewed_on or "")
        except ValueError:
            blockers.append(f"{name}: record review date as YYYY-MM-DD.")
        if not item.evidence:
            blockers.append(f"{name}: source evidence missing (including for zero charges).")
        for citation in item.evidence:
            doc = sources.get(citation.source_sha256)
            page = next((p for p in doc.pages if p.page_number == citation.page_number), None) if doc else None
            if page is None or not citation_matches(citation.quote, page):
                blockers.append(f"{name}: evidence does not match supplied source/page.")
        if name in NUMERIC_FIELDS and item.value is not None:
            try:
                amount = Decimal(item.value)
                if not amount.is_finite() or amount < 0:
                    raise ValueError()
            except (ValueError, ArithmeticError):
                blockers.append(f"{name}: enter a finite nonnegative number in the stated units.")
    if review.currency.value != "USD":
        blockers.append("Only USD is supported in this lesson.")
    if review.pricing_structure.value != SUPPORTED_STRUCTURE:
        blockers.append("Confirm the supported flat-rate structure; other pricing rules require a different engine.")
    if not review.accept_scenario_assumptions:
        blockers.append("Scenario scope and rounding assumptions have not been accepted.")
    return blockers


def compile_reviewed_plan(review: PricingReview, documents: list[PDFDocument]) -> ReviewedFixedPlan:
    blockers = review_blockers(review, documents)
    if blockers:
        raise ValueError("Calculation blocked:\n" + "\n".join(blockers))
    return ReviewedFixedPlan(name=review.plan_name.value, market=review.territory.value,
        source_sha256=review.source_sha256,
        **{name: Decimal(getattr(review, name).value) for name in NUMERIC_FIELDS})
