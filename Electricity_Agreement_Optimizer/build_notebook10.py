"""Generate the unexecuted Notebook 10 teaching artifact."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))

md("""# 10 — From general pricing rules to a cost comparison

Notebook 09 extracted structured rules with GPT-5. This lesson converts supported rules into Python pricing inputs and compares them using the same twelve months of usage. **No provider-specific PDF pricing parser and no new API calls are used.**

We discover your Notebook 09 record files automatically, so you do not need to paste pricing IDs. Run Sections 1–8 with your `.venv` kernel. Notebook 04's saved usage CSV and at least two compatible Notebook 09 records are the inputs; earlier notebook kernels are not needed.

Your two Reliant records contain enough numeric fields for a **modeled recurring subtotal**. They also contain unresolved terms. This notebook keeps those terms visible, shows a comparison preview, and lets you record your review of the scenario. It does not label the result a complete bill or an approved recommendation.""")
md("## 1. Imports and twelve months of usage\nWe reuse the component-rounding and usage-credit arithmetic from earlier lessons. The converter is new: it consumes the shared schema from 09. The default usage file is synthetic; the report labels it accordingly.")
code('''from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from html import escape
import json
import sys
import ipywidgets as widgets
from IPython.display import HTML, display

from electricity_optimizer.rule_compiler import (
    ComparisonScope, load_saved_candidates, fingerprint,
)
from electricity_optimizer.compiled_workflow import build_compilation_workflow
from electricity_optimizer.pricing import calculate_month
from electricity_optimizer.usage import MonthlyUsage, load_usage_csv

ROOT = Path.cwd()
CONTRACTS = ROOT / "contracts"
RECORDS = ROOT / "output/lesson09/records"
OUTPUT = ROOT / "output/lesson10"
USAGE_PATH = ROOT / "output/lesson04_synthetic/SYNTHETIC_usage_2025.csv"
USAGE_IS_SYNTHETIC = True  # Change only when replacing the CSV with actual usage.
if not USAGE_PATH.is_file():
    raise FileNotFoundError("Run Notebook 04 to save the synthetic usage CSV first.")
usage = load_usage_csv(USAGE_PATH)

def html_table(rows, columns):
    header = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(r.get(c, '')))}</td>" for c in columns) + "</tr>" for r in rows)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"

def show_table(rows, columns):
    display(HTML(html_table(rows, columns)))

print("Python:", sys.executable)
print("Usage type:", "SYNTHETIC" if USAGE_IS_SYNTHETIC else "User-provided actual usage")
print("Months:", len(usage.months), "Annual kWh:", sum(m.kwh for m in usage.months))''')
md("""## 2. Discover and validate saved records

For each PDF, we select the latest matching live pricing record. Old matching records remain in the inventory. Malformed/stale files and missing PDFs are reported. Fingerprints bind each record to the original PDF; replay validation happens here automatically.

The expected sources in your folder are `R1F00166003766B.pdf` and `R1F00160000021A.pdf`. A missing source stays missing; no API call is made to fill it in.""")
code('''loaded = load_saved_candidates(RECORDS, CONTRACTS)
entries = loaded["selected"]
show_table(loaded["inventory"], ["source_file", "status", "record_file", "error"])
print("Selected PDF records:", len(entries))
if not entries:
    print("No matching pricing records. Check the inventory or save a live extraction in Notebook 09.")

rule_rows = []
for entry in entries:
    for rule in entry["record"].candidate.rules:
        rule_rows.append({"source": entry["record"].source_file, "rule": rule.label,
                          "component": rule.component, "kind": rule.kind, "status": rule.status,
                          "amount": rule.amount, "unit": rule.unit, "rule ID": fingerprint(rule)})
show_table(rule_rows, ["source", "rule", "component", "kind", "status", "amount", "unit", "rule ID"])''')
md("""## 3. Define the comparison scenario

We model **energy + base + listed delivery − usage credit** over twelve billing cycles, using constant rates from the same document date. USD, United States and residential use are **scenario assumptions** where the PDF is silent; they do not become extracted facts. Stated conflicts in identity or territory are rejected. US date strings are interpreted as MM/DD/YYYY.

Taxes, termination fees, minimum/demand charges and other fees are outside this subtotal. Unknown charges remain unknown. This means the preview is useful for learning the arithmetic but does not establish which complete contract is cheapest.

Your 24-month record contains a separate `ITR refund (varies)` rule with no numeric amount. The explicit exclusion below uses that exact rule's fingerprint. The scenario uses the listed delivery totals without estimating an additional ITR adjustment, as in Notebook 07. This is a disclosed modeling choice, not a finding that ITR is zero. If the rule changes, its ID will not match and compilation will stop for review.

Special McAllen/Mission former-Oncor adjustments and future tariff changes are not modeled. All remaining condition text will be displayed in Section 5. Do not exclude a numeric energy/base/delivery rule just to make a plan pass.""")
code('''SCOPE = ComparisonScope(
    country="United States",
    territory="AEP Texas Central service area",
    currency="USD",
    customer_type="residential",
    document_date="2026-09-01",
)

EXCLUDED_RULES = {
    "R1F00160000021A.pdf": {
        "d80e89c3f9c7989d7bd828aae754237963f97719a591cb0f86f1d33cd5132216":
            "Scenario uses listed delivery totals; the unpriced ITR rider is not estimated separately. Its actual effect remains unresolved."
    }
}

print("Scenario:", SCOPE.country, SCOPE.territory, SCOPE.currency, SCOPE.document_date)
for assumption in SCOPE.assumptions:
    print(" -", assumption)''')
md("""## 4. Compile the general rules

**Compile** means translate supported rule structures into numeric inputs for the calculator. For example, `16.6483 cents_per_kwh` becomes `0.166483 USD/kWh`.

The compiler accepts one flat energy rate, one fixed base charge, fixed plus per-kWh delivery, and one positive monthly credit with an inclusive lower threshold and no upper limit. Explicit source absence can supply zero; missing values cannot. Tiered/time-of-use rules, daily charges, conflicting identities, duplicate fields and unsupported credit boundaries are rejected rather than approximated.

This graph compiles each record independently, then compares compatible plans. A failed record stays visible with its reason. The same code works for other providers when their extracted rule structures fit this subset.""")
code('''workflow = build_compilation_workflow(SCOPE, usage, EXCLUDED_RULES)
result = workflow.invoke({"entries": entries})
plans = result["plans"]
COMPILED_CONTEXT = fingerprint({"scope": SCOPE.model_dump(mode="json"),
    "usage": usage.model_dump(mode="json"), "synthetic_usage": USAGE_IS_SYNTHETIC,
    "exclusions": EXCLUDED_RULES, "records": [fingerprint(e["record"]) for e in entries]})
show_table(result["compilation"], ["source", "status", "reason"])
show_table([{"plan": p.name, "energy USD/kWh": p.energy_usd_per_kwh,
             "base USD/month": p.base_usd_per_month, "delivery USD/kWh": p.delivery_usd_per_kwh,
             "delivery USD/month": p.delivery_usd_per_month, "credit USD": p.credit_usd,
             "credit threshold kWh": p.credit_min_kwh, "contract months": p.contract_months}
            for p in plans],
           ["plan", "energy USD/kWh", "base USD/month", "delivery USD/kWh", "delivery USD/month",
            "credit USD", "credit threshold kWh", "contract months"])
print("Compiled scenarios:", len(plans))''')
md("""## 5. Review the mappings, evidence and exclusions

Expand each plan below. Check the source quotes, original units and converted values against the PDF. Read the conditions and excluded rules, especially the ITR and territory exceptions. Free-text conditions are retained here; the compiler does not execute them.

The checkboxes start unchecked. You can continue to the numerical preview while reviewing. If you have checked a plan, tick its box, enter your name and accept the shared scenario. Section 8 records these choices with a fingerprint of the exact record, scenario and exclusions. This records a review of this limited scenario, not approval of the whole contract. Rerunning this section resets the checkboxes.""")
code('''review_boxes = {}
panels = []
for plan in plans:
    content = "<h4>Rule-to-calculator mapping</h4>" + html_table(plan.mappings,
        ["label", "field", "original_amount", "original_unit", "converted_value", "conditions", "citations", "reason"])
    content += "<h4>Outside this subtotal</h4>" + html_table(plan.exclusions,
        ["component", "status", "explanation", "rule", "reason"])
    content += "<h4>Conditions and outstanding information</h4><ul>" + "".join(
        f"<li>{escape(note)}</li>" for note in plan.review_notes) + "</ul>"
    checkbox = widgets.Checkbox(value=False, description="I checked this plan's mappings, quotes and exclusions.",
                                indent=False, layout=widgets.Layout(width="auto"))
    review_boxes[plan.review_fingerprint] = checkbox
    panels.append(widgets.VBox([widgets.HTML(content), checkbox]))
accordion = widgets.Accordion(children=panels)
for i, plan in enumerate(plans):
    accordion.set_title(i, plan.name)
reviewer = widgets.Text(description="Reviewer:", placeholder="Your name")
review_date = widgets.DatePicker(description="Review date:", value=date.today())
scope_accepted = widgets.Checkbox(value=False,
    description="I accept the stated assumptions and exclusions for this subtotal scenario.",
    indent=False, layout=widgets.Layout(width="auto"))
display(accordion, reviewer, review_date, scope_accepted)
if not plans:
    print("Resolve the Section 4 compilation messages first; no plan is available to review.")''')
md("""## 6. Inspect the twelve-month comparison

This preview is based on the selected usage CSV and the scope above. Review choices are saved separately in Section 8. It is not a whole-contract recommendation.

With your current two saved records and 11,970 synthetic annual kWh, the expected modeled subtotals are **$2,572.69** for the 24-month plan and **$2,720.59** for the 12-month plan. The $147.90 difference covers the first twelve months only; the 24-month plan has a longer commitment. No synthetic month reaches 2,000 kWh, so neither receives the $150 credit in this usage profile.

These expected values are a teaching cross-check from Notebook 07, not hardcoded calculator outputs.""")
code('''comparison = result["comparison"]
show_table(comparison["results"], ["name", "contract_months", "annual_subtotal_usd"])
print(comparison["explanation"])

MONTHLY_PLAN_INDEX = 0
if comparison["results"]:
    if not 0 <= MONTHLY_PLAN_INDEX < len(comparison["results"]):
        raise ValueError("Choose a valid MONTHLY_PLAN_INDEX.")
    monthly_result = comparison["results"][MONTHLY_PLAN_INDEX]
    print("Monthly detail:", monthly_result["name"])
    show_table(monthly_result["bills"],
               ["month", "kwh", "energy_usd", "base_usd", "delivery_usd", "credit_usd", "total_usd"])''')
md("""## 7. Check the credit boundary

This separate exercise uses usage just below, at and above each plan's credit threshold. It helps you verify that **at least 2,000 kWh** includes exactly 2,000. These are test months, not changes to the usage CSV or the annual comparison.

For the 12-month plan, 1,999 kWh should produce $451.09, while 2,000 kWh should produce $301.32 because the credit activates. Lower consumption is not always a lower bill when a threshold credit is present.""")
code('''boundary_rows = []
for plan in plans:
    if plan.credit_min_kwh is None:
        continue
    for kwh in (max(Decimal("0"), plan.credit_min_kwh - 1), plan.credit_min_kwh, plan.credit_min_kwh + 1):
        bill = calculate_month(MonthlyUsage(month=usage.months[0].month, kwh=kwh), plan)
        boundary_rows.append({"plan": plan.name, "kWh": kwh,
                              "credit USD": bill.credit_usd, "subtotal USD": bill.total_usd})
show_table(boundary_rows, ["plan", "kWh", "credit USD", "subtotal USD"])''')
md("""## 8. Save the comparison and your review choices

This saves the source records, compiled mappings, conditions, exclusions, usage, monthly bills and review choices together. Unticked plans remain unreviewed. Checking the boxes does not resolve missing supporting documents or establish customer eligibility.

You can change review choices in Section 5 and rerun only this section to save them. If you change the scenario, exclusions or records, rerun Sections 2–8 so the calculations and review fingerprints agree. Existing Notebook 06 and 09 review/extraction files are preserved.""")
code('''current_context = fingerprint({"scope": SCOPE.model_dump(mode="json"),
    "usage": usage.model_dump(mode="json"), "synthetic_usage": USAGE_IS_SYNTHETIC,
    "exclusions": EXCLUDED_RULES, "records": [fingerprint(e["record"]) for e in entries]})
if current_context != COMPILED_CONTEXT:
    raise ValueError("Inputs changed after compilation. Rerun Sections 4-8 before saving.")

review_decisions = []
for plan in plans:
    box = review_boxes.get(plan.review_fingerprint)
    confirmed = bool(box and box.value and scope_accepted.value and reviewer.value.strip() and review_date.value)
    review_decisions.append({
        "source_file": plan.source_file, "review_fingerprint": plan.review_fingerprint,
        "status": "reviewed_for_this_scenario" if confirmed else "unreviewed",
        "reviewer": reviewer.value.strip() if confirmed else None,
        "review_date": review_date.value.isoformat() if confirmed else None,
    })

all_reviewed = bool(plans) and all(r["status"] == "reviewed_for_this_scenario" for r in review_decisions)
report = {
    "lesson": "10_general_rule_comparison",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "status": "reviewed_scenario_subtotals" if all_reviewed else "unreviewed_scenario_preview",
    "approved_for_real_plan_recommendation": False,
    "synthetic_usage": USAGE_IS_SYNTHETIC, "usage": usage.model_dump(mode="json"),
    "scope": SCOPE.model_dump(mode="json"),
    "inventory": loaded["inventory"],
    "source_records": [e["record"].model_dump(mode="json") for e in entries],
    "compilation": result["compilation"],
    "plans": [p.model_dump(mode="json") for p in plans],
    "comparison": comparison, "review_decisions": review_decisions,
}
OUTPUT.mkdir(parents=True, exist_ok=True)
destination = OUTPUT / "general_rule_comparison.json"
destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Saved:", destination)
print("Review status:", report["status"])
print("Comparison status:", comparison["status"])''')
md("""## What we have connected

**PDF → GPT-5 pricing record → general-rule compiler → monthly arithmetic → comparison report.**

The converter now reads the same schema for any provider whose rules fit the supported subset. We still need broader pricing engines, real usage intake, stronger review/eligibility checks and the recommendation/negotiation agents for the final application.

Your next step is to inspect the two plan panels in Section 5, then read the monthly and threshold results. The following lesson can explain the comparison and formulate negotiation questions while carrying forward these limitations.""")
nb.cells = cells
nb.metadata = {"kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
               "language_info": {"name": "python"}}
nbf.validate(nb)
nbf.write(nb, Path(__file__).parent / "10_general_rule_comparison.ipynb")
