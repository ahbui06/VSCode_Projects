import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import AgentBackend
from .costs import PRICING_FIELDS, eligibility_issues, estimate
from .documents import read_pdf
from .models import Evidence, Preferences, ProviderConfig, ProviderResult, Report, Review, UsageHistory


class State(TypedDict):
    usage: UsageHistory
    preferences: Preferences
    results: Annotated[list[ProviderResult], operator.add]
    report: Report


def evidence_issues(result: ProviderResult) -> list[str]:
    if result.terms is None:
        return ["No extracted agreement"]
    plan = result.terms
    # Dollar symbols support the USD interpretation; a synthetic "currency"
    # quotation is not required as long as each monetary charge is sourced.
    required = set(PRICING_FIELDS) - {"currency"}
    if plan.credit_usd:
        required.add("credit_min_kwh")
        if plan.credit_max_kwh is not None:
            required.add("credit_max_kwh")
    if plan.renewable_percent is not None:
        required.add("renewable_percent")
    supported = set()
    issues = []
    def tokens(value):
        return [token for token in "".join(
            char.lower() if char.isalnum() else " " for char in value
        ).split() if token]

    def quoted_on_page(quote, page):
        wanted, source = tokens(quote), iter(tokens(page))
        # PDF table extraction can insert the left-column label in the middle
        # of a right-column sentence. Requiring quote tokens in source order
        # tolerates that insertion without accepting reordered/fabricated text.
        return bool(wanted) and all(any(item == token for item in source) for token in wanted)

    for evidence in plan.evidence:
        if evidence.page > len(result.pages) or not quoted_on_page(evidence.quote, result.pages[evidence.page - 1]):
            issues.append(f"Unverifiable source quote for {evidence.field}")
        else:
            supported.add(evidence.field)
    issues.extend(f"Missing source evidence: {field}" for field in sorted(required - supported))
    return issues


def build_graph(providers: list[ProviderConfig], backend: AgentBackend, mode="live"):
    if not providers or len({p.provider_id for p in providers}) != len(providers):
        raise ValueError("Supply at least one provider with unique provider_id values")
    if mode not in ("demo", "live"):
        raise ValueError("mode must be demo or live")
    graph = StateGraph(State)

    def dispatch(state):
        # Validate direct callers as well as notebook inputs.
        return {"usage": UsageHistory.model_validate(state["usage"]),
                "preferences": Preferences.model_validate(state["preferences"])}

    graph.add_node("supervisor_dispatch", dispatch)
    graph.add_edge(START, "supervisor_dispatch")
    workers = []
    for provider in providers:
        def worker(state, provider=provider):
            pages = []
            try:
                pages = read_pdf(provider.contract_path)
                terms = backend.extract(provider, pages)
                if terms.monthly_base_usd is None:
                    no_base_statement = (
                        "The price you pay each month includes the Energy Charge and "
                        "TDU Delivery Charges in effect for your monthly billing cycle."
                    )
                    for page_number, page_text in enumerate(pages, 1):
                        if no_base_statement in " ".join(page_text.split()):
                            terms.monthly_base_usd = 0
                            terms.evidence.append(Evidence(
                                field="monthly_base_usd", page=page_number, quote=no_base_statement
                            ))
                            break
                issues = []
                if terms.provider.casefold().strip() != provider.company.casefold().strip():
                    issues.append("Extracted company does not match the configured provider")
                result = ProviderResult(provider_id=provider.provider_id, terms=terms, pages=pages, issues=issues)
            except Exception as exc:
                result = ProviderResult(provider_id=provider.provider_id, terms=None, pages=pages,
                                        issues=[f"Extraction failed ({type(exc).__name__}); check PDF and API configuration"])
            return {"results": [result]}

        node = "provider_" + provider.provider_id
        graph.add_node(node, worker)
        graph.add_edge("supervisor_dispatch", node)
        workers.append(node)

    def supervise(state):
        results = sorted(state["results"], key=lambda r: r.provider_id)
        checks, estimates = {}, {}
        for result in results:
            issues = result.issues + evidence_issues(result)
            if result.terms:
                issues += eligibility_issues(result.terms, state["preferences"])
                if not issues:
                    try:
                        estimates[result.provider_id] = estimate(result.provider_id, result.terms,
                                                                 state["usage"], state["preferences"])
                    except ValueError as exc:
                        issues.append(str(exc))
            checks[result.provider_id] = issues
        questions = []
        try:
            notes = backend.review(results, "Computed estimates (pre-tax historical replay):\n" +
                                   "\n".join(e.model_dump_json() for e in estimates.values()))
            ids = [review.provider_id for review in notes.reviews]
            if len(ids) != len(results) or set(ids) != set(checks):
                raise ValueError("Supervisor did not review every provider exactly once")
            for review in notes.reviews:
                if not review.approved:
                    checks[review.provider_id].extend(review.issues)
                    checks[review.provider_id].append("Supervisor withheld approval")
            questions = notes.negotiation_questions
        except Exception as exc:
            for issues in checks.values():
                issues.append(f"Supervisor review unavailable ({type(exc).__name__}); approval withheld")
        reviews = [Review(provider_id=key, approved=not issues, issues=list(dict.fromkeys(issues)))
                   for key, issues in checks.items()]
        ranking = sorted((estimates[r.provider_id] for r in reviews if r.approved),
                         key=lambda e: (e.first_year_usd, e.provider_id))
        report = Report(mode=mode, reviews=reviews, ranking=ranking,
                        recommended_provider_id=ranking[0].provider_id if ranking else None,
                        negotiation_questions=questions, limitations=[
                            "Historical 12-month usage replay, not a forecast or a binding quote.",
                            "Pre-tax costs; fixed USD plans only. Unsupported or ambiguous terms are excluded.",
                            "Confirm current availability, service territory, eligibility, and extracted terms before signing.",
                            "Switching cost is user-supplied; a new plan's future exit fee is not charged in this estimate.",
                            "Best fit means lowest first-year cost among approved plans meeting your preferences.",
                            "Source quote matching verifies presence; semantic correctness still requires review.",
                        ])
        return {"report": report}

    graph.add_node("supervisor_review", supervise)
    graph.add_edge(workers, "supervisor_review")
    graph.add_edge("supervisor_review", END)
    return graph.compile()
