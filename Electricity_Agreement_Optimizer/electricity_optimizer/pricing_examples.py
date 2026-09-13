"""Authored synthetic examples. These are NOT GPT-5 extraction results or real PDFs."""
from hashlib import sha256

from .agreements import Citation, ContractTerm
from .models import PDFDocument, PDFPage
from .pricing_extraction import PricingRecord, PROMPT_VERSION
from .pricing_schema import ComponentCoverage, PlanIdentity, PricingCandidate, PricingRule, SCHEMA_VERSION


def teaching_examples():
    examples = []
    for provider, label, energy, is_tou in [
        ("Demo Cedar Energy", "Simple 12", "Energy: 10 cents per kWh at all hours.", False),
        ("Demo Harbor Power", "Evening 12", "Energy: 8 cents per kWh 00:00-16:00; 20 cents per kWh 16:00-24:00, daily, UTC.", True),
    ]:
        statements = {
            "provider": f"Provider: {provider}.", "plan_name": f"Plan: {label}.",
            "country": "Country: United States.", "territory": "Territory: Fictional Demo Zone.",
            "currency": "Currency: USD.", "customer_type": "Customer: residential.",
            "document_date": "Document date: 2026-09-01.", "contract_length": "Term: 12 months.",
            "renewal_terms": "Renewal requires a new agreement.", "termination_terms": "No termination fee.",
        }
        extra = [energy, "Base fee: USD 5 per month.", "No separate delivery charges.",
                 "No usage credits.", "No minimum charges.", "No demand charges.",
                 "No other fees.", "Taxes are excluded from these example prices."]
        text = "SYNTHETIC TEACHING EXAMPLE — NOT AN OFFER\n" + "\n".join([*statements.values(), *extra])
        doc = PDFDocument(source_file=f"AUTHORED_{provider.replace(' ', '_')}.txt",
                          sha256=sha256(text.encode()).hexdigest(),
                          pages=[PDFPage(page_number=1, text=text, needs_review=False)])
        def cites(quote): return [Citation(page_number=1, quote=quote)]
        identity = PlanIdentity(**{name: ContractTerm(status="found",
                                  value=value.split(": ", 1)[-1].removesuffix("."), citations=cites(value))
                                  for name, value in statements.items()})
        def rule(label, component, kind, amount, unit, quote, window=None):
            return PricingRule(label=label, component=component, kind=kind, status="found",
                amount=amount, unit=unit, lower_kwh=None, upper_kwh=None,
                lower_inclusive=None, upper_inclusive=None, bands=[], tier_method=None,
                time_window=window, conditions=None, citations=cites(quote))
        rules = [rule("Monthly base", "base", "fixed", "5", "currency_per_month", extra[1])]
        if is_tou:
            rules.extend([rule("Off-peak energy", "energy", "time_of_use", "8", "cents_per_kwh", energy, "00:00-16:00 daily UTC"),
                          rule("Peak energy", "energy", "time_of_use", "20", "cents_per_kwh", energy, "16:00-24:00 daily UTC")])
        else:
            rules.append(rule("All-hours energy", "energy", "flat_per_kwh", "10", "cents_per_kwh", energy))
        coverage = [ComponentCoverage(component=c, status="present", explanation="Explicit charge.", citations=cites(q))
                    for c, q in [("energy", energy), ("base", extra[1])]]
        coverage.extend(ComponentCoverage(component=c, status="explicit_none", explanation=q, citations=cites(q))
                        for c, q in [("delivery", extra[2]), ("credit", extra[3]), ("minimum_charge", extra[4]),
                                     ("demand", extra[5]), ("other", extra[6]), ("termination", statements["termination_terms"])])
        coverage.append(ComponentCoverage(component="tax", status="ambiguous", explanation=extra[7], citations=cites(extra[7])))
        candidate = PricingCandidate(identity=identity, coverage=coverage, rules=rules,
                                     unresolved_terms=[], supporting_documents_needed=[])
        record = PricingRecord(schema_version=SCHEMA_VERSION, prompt_version=PROMPT_VERSION,
            source_file=doc.source_file, source_sha256=doc.sha256, origin="authored_example",
            model=None, response_id=None, created_at="2026-09-01T00:00:00+00:00", candidate=candidate)
        examples.append((doc, record))
    return examples
