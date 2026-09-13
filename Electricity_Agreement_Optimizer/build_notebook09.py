"""Generate the unexecuted Notebook 09 teaching artifact."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))

md("""# 09 — General pricing schema and GPT-5 extraction

**Goal:** send different providers' PDF text through the same extraction workflow, with no provider-name parser required. Each result has the same structure, exact source quotes, and a clear next step.

This lesson builds the general **extraction and review stage**. It does not yet replace Notebook 08's calculator or make every extracted rule executable. A later lesson will connect reviewed rules to calculation engines and your 12 months of usage.

Start with `MODE = "example"`. The two offline examples are **manually authored fictional page text and answers**, not real PDFs or GPT-5 results. They let you learn the schema without an API key. Then choose `live` for your PDFs or `replay` for pricing records saved by this notebook.

Use your project's `.venv` kernel and run sections in order. You do not need to rerun Notebooks 01–08 first.""")
md("## 1. Imports and paths\nThe reusable implementation lives in `pricing_schema.py`, `pricing_extraction.py`, and `pricing_examples.py`. Check that the interpreter below belongs to `.venv`.")
code('''from pathlib import Path
from datetime import datetime, timezone
from html import escape
import json
import sys
from IPython.display import HTML, display
from dotenv import load_dotenv

from electricity_optimizer.ingestion import read_pdf
from electricity_optimizer.pricing_schema import (
    PricingCandidate, PlanIdentity, assess_pricing, normalized_kwh_rate,
)
from electricity_optimizer.pricing_extraction import (
    PricingRecord, build_pricing_workflow, load_pricing_record, save_pricing_record,
)
from electricity_optimizer.pricing_examples import teaching_examples

ROOT = Path.cwd()
CONTRACTS = ROOT / "contracts"
OUTPUT = ROOT / "output/lesson09"
RECORDS = OUTPUT / "records"
if not (ROOT / "electricity_optimizer").is_dir():
    raise FileNotFoundError("Open this notebook from the project root.")

def show_table(rows, columns):
    header = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(row.get(c, '')))}</td>" for c in columns) + "</tr>" for row in rows)
    display(HTML(f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"))

print("Python:", sys.executable)
print("Available PDFs:")
for path in sorted(CONTRACTS.glob("*")):
    if path.is_file() and path.suffix.lower() == ".pdf":
        print(" -", path.name)''')
md("""## 2. Understand the shared schema

A **schema** specifies the fields every provider's extracted result must contain. Pydantic checks types and structure. Our additional checks verify quotes and some consistency rules. Neither proves that every clause has been interpreted correctly.

| Part | What it stores |
|---|---|
| `identity` | Provider, plan, country, territory, currency, customer type, date and contract terms |
| `coverage` | Whether each charge category is present, explicitly absent, missing or ambiguous |
| `rules` | Original amounts/units, rule types, thresholds, tiers, time windows, conditions and citations |
| `unresolved_terms` | Anything that cannot be represented confidently |
| `supporting_documents_needed` | Missing rate schedules or other supporting material |

`not_stated` means **unknown**, never zero. `explicit_none` needs evidence explicitly ruling out a charge. Monetary amounts are decimal strings to preserve precision. We retain `10 cents_per_kwh` and let Python convert it to `0.10 currency_per_kwh`.

Tiered, time-of-use, demand and indexed rules can be recorded for review, but their full calculators are future work. Complex conditions remain text for review; the program does not execute model-generated expressions.""")
code('''schema = PricingCandidate.model_json_schema()
show_table([{"field": name, "description": details.get("description", "Structured field")}
            for name, details in schema["properties"].items()], ["field", "description"])
print("Required identity fields:", ", ".join(PlanIdentity.model_fields))''')
md("""## 3. Choose example, live or replay mode

Leave **example** selected for your first run.

- `example`: two authored fictional examples; no key and no network calls.
- `live`: sends extracted text/table cells from the selected PDFs to **GPT-5**. This incurs API usage. Rerunning Section 4 in live mode makes new calls. Begin with one PDF.
- `replay`: loads **Notebook 09 pricing records**, checks their PDF fingerprints and reruns validation with no API calls. Old Notebook 02 agreement JSONs use a different schema and cannot be replayed here.

For live mode, put your key in the existing `.env`, change `MODE` below, and rerun Sections 3–7. The key is loaded only in live mode and is never printed. For replay, paste the saved record paths printed by Section 4 into `REPLAY_FILES`. Replay never falls back to live calls.

All top-level PDFs can use this same extractor. To select them all, replace `SELECTED_PDFS` with the commented expression, after trying one file.""")
code('''MODE = "example"  # "example", "live", or "replay"
MODEL = "gpt-5"
SELECTED_PDFS = ["R1F00166003766B.pdf"]
# SELECTED_PDFS = sorted(p.name for p in CONTRACTS.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
REPLAY_FILES = []  # Example: ["output/lesson09/records/pricing_<id>.json"]

if MODE not in {"example", "live", "replay"}:
    raise ValueError("Choose example, live, or replay.")
if MODE == "live":
    load_dotenv(ROOT / ".env", override=False)
    print("LIVE: Section 4 will send", len(SELECTED_PDFS), "selected PDF(s) to", MODEL)
elif MODE == "replay":
    print("REPLAY: only saved Notebook 09 records will be read.")
else:
    print("EXAMPLE: manually authored fictional data; no API calls.")''')
md("""## 4. Run extraction → validation → supervisor

The LangGraph workflow has one LLM extraction step in live mode. Validation and the supervisor's routing are deterministic Python functions. These are foundations for the final multi-agent system, not a claim that the entire system is finished.

The supervisor chooses among four next steps:

| Route | Meaning |
|---|---|
| `needs_evidence_review` | A quote, page, field or rule-consistency check failed |
| `needs_information` | Required context or prices are unknown/ambiguous |
| `needs_pricing_engine` | Rules require additional calculation logic or usage detail |
| `candidate_for_pricing_review` | Initial checks passed; interpretation still needs review before calculation |

Each successful live result is saved immediately to its own record file. Failures are reported per PDF, so one bad document does not hide the other results. Input is limited to 150,000 characters including table cells; oversized PDFs are rejected without truncation. OCR, chunking and automatic multi-document linking are later extensions.""")
code('''runs, failures = [], []
workflow = build_pricing_workflow(mode="live" if MODE == "live" else "replay", model=MODEL)

def selected_pdf(name):
    path = (CONTRACTS / name).resolve()
    if path.parent != CONTRACTS.resolve() or path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("Select an existing top-level PDF in contracts/.")
    return path

if MODE == "example":
    for document, record in teaching_examples():
        state = workflow.invoke({"document": document, "record": record})
        runs.append({"state": state, "saved_record": None})
else:
    selections = SELECTED_PDFS if MODE == "live" else REPLAY_FILES
    if not selections:
        raise ValueError("Select PDFs for live mode or Notebook 09 record paths for replay, then rerun Section 3.")
    for selection in dict.fromkeys(selections):
        try:
            if MODE == "live":
                document = read_pdf(selected_pdf(selection), include_tables=True)
                state = workflow.invoke({"document": document})
                saved = save_pricing_record(state["record"], RECORDS)
            else:
                saved = (ROOT / selection).resolve()
                header = PricingRecord.model_validate_json(saved.read_text(encoding="utf-8"))
                if header.origin != "live":
                    raise ValueError("Use example mode for authored examples; replay expects a saved live PDF extraction.")
                document = read_pdf(selected_pdf(header.source_file), include_tables=True)
                record = load_pricing_record(saved, document)
                state = workflow.invoke({"document": document, "record": record})
            runs.append({"state": state, "saved_record": str(saved)})
            print("Saved/replayed record:", saved)
        except Exception as exc:
            failures.append({"selection": selection, "error": str(exc)})

show_table([{"source": r["state"]["document"].source_file,
             "origin": r["state"]["record"].origin,
             "route": r["state"]["route"], "approved": False} for r in runs],
           ["source", "origin", "route", "approved"])
if failures:
    show_table(failures, ["selection", "error"])
print("Completed:", len(runs), "Failed:", len(failures))''')
md("""## 5. Inspect one result and its evidence

Change `RESULT_INDEX` to select another result. For a real PDF, open the named source and compare the quoted page with the amount, unit, boundary and conditions. For example mode, the authored source text is printed below.

The first example should reach `candidate_for_pricing_review`. The second should need a pricing engine and usage by time period. They use the same schema despite different pricing structures.

The per-kWh conversion column is only a unit demonstration, not a calculated bill. A matching quote does not prove that an extracted amount is correct or that omitted charges do not exist.""")
code('''RESULT_INDEX = 0
if runs:
    if not 0 <= RESULT_INDEX < len(runs):
        raise ValueError("RESULT_INDEX must identify one of the completed results.")
    selected = runs[RESULT_INDEX]["state"]
    candidate = selected["record"].candidate
    print("Source:", selected["document"].source_file)
    print("Route:", selected["route"])
    if MODE == "example":
        print("\\nAUTHORED SOURCE TEXT:\\n", selected["document"].pages[0].text)
    show_table([{"field": name, "status": getattr(candidate.identity, name).status,
                 "value": getattr(candidate.identity, name).value,
                 "evidence": [c.model_dump() for c in getattr(candidate.identity, name).citations]}
                for name in PlanIdentity.model_fields], ["field", "status", "value", "evidence"])
    show_table([c.model_dump() for c in candidate.coverage], ["component", "status", "explanation", "citations"])
    rows = []
    for rule in candidate.rules:
        converted = str(normalized_kwh_rate(rule)) if rule.amount is not None and rule.unit in {"cents_per_kwh", "currency_per_kwh"} else "n/a"
        rows.append({"rule": rule.label, "kind": rule.kind, "amount": rule.amount,
                     "unit": rule.unit, "currency/kWh": converted,
                     "conditions": rule.conditions, "time window": rule.time_window,
                     "lower kWh": rule.lower_kwh, "lower inclusive": rule.lower_inclusive,
                     "upper kWh": rule.upper_kwh, "upper inclusive": rule.upper_inclusive,
                     "bands": [b.model_dump() for b in rule.bands],
                     "evidence": [c.model_dump() for c in rule.citations]})
    show_table(rows, ["rule", "kind", "amount", "unit", "currency/kWh", "lower kWh", "lower inclusive", "upper kWh", "upper inclusive", "bands", "time window", "conditions", "evidence"])
    assessment = selected["assessment"]
    show_table(assessment["issues"], ["severity", "field", "message"])
    for reason in assessment["missing_information"] + assessment["engine_work"]:
        print(" -", reason)
    print(assessment["next_step"])
else:
    print("No successful results. Review Section 4 failures before continuing.")''')
md("""## 6. Try a deliberately incorrect quote (offline)

This exercise changes a **copy of the fictional example**, then checks it again. It should route to `needs_evidence_review` because the cited rate never appeared in the source. Your live results are unaffected.

This test catches a fabricated quote. It cannot catch every semantic error—for example, citing the correct sentence but assigning its number to the wrong charge category. That is why review/evaluation remains a separate step.""")
code('''example_document, example_record = teaching_examples()[0]
changed = example_record.candidate.model_copy(deep=True)
energy_rule = next(r for r in changed.rules if r.component == "energy")
energy_rule.citations[0].quote = "Energy: 99 cents per kWh at all hours."
exercise = assess_pricing(changed, example_document)
print("Deliberately incorrect quote ->", exercise["route"])
show_table(exercise["issues"], ["severity", "field", "message"])''')
md("""## 7. Save the review summary

The summary includes successful candidates, source fingerprints, issues, next steps and failures. It records whether the input was an authored example, live extraction or replay. Saving does not approve any plan. Live record files from Section 4 can be replayed even if you never run this section.""")
code('''OUTPUT.mkdir(parents=True, exist_ok=True)
report = {
    "lesson": "09_general_pricing_extraction", "mode": MODE,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "approved_for_comparison": False,
    "scope": "Extraction and review routing only; no cost calculation or ranking.",
    "results": [{"record": r["state"]["record"].model_dump(mode="json"),
                 "assessment": r["state"]["assessment"], "saved_record": r["saved_record"]}
                for r in runs],
    "failures": failures,
}
summary_path = OUTPUT / f"{MODE}_pricing_review_summary.json"
summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Saved:", summary_path)
print("Next: inspect the evidence, then connect reviewed standard rules to the cost calculator.")''')
md("""## What this adds to the final project

The upload workflow can now ask GPT-5 for the same pricing structure across providers. Provider-specific regex adapters are no longer required for this extraction stage. Missing documents and unsupported calculations still need explicit handling.

Next, we will turn a supported subset of reviewed rules into executable pricing, compare compatible plans against the same 12 months of usage, and feed those results to recommendation/negotiation agents. Time-of-use and demand plans will require finer usage data. The full multi-agent supervisor and upload interface remain later work.

Implementation references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [GPT-5](https://developers.openai.com/api/docs/models/gpt-5). The SDK parses the response into Pydantic models; source and pricing validation are our separate responsibilities.""")
nb.cells = cells
nb.metadata = {"kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
               "language_info": {"name": "python"}}
nbf.validate(nb)
nbf.write(nb, Path(__file__).parent / "09_general_pricing_extraction.ipynb")
