"""Rebuild the unexecuted teaching notebook."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))

md("""# 08 — Scan and compare the contract portfolio

In 07 we selected two PDFs. Here we discover **every top-level PDF in `contracts/`**, show why each can or cannot be calculated, and compare compatible supported plans.

This is an **unapproved demonstration using synthetic usage**, not a current-offer recommendation. The pricing adapter still supports only Reliant Power Savings 2,000 kWh 12/24 EFLs. Other PDFs remain visible for future adapters/review. No API key or live API calls are needed. Run sections in order using your `.venv` kernel.""")
md("## 1. Imports and project paths\nThis notebook is independent of previous kernel sessions. It reads the synthetic usage file saved by 04.")
code('''from pathlib import Path
from typing import TypedDict
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from IPython.display import HTML, display
from langgraph.graph import StateGraph, START, END
from electricity_optimizer.portfolio import scan_portfolio, compare_portfolio
from electricity_optimizer.usage import load_usage_csv

ROOT = Path.cwd()
if not (ROOT / "contracts").is_dir():
    raise FileNotFoundError("Open this notebook from the project root containing contracts/.")
CONTRACTS = ROOT / "contracts"
EXTRACTIONS = ROOT / "output/extraction"
USAGE_PATH = ROOT / "output/lesson04_synthetic/SYNTHETIC_usage_2025.csv"
if not USAGE_PATH.exists():
    raise FileNotFoundError("Run Notebook 04 to save its synthetic usage CSV first.")
usage = load_usage_csv(USAGE_PATH)

def table(rows, columns):
    header = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(r.get(c, '')))}</td>" for c in columns) + "</tr>" for r in rows)
    display(HTML(f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"))

print("PDF folder:", CONTRACTS)
print("Synthetic annual kWh:", sum(m.kwh for m in usage.months))''')
md("""## 2. Build the portfolio workflow

`scan → compare`: the first node reads PDFs and audits matching saved extractions; the second groups supported prices by territory, currency and document date. This graph uses Python functions, with no LLM calls.

Bad PDFs and malformed saved records are reported individually. Duplicate PDF bytes count once. A group needs at least two distinct plan names to rank.""")
code('''class PortfolioState(TypedDict, total=False):
    scan: dict
    groups: list

def scan_node(state):
    return {"scan": scan_portfolio(CONTRACTS, EXTRACTIONS)}

def compare_node(state):
    return {"groups": compare_portfolio(state["scan"], usage)}

builder = StateGraph(PortfolioState)
builder.add_node("scan", scan_node)
builder.add_node("compare", compare_node)
builder.add_edge(START, "scan")
builder.add_edge("scan", "compare")
builder.add_edge("compare", END)
workflow = builder.compile()
result = workflow.invoke({})
print("PDFs inventoried:", len(result["scan"]["inventory"]))''')
md("""## 3. Read the inventory

- **demo_ready**: the narrow adapter found its required source prices; not approved.
- **unsupported_or_incomplete**: no supported complete pricing representation. This does **not** mean there are no prices anywhere in the PDF.
- **needs_text_review / unreadable**: inspect the PDF or improve extraction first.
- **duplicate**: another filename contains the same bytes.

Extraction status is separate: missing or stale saved AI output does not prevent the independent source-price adapter from running.""")
code('''inventory = result["scan"]["inventory"]
table(inventory, ["file", "status", "extraction_status", "reason"])
print(dict(Counter(row["status"] for row in inventory)))
if not inventory:
    print("No PDFs found. Add PDFs to contracts/ and rerun Section 2.")''')
md("## 4. Inspect extraction issues and source prices\nExisting model quotes are checked against the current PDF. Errors remain unresolved even when independent price parsing succeeds. Expand the printed evidence by choosing a filename below.")
code('''for row in inventory:
    if row["issues"]:
        print("\\n", row["file"])
        table(row["issues"], ["severity", "field", "message"])
for error in result["scan"]["saved_record_errors"]:
    print("Saved-record read error:", error["file"], error["error"])

plans = result["scan"]["plans"]
SELECTED_FILE = plans[0].source_file if plans else None  # Change to another supported PDF filename.
selected = next((p for p in plans if p.source_file == SELECTED_FILE), None)
if selected:
    print("Source evidence:", selected.source_file)
    table([{"field": field, **e.model_dump()} for field, e in selected.evidence.items()],
          ["field", "value", "page_number", "quote"])
else:
    print("No supported plan selected.")''')
md("""## 5. Compare within each compatible group

Costs use the same twelve synthetic monthly usage values for every plan. Rates are held at the PDF snapshot, with inclusive monthly usage credits and component rounding to cents (half up). USD is the adapter's US-plan assumption. The comparison covers 12 months even for a 24-month commitment.

Taxes, deposits, early termination/switching charges, future tariff changes and special-territory adjustments are excluded. Standard AEP Texas Central delivery totals are used without separately estimating ITR adjustments. The McAllen/Mission former-Oncor exception is outside this demonstration. Matching group keys alone do not establish customer eligibility.""")
code('''for group in result["groups"]:
    print("\\n", group["market"], group["currency"], group["document_date"], "—", group["status"])
    if not group["results"]:
        print(group["reason"])
        continue
    table([{"plan": r["plan"]["name"], "12-month USD": r["annual_usd"],
            "contract months": r["plan"]["contract_months"],
            "termination USD (excluded)": r["plan"]["termination_usd"]}
           for r in group["results"]],
          ["plan", "12-month USD", "contract months", "termination USD (excluded)"])
if not result["groups"]:
    print("No supported groups yet; inspect the inventory reasons.")''')
md("## 6. Save the portfolio report\nThis saves a new lesson report with all inventory rows, source evidence, unresolved issues, assumptions and calculated bills. It does not modify your PDFs, extraction records or Notebook 06 review JSON.")
code('''report = {
    "status": "source_backed_demonstration_not_approved",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "synthetic_usage": True,
    "assumptions": ["12 months; snapshot rates held constant; USD assumed for supported US EFLs",
                    "Standard AEP Texas Central territory; excludes former-Oncor exception",
                    "Component rounding to cents, half up; inclusive monthly credit threshold",
                    "Excludes taxes, deposits, switching/termination costs and future tariff changes",
                    "Uses listed delivery totals without independently estimating ITR adjustments",
                    "AI evidence errors remain unresolved; no human approval is implied"],
    "usage": usage.model_dump(mode="json"),
    "inventory": inventory,
    "saved_record_errors": result["scan"]["saved_record_errors"],
    "supported_plans": [p.model_dump(mode="json") for p in plans],
    "groups": result["groups"],
}
destination = ROOT / "output/lesson08/portfolio_comparison.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Saved:", destination)''')
md("""## 7. What to try next

Add another PDF and rerun Sections 2–6. It should appear in the inventory even if it cannot be ranked. Check its exclusion reason before choosing a next pricing adapter.

For your existing seven PDFs, expect the two Power Savings plans to form one demonstration comparison group. The other documents remain listed for pricing support/review. A future lesson can add adapters for more pricing structures and a recommendation explanation grounded in the saved results.""")
nb.cells = cells
nb.metadata = {"kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
               "language_info": {"name": "python"}}
nbf.validate(nb)
nbf.write(nb, Path(__file__).parent / "08_portfolio_comparison.ipynb")
