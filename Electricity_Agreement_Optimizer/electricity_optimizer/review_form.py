"""Local notebook review form; rendering never writes or records approval."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

import ipywidgets as widgets
from IPython.display import display

from .agreements import ExtractionRecord
from .extraction import citation_matches
from .models import PDFDocument
from .review import (Evidence, PricingReview, ReviewedValue, NUMERIC_FIELDS,
                     SCENARIO_ASSUMPTIONS, SUPPORTED_STRUCTURE, review_blockers)


def prefill_candidates(review: PricingReview, record: ExtractionRecord,
                       document: PDFDocument) -> PricingReview:
    if (review.source_sha256 != document.sha256 or record.source_sha256 != document.sha256
            or review.source_file != document.source_file):
        raise ValueError("Review, extraction and PDF must describe the same source.")
    result = review.model_copy(deep=True)
    target = result.energy_usd_per_kwh
    # Only fill an entirely untouched field. Preserve user input and approvals.
    if target.value is not None or target.evidence or target.reviewer or target.reviewed_on:
        return result
    term = record.terms.energy_charges
    if term.status != "found":
        return result
    candidates = []
    for citation in term.citations:
        page = next((p for p in document.pages if p.page_number == citation.page_number), None)
        if page is None or not citation_matches(citation.quote, page):
            continue
        # Narrow conversion rule. Do not mine illustrative average-price rows.
        for match in re.finditer(r"Energy\s+Charge\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:¢|cents)\s*(?:per\s+|/\s*)kWh\b",
                                 citation.quote, flags=re.IGNORECASE):
            candidates.append((str(Decimal(match.group(1)) / 100), Evidence(
                source_sha256=document.sha256, page_number=citation.page_number, quote=match.group(0))))
    if len({value for value, _ in candidates}) == 1:
        result.energy_usd_per_kwh = ReviewedValue(value=candidates[0][0],
                                                  evidence=[candidates[0][1]])
    return result


def save_review(path: Path, expected_text: str, review: PricingReview) -> None:
    """Refuse to overwrite edits made after the form was opened."""
    if path.read_text(encoding="utf-8") != expected_text:
        raise ValueError("Review file changed on disk. Rerun the form cell before saving.")
    backup = path.with_name(path.stem + ".before_form_save.json")
    backup.write_text(expected_text, encoding="utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def show_review_form(path: Path, record: ExtractionRecord, documents: list[PDFDocument]):
    original_text = path.read_text(encoding="utf-8")
    original = PricingReview.model_validate_json(original_text)
    primary = next(d for d in documents if d.sha256 == original.source_sha256)
    candidate = prefill_candidates(original, record, primary)
    sources = {d.sha256: d for d in documents}
    options = [(d.source_file, d.sha256) for d in documents]
    reviewer = widgets.Text(description="Your name:")
    reviewed_on = widgets.Text(value=date.today().isoformat(), description="Review date:")
    assumptions = widgets.Checkbox(value=original.accept_scenario_assumptions,
                                  description="I accept the scenario assumptions", indent=False)
    controls = {}
    panels = []

    def evidence_editor(evidence):
        rows = []
        box = widgets.VBox()

        def add_row(item=None):
            source = widgets.Dropdown(options=options, description="Source:", layout=widgets.Layout(width="95%"))
            if item and item.source_sha256 in sources:
                source.value = item.source_sha256
            elif item:
                source.options = [*options, ("Unavailable source", item.source_sha256)]
                source.value = item.source_sha256
            page = widgets.IntText(value=item.page_number if item else 1, description="Page:")
            quote = widgets.Textarea(value=item.quote if item else "", description="Exact quote:",
                                     layout=widgets.Layout(width="95%", height="85px"))
            remove = widgets.Checkbox(description="Remove this citation", indent=False)
            rows.append((source, page, quote, remove))
            box.children = (*box.children, widgets.VBox([source, page, quote, remove]))

        for item in evidence:
            add_row(item)
        add = widgets.Button(description="Add citation")
        add.on_click(lambda _: add_row())
        return widgets.VBox([box, add]), rows

    for name in PricingReview.model_fields:
        item = getattr(candidate, name)
        if not isinstance(item, ReviewedValue):
            continue
        old = getattr(original, name)
        value = widgets.Text(value=item.value or "", description="Value:", layout=widgets.Layout(width="95%"))
        evidence_box, citations = evidence_editor(item.evidence)
        approve = widgets.Checkbox(value=False, description="I checked this value and its evidence", indent=False)
        status = "Previously reviewed; preserved unless edited." if old.reviewer else "Not reviewed."
        if item != old:
            status += " Candidate prefilled: cents/kWh divided by 100; check all rate conditions."
        controls[name] = (value, citations, approve)
        panels.append(widgets.VBox([widgets.Label(status), value, evidence_box, approve]))
    accordion = widgets.Accordion(children=panels)
    for index, name in enumerate(controls):
        accordion.set_title(index, name)
    output = widgets.Output()
    save = widgets.Button(description="Save review & check", button_style="primary")

    def on_save(_):
        nonlocal original_text, original
        with output:
            output.clear_output()
            try:
                draft = original.model_copy(deep=True)
                for name, (value, citations, approve) in controls.items():
                    evidence = [Evidence(source_sha256=s.value, page_number=p.value, quote=q.value)
                                for s, p, q, remove in citations if not remove.value and q.value.strip()]
                    text = value.value.strip() or None
                    old = getattr(original, name)
                    unchanged = text == old.value and evidence == old.evidence
                    item = old.model_copy(deep=True) if unchanged else ReviewedValue(value=text, evidence=evidence)
                    if approve.value:
                        if not reviewer.value.strip():
                            raise ValueError("Enter your name before recording a new review.")
                        date.fromisoformat(reviewed_on.value)
                        item.reviewer = reviewer.value.strip()
                        item.reviewed_on = reviewed_on.value
                    setattr(draft, name, item)
                draft.accept_scenario_assumptions = assumptions.value
                blockers = review_blockers(draft, documents)
                for name, (_, _, approve) in controls.items():
                    if approve.value:
                        issues = [b for b in blockers if b.startswith(name + ":")]
                        if name == "currency" and draft.currency.value != "USD":
                            issues.append("Currency must be supported USD with evidence.")
                        if name == "pricing_structure" and draft.pricing_structure.value != SUPPORTED_STRUCTURE:
                            issues.append("Pricing structure is outside the supported scope.")
                        if issues:
                            raise ValueError("Cannot mark this field reviewed: " + " ".join(issues))
                save_review(path, original_text, draft)
                original_text = path.read_text(encoding="utf-8")
                original = draft
                for _, _, approve in controls.values():
                    approve.value = False
                print("Saved. Previous file backed up beside the review JSON.")
                print("BLOCKED" if blockers else "Ready for the limited scenario")
                # Group repeated blockers under their field, without hiding missing evidence.
                for blocker in blockers:
                    print("-", blocker)
                print("Rerun Sections 5–7 to refresh calculation and saved readiness report.")
            except (ValueError, OSError) as error:
                print(str(error))

    save.on_click(on_save)
    display(widgets.VBox([widgets.HTML("<b>Review pricing inputs</b><p>Blank means unknown. No field is approved automatically.</p>"),
                         reviewer, reviewed_on, accordion, widgets.Label(SCENARIO_ASSUMPTIONS), assumptions, save, output]))
    return {"controls": controls, "save": save, "reviewer": reviewer, "reviewed_on": reviewed_on}
