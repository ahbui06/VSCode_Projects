"""Fictional fixtures exercise PDF ingestion and the graph without calling an LLM."""
from pathlib import Path

import pymupdf

from .models import Evidence, PlanTerms, ProviderConfig, Review, SupervisorNotes


def demo_terms(company, rate, credit=0):
    values = dict(provider=company, plan_name=f"{company} Fixed 12", pricing_type="fixed", currency="USD",
                  term_months=12, energy_cents_per_kwh=rate, delivery_cents_per_kwh=5.0,
                  monthly_base_usd=5.0, monthly_delivery_usd=4.5, credit_usd=credit,
                  credit_min_kwh=1000.0 if credit else None, credit_max_kwh=None,
                  early_termination_usd=150.0, renewable_percent=20.0,
                  renewal_terms="Renews at a new rate; written notice before expiry.", unresolved_terms=[], evidence=[])
    values["evidence"] = [Evidence(field=key, page=1, quote=f"{key}: {value}")
                          for key, value in values.items() if value is not None and key not in ("evidence", "unresolved_terms")]
    return PlanTerms(**values)


class DemoBackend:
    def __init__(self):
        self.plans = {"prairie": demo_terms("Prairie Demo Energy", 8.5),
                      "bayou": demo_terms("Bayou Demo Power", 10.5, 30),
                      "mesa": demo_terms("Mesa Demo Electric", 9.2)}

    def extract(self, provider, pages):
        return self.plans[provider.provider_id].model_copy(deep=True)

    def review(self, results, comparison):
        return SupervisorNotes(
            reviews=[Review(provider_id=r.provider_id, approved=r.terms is not None, issues=[]) for r in results],
            negotiation_questions=[
                "Can you match the lowest verified annual cost for my actual usage profile?",
                "Can the $150 early termination fee be reduced or waived?",
                "Can the bill credit apply in months below 1,000 kWh, and can that be written into the agreement?",
            ])


def create_demo(root: Path):
    directory = root / "outputs" / "demo_contracts"
    directory.mkdir(parents=True, exist_ok=True)
    backend = DemoBackend()
    providers = []
    for key, plan in backend.plans.items():
        path = directory / f"{key}.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            text = "FICTIONAL DEMO AGREEMENT - NOT AN AVAILABLE OFFER\n\n" + "\n".join(e.quote for e in plan.evidence)
            page.insert_text((40, 45), text, fontsize=10)
            doc.save(path)
        providers.append(ProviderConfig(provider_id=key, company=plan.provider, contract_path=str(path)))
    return providers, backend
