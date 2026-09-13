from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class UsageMonth(Model):
    month: date
    kwh: float = Field(ge=0)


class UsageHistory(Model):
    months: list[UsageMonth] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def consecutive_months(self):
        serials = sorted(m.month.year * 12 + m.month.month for m in self.months)
        if any(b - a != 1 for a, b in zip(serials, serials[1:])):
            raise ValueError("Supply exactly 12 distinct, consecutive calendar months")
        self.months.sort(key=lambda m: m.month)
        return self


class Evidence(Model):
    field: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class PlanTerms(Model):
    provider: str
    plan_name: str
    pricing_type: Literal["fixed", "variable", "time_of_use", "tiered", "unknown"]
    currency: Literal["USD", "other"]
    term_months: int | None = Field(ge=1)
    energy_cents_per_kwh: float | None = Field(ge=0)
    delivery_cents_per_kwh: float | None = Field(ge=0)
    monthly_base_usd: float | None = Field(ge=0)
    monthly_delivery_usd: float | None = Field(ge=0)
    credit_usd: float | None = Field(ge=0)
    credit_min_kwh: float | None = Field(ge=0)
    credit_max_kwh: float | None = Field(ge=0)
    early_termination_usd: float | None = Field(ge=0)
    renewable_percent: float | None = Field(ge=0, le=100)
    renewal_terms: str | None
    unresolved_terms: list[str]
    evidence: list[Evidence]

    @model_validator(mode="after")
    def credit_range(self):
        if self.credit_usd and self.credit_min_kwh is None:
            raise ValueError("A bill credit requires its minimum usage threshold")
        if (self.credit_max_kwh is not None and self.credit_min_kwh is not None
                and self.credit_max_kwh < self.credit_min_kwh):
            raise ValueError("Invalid credit usage range")
        return self


class ProviderConfig(Model):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    company: str = Field(min_length=1)
    contract_path: str


class Preferences(Model):
    max_term_months: int = Field(default=36, ge=12)
    minimum_renewable_percent: float = Field(default=0, ge=0, le=100)
    switching_cost_usd: float = Field(default=0, ge=0)


class MonthlyCost(Model):
    month: date
    kwh: float
    cost_usd: float


class Estimate(Model):
    provider_id: str
    plan_name: str
    monthly: list[MonthlyCost]
    annual_usd: float
    first_year_usd: float
    effective_cents_per_kwh: float | None


class ProviderResult(Model):
    provider_id: str
    terms: PlanTerms | None
    pages: list[str]
    issues: list[str]


class Review(Model):
    provider_id: str
    approved: bool
    issues: list[str]


class SupervisorNotes(Model):
    reviews: list[Review]
    negotiation_questions: list[str]


class Report(Model):
    mode: Literal["demo", "live"]
    reviews: list[Review]
    ranking: list[Estimate]
    recommended_provider_id: str | None
    negotiation_questions: list[str]
    limitations: list[str]
