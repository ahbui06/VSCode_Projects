"""Provider-independent extraction candidates, not executable billing instructions."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from .agreements import Citation, ContractTerm, ReviewIssue, StrictModel
from .extraction import citation_matches
from .models import PDFDocument

SCHEMA_VERSION = "pricing-candidate-v1"
Number = Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
Component = Literal["energy", "base", "delivery", "credit", "minimum_charge", "demand", "tax", "termination", "other"]
Unit = Literal["currency_per_kwh", "cents_per_kwh", "currency_per_month", "currency_per_day",
               "currency_per_billing_cycle", "currency_per_kw", "currency", "percent", "unknown"]
RECURRING_COMPONENTS = {"energy", "base", "delivery", "credit", "minimum_charge", "demand"}


class PlanIdentity(StrictModel):
    provider: ContractTerm
    plan_name: ContractTerm
    country: ContractTerm
    territory: ContractTerm
    currency: ContractTerm
    customer_type: ContractTerm
    document_date: ContractTerm
    contract_length: ContractTerm
    renewal_terms: ContractTerm
    termination_terms: ContractTerm


class ComponentCoverage(StrictModel):
    component: Component
    status: Literal["present", "explicit_none", "not_stated", "ambiguous"]
    explanation: str
    citations: list[Citation]


class UsageBand(StrictModel):
    lower_kwh: Number | None
    upper_kwh: Number | None
    lower_inclusive: bool | None
    upper_inclusive: bool | None
    amount: Number | None
    unit: Unit
    citations: list[Citation]


class PricingRule(StrictModel):
    label: str
    component: Component
    kind: Literal["flat_per_kwh", "fixed", "tiered", "time_of_use", "usage_credit",
                  "minimum_charge", "indexed", "demand", "other"]
    status: Literal["found", "ambiguous"]
    amount: Number | None = Field(description="Original numeric amount, as a decimal string; do not convert cents.")
    unit: Unit
    lower_kwh: Number | None
    upper_kwh: Number | None
    lower_inclusive: bool | None
    upper_inclusive: bool | None
    bands: list[UsageBand]
    tier_method: Literal["incremental", "whole_usage", "unknown"] | None
    time_window: str | None = Field(description="Preserve hours, weekdays, seasons and timezone if given.")
    conditions: str | None = Field(description="Preserve exceptions, pass-through changes, eligibility and application order; never executable code.")
    citations: list[Citation]


class PricingCandidate(StrictModel):
    identity: PlanIdentity
    coverage: list[ComponentCoverage] = Field(description="One entry for every component, including missing components.")
    rules: list[PricingRule]
    unresolved_terms: list[str]
    supporting_documents_needed: list[str]


def normalized_kwh_rate(rule: PricingRule) -> Decimal:
    """Unit conversion only, not proof that a rule is correctly interpreted."""
    if rule.amount is None:
        raise ValueError("Missing amount is not zero.")
    if rule.unit == "cents_per_kwh":
        return Decimal(rule.amount) / Decimal("100")
    if rule.unit == "currency_per_kwh":
        return Decimal(rule.amount)
    raise ValueError("This rule is not a per-kWh rate.")


def validate_pricing(candidate: PricingCandidate, document: PDFDocument) -> list[ReviewIssue]:
    """Check source grounding and structural consistency; not full semantic entailment."""
    issues = []
    pages = {p.page_number: p for p in document.pages}

    def add(field, message, severity="error"):
        issues.append(ReviewIssue(field=field, severity=severity, message=message))

    def citations(field, values, required=True):
        if required and not values:
            add(field, "Supporting citation is missing.")
        for cite in values:
            if cite.page_number not in pages:
                add(field, f"Page {cite.page_number} does not exist.")
            elif not citation_matches(cite.quote, pages[cite.page_number]):
                add(field, f"Quote not found on page {cite.page_number}.")

    for name in PlanIdentity.model_fields:
        term = getattr(candidate.identity, name)
        if term.status == "not_stated":
            if term.value is not None or term.citations:
                add(name, "Not-stated fields require null value and no citations.")
        elif not term.value or not term.value.strip():
            add(name, "A stated term requires a value.")
        citations(name, term.citations, term.status != "not_stated")
    coverage = {}
    for entry in candidate.coverage:
        if entry.component in coverage:
            add(entry.component, "Duplicate component coverage.")
        coverage[entry.component] = entry
        citations(entry.component, entry.citations, entry.status != "not_stated")
        if entry.status == "not_stated" and entry.citations:
            add(entry.component, "Not-stated coverage must not contain citations; use ambiguous when appropriate.")
        rules = [r for r in candidate.rules if r.component == entry.component]
        if entry.status == "present" and not rules:
            add(entry.component, "Present component has no extracted rule.")
        if entry.status in {"explicit_none", "not_stated"} and rules:
            add(entry.component, "Coverage conflicts with an extracted rule.")
    for component in (*sorted(RECURRING_COMPONENTS), "tax", "termination", "other"):
        if component not in coverage:
            add(component, "Coverage entry missing; report unknowns explicitly.")
    for index, rule in enumerate(candidate.rules):
        field = f"rules[{index}] {rule.label}"
        citations(field, rule.citations)
        if rule.kind in {"flat_per_kwh", "fixed", "usage_credit", "minimum_charge", "demand"} and rule.amount is None:
            add(field, "Numeric amount is missing.")
        if rule.kind == "flat_per_kwh" and rule.unit not in {"currency_per_kwh", "cents_per_kwh"}:
            add(field, "A flat per-kWh rule needs per-kWh units.")
        if rule.kind == "tiered" and not rule.bands:
            add(field, "Tiered pricing needs usage bands.")
        if rule.kind == "time_of_use" and not rule.time_window:
            add(field, "Time-of-use pricing needs its time window.")
        for band in [rule, *rule.bands]:
            if isinstance(band, UsageBand):
                citations(field + " band", band.citations)
                if band.amount is None or band.unit == "unknown":
                    add(field, "Band amount or unit is missing.")
            if band.lower_kwh is not None and Decimal(band.lower_kwh) < 0:
                add(field, "Usage boundary cannot be negative.")
            if band.upper_kwh is not None and Decimal(band.upper_kwh) < 0:
                add(field, "Usage boundary cannot be negative.")
            if band.lower_kwh is not None and band.upper_kwh is not None and Decimal(band.lower_kwh) >= Decimal(band.upper_kwh):
                add(field, "Usage boundaries must increase.")
            if band.lower_kwh is not None and band.lower_inclusive is None:
                add(field, "Lower boundary inclusivity is unknown.")
            if band.upper_kwh is not None and band.upper_inclusive is None:
                add(field, "Upper boundary inclusivity is unknown.")
    for page in document.pages:
        if page.needs_review:
            add("source", f"Page {page.page_number} has sparse text; inspect or add OCR.")
        if page.layout_warning:
            add("source", f"Page {page.page_number}: {page.layout_warning}", "warning")
    return issues


def assess_pricing(candidate: PricingCandidate, document: PDFDocument) -> dict:
    """Route work for later lessons. No route authorizes automatic billing/ranking."""
    issues = validate_pricing(candidate, document)
    missing = []
    for name in ("provider", "plan_name", "country", "territory", "currency", "customer_type", "document_date"):
        if getattr(candidate.identity, name).status != "found":
            missing.append(f"Resolve identity.{name} before grouping plans.")
    for entry in candidate.coverage:
        if entry.component in RECURRING_COMPONENTS and entry.status in {"not_stated", "ambiguous"}:
            missing.append(f"Resolve {entry.component}: {entry.explanation}")
    for rule in candidate.rules:
        if rule.status == "ambiguous" or rule.unit == "unknown":
            missing.append(f"Resolve rule: {rule.label}.")
    missing.extend(candidate.unresolved_terms)
    missing.extend(f"Supporting document: {name}" for name in candidate.supporting_documents_needed)
    engine_work = []
    for rule in candidate.rules:
        if rule.kind not in {"flat_per_kwh", "fixed", "usage_credit"}:
            engine_work.append(f"{rule.label}: {rule.kind} needs additional calculation logic.")
        if rule.kind in {"time_of_use", "demand"}:
            engine_work.append(f"{rule.label}: monthly kWh alone is insufficient; obtain interval/time-band or demand data.")
        if rule.unit == "currency_per_day":
            engine_work.append(f"{rule.label}: daily charges need actual billing dates/day counts.")
    if any(i.severity == "error" for i in issues):
        route = "needs_evidence_review"
    elif missing:
        route = "needs_information"
    elif engine_work:
        route = "needs_pricing_engine"
    else:
        route = "candidate_for_pricing_review"
    return {"route": route, "approved_for_comparison": False,
            "issues": [i.model_dump() for i in issues], "missing_information": missing,
            "engine_work": engine_work,
            "next_step": "Review amounts, units, exceptions and completeness, then connect a supported calculator. Quote matches alone do not prove interpretation."}
