"""Source-backed demonstration adapter for Reliant Power Savings EFL layouts.

Not a general contract parser or an approval of complete billing terms.
"""
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field

from .models import PDFDocument
from .pricing import MonthlyBill, calculate_month
from .usage import UsageYear


class SourceValue(BaseModel):
    value: str
    page_number: int
    quote: str


class EFLPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file: str
    source_sha256: str
    evidence: dict[str, SourceValue]
    name: str
    market: str
    document_date: str
    currency: str = "USD"
    energy_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    base_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_min_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    contract_months: int = Field(ge=12)
    termination_usd: Decimal = Field(ge=0, allow_inf_nan=False)


def parse_power_savings(document: PDFDocument) -> EFLPlan:
    """Read labeled values directly from the PDF; reject missing/conflicting matches."""
    evidence = {}

    def find(name, pattern, group=1, cents=False):
        hits = []
        for page in document.pages:
            for text in [page.text, *(c.text for c in page.table_cells)]:
                text = re.sub(r"\s+", " ", text)
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    value = match.group(group).replace(",", "") if name not in {"name", "market"} else match.group(group)
                    if cents:
                        value = str(Decimal(value) / 100)
                    hits.append(SourceValue(value=value, page_number=page.page_number, quote=match.group(0)))
        if len({h.value for h in hits}) != 1:
            raise ValueError(f"{document.source_file}: {name} missing or conflicting; inspect the source.")
        evidence[name] = hits[0]
        return hits[0].value

    name = find("name", r"(Reliant Power Savings 2,000 kWh (?:12|24) plan)")
    market = find("market", r"(AEP Texas Central) service area")
    date = find("document_date", r"Date:\s*(\d{2}/\d{2}/\d{4})")
    energy = find("energy_usd_per_kwh", r"Energy Charge:\s*([\d.]+)\s*¢\s*per kWh", cents=True)
    base = find("base_usd_per_month", r"Base Charge:\s*\$([\d.]+)\s*per billing cycle")
    delivery_pattern = r"AEP Texas Central Delivery Charges:\s*\$([\d.]+) per billing cycle and ([\d.]+)\s*¢ per kWh"
    delivery_base = find("delivery_usd_per_month", delivery_pattern)
    delivery_rate = find("delivery_usd_per_kwh", delivery_pattern, group=2, cents=True)
    credit_pattern = r"A Usage Credit of \$([\d.]+) will be included for each billing cycle when your usage on this plan is above or equal to ([\d,]+) kWh"
    credit = find("credit_usd", credit_pattern)
    threshold = find("credit_min_kwh", credit_pattern, group=2)
    term = find("contract_months", r"Contract Term\s+(\d+) months")
    termination = find("termination_usd", r"Yes\. \$([\d.]+)\. Applies through the end of the contract term\.")
    return EFLPlan(source_file=document.source_file, source_sha256=document.sha256,
        evidence=evidence, name=name, market=market, document_date=date,
        energy_usd_per_kwh=energy, base_usd_per_month=base,
        delivery_usd_per_month=delivery_base, delivery_usd_per_kwh=delivery_rate,
        credit_usd=credit, credit_min_kwh=threshold, contract_months=int(term), termination_usd=termination)


class EFLComparison(BaseModel):
    plan: EFLPlan
    bills: list[MonthlyBill]
    annual_usd: Decimal


def compare_efls(usage: UsageYear, plans: list[EFLPlan]) -> list[EFLComparison]:
    if len(plans) < 2 or len({p.name for p in plans}) != len(plans):
        raise ValueError("Provide at least two distinct plans.")
    if len({(p.market, p.currency, p.document_date) for p in plans}) != 1:
        raise ValueError("This lesson requires the same territory, currency and EFL date.")
    results = []
    for plan in plans:
        bills = [calculate_month(month, plan) for month in usage.months]
        results.append(EFLComparison(plan=plan, bills=bills,
            annual_usd=sum((b.total_usd for b in bills), Decimal("0.00"))))
    return sorted(results, key=lambda result: (result.annual_usd, result.plan.name))
