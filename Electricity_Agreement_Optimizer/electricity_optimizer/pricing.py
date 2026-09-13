"""Fictional fixed-rate plans for teaching; no real-provider plan conversion yet."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .usage import MonthlyUsage, UsageYear


class DemoPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    fictional: Literal[True] = True
    market: Literal["fictional-demo-market"] = "fictional-demo-market"
    currency: Literal["USD"] = "USD"
    energy_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    base_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_min_kwh: Decimal | None = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def paired_credit(self):
        if (self.credit_usd > 0) != (self.credit_min_kwh is not None):
            raise ValueError("A positive credit requires a threshold; zero credit requires null threshold.")
        return self


class MonthlyBill(BaseModel):
    month: str
    kwh: Decimal
    energy_usd: Decimal
    base_usd: Decimal
    delivery_usd: Decimal
    credit_usd: Decimal
    total_usd: Decimal


class PlanComparison(BaseModel):
    plan: DemoPlan
    bills: list[MonthlyBill]
    annual_usd: Decimal


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class FixedPricing(Protocol):
    energy_usd_per_kwh: Decimal
    base_usd_per_month: Decimal
    delivery_usd_per_kwh: Decimal
    delivery_usd_per_month: Decimal
    credit_usd: Decimal
    credit_min_kwh: Decimal | None


def calculate_month(usage: MonthlyUsage, plan: FixedPricing) -> MonthlyBill:
    energy = money(usage.kwh * plan.energy_usd_per_kwh)
    base = money(plan.base_usd_per_month)
    delivery = money(usage.kwh * plan.delivery_usd_per_kwh + plan.delivery_usd_per_month)
    subtotal = energy + base + delivery
    qualifies = plan.credit_min_kwh is not None and usage.kwh >= plan.credit_min_kwh
    # Explicit teaching assumption: credit cannot exceed the month's subtotal.
    credit = min(money(plan.credit_usd), subtotal) if qualifies else Decimal("0.00")
    return MonthlyBill(month=usage.month, kwh=usage.kwh, energy_usd=energy,
        base_usd=base, delivery_usd=delivery, credit_usd=credit,
        total_usd=subtotal - credit)


def compare_plans(usage: UsageYear, plans: list[DemoPlan]) -> list[PlanComparison]:
    if not plans or len({p.name for p in plans}) != len(plans):
        raise ValueError("Provide at least one plan, with unique names.")
    results = []
    for plan in plans:
        bills = [calculate_month(month, plan) for month in usage.months]
        results.append(PlanComparison(plan=plan, bills=bills,
            annual_usd=sum((bill.total_usd for bill in bills), Decimal("0.00"))))
    return sorted(results, key=lambda result: (result.annual_usd, result.plan.name))
