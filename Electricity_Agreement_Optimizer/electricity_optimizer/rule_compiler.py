"""Compile a bounded subset of general pricing rules into an explicit scenario.

Amounts come from Notebook 09 records, never a provider-specific PDF parser.
Results are modeled recurring subtotals, not complete bills or eligibility advice.
"""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ingestion import read_pdf
from .pricing import calculate_month
from .pricing_extraction import PricingRecord, check_record, load_pricing_record
from .pricing_schema import normalized_kwh_rate, validate_pricing


def fingerprint(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class ComparisonScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    country: str
    territory: str
    currency: Literal["USD"] = "USD"
    customer_type: str
    document_date: str
    assumptions: tuple[str, ...] = (
        "Twelve monthly usage rows represent twelve billing cycles at unchanged snapshot rates.",
        "USD, country and customer type are scenario assumptions when not stated in the source.",
        "Standard territory only; special-area adjustments are outside this scenario.",
        "Listed delivery totals are used; any separately excluded rider is not estimated.",
        "Only energy, base, listed delivery and supported usage credit are modeled.",
        "Taxes, termination, minimum/demand charges and other fees are outside this subtotal, not assumed absent.",
        "Amounts are rounded by component to cents, half up; credit is capped at that month's subtotal.",
        "Free-text conditions are retained for review, not executed; customer eligibility is unverified.",
    )


class CompiledScenarioPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    provider: str
    source_file: str
    source_sha256: str
    record_fingerprint: str
    review_fingerprint: str
    scope: ComparisonScope
    contract_months: int
    energy_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    base_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_kwh: Decimal = Field(ge=0, allow_inf_nan=False)
    delivery_usd_per_month: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    credit_min_kwh: Decimal | None
    mappings: list[dict]
    exclusions: list[dict]
    review_notes: list[str]


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold().removesuffix(" service area")


def _date(value: str) -> str:
    value = re.sub(r"^date:\s*", "", value, flags=re.IGNORECASE).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Document date must be ISO or an unambiguous US MM/DD/YYYY date for this lesson.")


def compile_scenario(record: PricingRecord, document, scope: ComparisonScope,
                     excluded_rules: dict[str, str] | None = None) -> CompiledScenarioPlan:
    """Compile supported structures; explicit hash-bound exclusions stay in the output."""
    check_record(record, document)
    candidate = record.candidate
    issues = validate_pricing(candidate, document)
    errors = [f"{i.field}: {i.message}" for i in issues if i.severity == "error"]
    if errors:
        raise ValueError("Evidence/structure checks failed: " + "; ".join(errors))
    notes = [f"{i.field}: {i.message}" for i in issues]
    for field in ("provider", "plan_name", "territory", "document_date", "contract_length"):
        if getattr(candidate.identity, field).status != "found":
            raise ValueError(f"Resolve identity.{field} before compiling.")
    if _date(candidate.identity.document_date.value) != _date(scope.document_date):
        raise ValueError("Document snapshot date does not match the comparison scope.")
    if _normalized(candidate.identity.territory.value) != _normalized(scope.territory):
        raise ValueError("Service territory does not match the comparison scope.")
    for field in ("country", "currency", "customer_type"):
        term = getattr(candidate.identity, field)
        expected = getattr(scope, field)
        if term.status == "found":
            if _normalized(term.value) != _normalized(expected):
                raise ValueError(f"Stated {field} conflicts with scenario {expected}.")
        elif term.status == "ambiguous":
            raise ValueError(f"Resolve ambiguous {field}; a scenario cannot override a conflict.")
        else:
            notes.append(f"Scenario assumption: {field}={expected}; not stated in the PDF.")
    term_match = re.fullmatch(r"\s*(\d+)\s+months?\s*", candidate.identity.contract_length.value, re.IGNORECASE)
    if not term_match or int(term_match[1]) < 12:
        raise ValueError("A twelve-month scenario requires a supported contract term of at least twelve months.")

    coverage = {c.component: c for c in candidate.coverage}
    modeled = {"energy", "base", "delivery", "credit"}
    for component in modeled:
        if coverage[component].status not in {"present", "explicit_none"}:
            raise ValueError(f"Resolve {component} prices; missing is not zero.")
    if coverage["energy"].status != "present":
        raise ValueError("An explicit energy rule is required.")
    excluded_rules = excluded_rules or {}
    rule_ids = [fingerprint(r) for r in candidate.rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("Duplicate extracted rules need review before calculation.")
    if set(excluded_rules) - set(rule_ids):
        raise ValueError("An excluded rule fingerprint no longer matches this record; review the new extraction.")
    if any(not reason.strip() for reason in excluded_rules.values()):
        raise ValueError("Every excluded rule needs a scenario-specific reason.")
    exclusions = [{"component": c.component, "status": c.status, "explanation": c.explanation,
                   "reason": "Outside the modeled subtotal; not asserted to be zero."}
                  for c in candidate.coverage if c.component not in modeled]
    slots, mappings = {}, []
    credit_min = None
    for rule in candidate.rules:
        rule_id = fingerprint(rule)
        if rule.component not in modeled or rule_id in excluded_rules:
            exclusions.append({"rule_id": rule_id, "rule": rule.model_dump(mode="json"),
                               "reason": excluded_rules.get(rule_id, "Outside the modeled subtotal.")})
            continue
        if rule.status != "found" or rule.amount is None:
            raise ValueError(f"{rule.label}: unresolved amount/status; review it or explicitly exclude it from a subtotal scenario.")
        if rule.bands or rule.tier_method is not None or rule.time_window is not None:
            raise ValueError(f"{rule.label}: tiers/time windows are not supported by this compiler.")
        if rule.component != "credit" and any(v is not None for v in (
            rule.lower_kwh, rule.upper_kwh, rule.lower_inclusive, rule.upper_inclusive)):
            raise ValueError(f"{rule.label}: conditional energy/base/delivery pricing needs another engine.")
        amount = Decimal(rule.amount)
        if amount < 0:
            raise ValueError(f"{rule.label}: negative amounts are not supported; credits must be positive credit rules.")
        if rule.component in {"energy", "delivery"} and rule.kind == "flat_per_kwh":
            value = normalized_kwh_rate(rule)
            slot = f"{rule.component}_usd_per_kwh"
        elif rule.component in {"base", "delivery"} and rule.kind == "fixed" and rule.unit in {"currency_per_month", "currency_per_billing_cycle"}:
            value = amount
            slot = f"{rule.component}_usd_per_month"
        elif rule.component == "credit" and rule.kind == "usage_credit" and rule.unit in {"currency_per_month", "currency_per_billing_cycle"}:
            if amount <= 0 or rule.lower_kwh is None or rule.lower_inclusive is not True or rule.upper_kwh is not None or rule.upper_inclusive is not None:
                raise ValueError(f"{rule.label}: only one positive monthly credit with an inclusive lower threshold and no upper bound is supported.")
            value, slot = amount, "credit_usd"
            credit_min = Decimal(rule.lower_kwh)
        else:
            raise ValueError(f"{rule.label}: unsupported component/kind/unit combination.")
        if slot in slots:
            raise ValueError(f"Multiple rules map to {slot}; review possible double-counting or a more complex price structure.")
        slots[slot] = value
        mappings.append({"rule_id": rule_id, "label": rule.label, "field": slot,
                         "original_amount": rule.amount, "original_unit": rule.unit, "converted_value": str(value),
                         "conditions": rule.conditions, "citations": [c.model_dump() for c in rule.citations]})
        if rule.conditions:
            notes.append(f"Review conditions for {rule.label}: {rule.conditions}")
    required = {"energy": ["energy_usd_per_kwh"], "base": ["base_usd_per_month"],
                "delivery": ["delivery_usd_per_month", "delivery_usd_per_kwh"], "credit": ["credit_usd"]}
    for component, fields in required.items():
        if coverage[component].status == "explicit_none":
            for field in fields:
                slots[field] = Decimal("0")
                mappings.append({"field": field, "converted_value": "0", "reason": "Explicit absence in source.",
                                 "citations": [c.model_dump() for c in coverage[component].citations]})
        elif any(field not in slots for field in fields):
            raise ValueError(f"{component}: incomplete supported prices; no missing rate will be filled with zero.")
    notes.extend(candidate.unresolved_terms)
    notes.extend(f"Supporting document remains outstanding: {x}" for x in candidate.supporting_documents_needed)
    notes.append("Contract term: " + candidate.identity.contract_length.value)
    notes.append("Termination terms (excluded): " + (candidate.identity.termination_terms.value or "Not stated"))
    review_id = fingerprint({"record": record.model_dump(mode="json"), "scope": scope.model_dump(mode="json"),
                             "excluded_rules": excluded_rules, "compiler_version": "subtotal-v1"})
    return CompiledScenarioPlan(name=candidate.identity.plan_name.value,
        provider=candidate.identity.provider.value, source_file=record.source_file, source_sha256=record.source_sha256,
        record_fingerprint=fingerprint(record), review_fingerprint=review_id, scope=scope,
        contract_months=int(term_match[1]), credit_min_kwh=credit_min, mappings=mappings,
        exclusions=exclusions, review_notes=notes, **slots)


def load_saved_candidates(records_folder: Path, contracts_folder: Path) -> dict:
    """Discover all records; use latest matching live record per source, retain errors."""
    grouped, inventory, documents = {}, [], {}
    for path in sorted(records_folder.glob("*.json")):
        row = {"record_file": str(path), "status": "invalid"}
        inventory.append(row)
        try:
            record = PricingRecord.model_validate_json(path.read_text(encoding="utf-8"))
            row["source_file"] = record.source_file
            pdf = (contracts_folder / record.source_file).resolve()
            if pdf.parent != contracts_folder.resolve() or pdf.suffix.lower() != ".pdf":
                raise ValueError("Source must be a top-level PDF in contracts/.")
            if record.origin != "live":
                raise ValueError("Expected a saved live PDF extraction, not an authored example.")
            if pdf not in documents:
                documents[pdf] = read_pdf(pdf, include_tables=True)
            document = documents[pdf]
            load_pricing_record(path, document)
            stamp = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Record timestamp must include a timezone.")
            grouped.setdefault(record.source_file, []).append((stamp, path.name, record, document, row))
            row["status"] = "older_matching_record"
        except Exception as exc:
            row["error"] = str(exc)
    selected = []
    for source, entries in sorted(grouped.items()):
        _, _, record, document, row = max(entries, key=lambda x: (x[0], x[1]))
        row["status"] = "selected"
        selected.append({"record": record, "document": document, "record_file": row["record_file"]})
    return {"selected": selected, "inventory": inventory}


def compare_compiled(usage, plans: list[CompiledScenarioPlan]) -> dict:
    """Rank only within this explicit scenario; keep singleton results unranked."""
    if len({p.source_sha256 for p in plans}) != len(plans):
        raise ValueError("Duplicate source PDFs cannot compete against themselves.")
    if len({fingerprint(p.scope) for p in plans}) > 1:
        raise ValueError("Plans must use the same territory, currency, date and scenario assumptions.")
    results = []
    for plan in plans:
        bills = [calculate_month(m, plan) for m in usage.months]
        results.append({"source_file": plan.source_file, "name": plan.name,
                        "contract_months": plan.contract_months,
                        "annual_subtotal_usd": str(sum((b.total_usd for b in bills), Decimal("0.00"))),
                        "bills": [b.model_dump(mode="json") for b in bills]})
    results.sort(key=lambda r: (Decimal(r["annual_subtotal_usd"]), r["name"], r["source_file"]))
    if len(results) < 2:
        explanation = "At least two compatible compiled plans are needed for a comparison."
    else:
        lowest = Decimal(results[0]["annual_subtotal_usd"])
        winners = [r["name"] for r in results if Decimal(r["annual_subtotal_usd"]) == lowest]
        explanation = "Lowest modeled 12-month subtotal: " + ", ".join(winners) + f" (${lowest:.2f})."
        if len(winners) == 1:
            difference = Decimal(results[1]["annual_subtotal_usd"]) - lowest
            explanation += f" Difference from the next plan: ${difference:.2f}."
        explanation += " This is a scoped subtotal, not a full bill or a best-fit recommendation."
    return {"status": "illustrative_subtotal_comparison" if len(results) >= 2 else "insufficient_comparable_plans",
            "results": results, "explanation": explanation}
