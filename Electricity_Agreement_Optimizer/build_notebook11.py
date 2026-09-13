"""Generate the unexecuted Notebook 11 teaching artifact."""
from pathlib import Path
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))

md("""# 11 — Comparison explanations and negotiation insights

Notebook 10 calculated the modeled costs. Here we explain their tradeoffs and draft questions a customer could ask a provider. **Python owns the calculations; GPT-5 optionally drafts the wording.**

The first run uses an **offline template built from your real saved comparison**, not invented model output. It makes no API calls. It works even if Notebook 10 is still marked `unreviewed_scenario_preview`; that status remains visible.

Run Sections **1–8** in order with your `.venv` kernel. You only need Notebook 10's saved report and its original PDFs. This lesson drafts questions; it does not contact providers or change agreements.""")
md("## 1. Imports and report path\nThe report contains the input records, compiled plans, usage, exclusions and calculated bills. Notebook 11 reads these without modifying them.")
code('''from pathlib import Path
from datetime import datetime, timezone
from html import escape
import json
import sys
from IPython.display import HTML, display
from dotenv import load_dotenv

from electricity_optimizer.insight_context import load_insight_context, InsightPreferences
from electricity_optimizer.insights import (
    InsightRecord, build_insight_workflow, validate_insights,
    save_insight_record, load_insight_record,
)
from electricity_optimizer.rule_compiler import fingerprint

ROOT = Path.cwd()
REPORT_PATH = ROOT / "output/lesson10/general_rule_comparison.json"
CONTRACTS = ROOT / "contracts"
OUTPUT = ROOT / "output/lesson11"
INSIGHT_RECORDS = OUTPUT / "records"
if not REPORT_PATH.is_file():
    raise FileNotFoundError("Run Section 8 of Notebook 10 to save its comparison report first.")

def show_table(rows, columns):
    header = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(r.get(c, '')))}</td>" for c in columns) + "</tr>" for r in rows)
    display(HTML(f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"))

print("Python:", sys.executable)
print("Input:", REPORT_PATH)''')
md("""## 2. Set preferences and verify the comparison

`priority` can be `balanced`, `modeled_cost`, or `shorter_commitment`. `max_contract_months` is optional. These preferences affect which candidate to investigate; they do not change prices, prove eligibility, or make the subtotal a full bill.

For your first run, keep the defaults. Later, try `max_contract_months=12` to exclude longer commitments from your shortlist. This does not change the global cost comparison. If no plan meets your limit, the system says so.

Before drafting, Python checks PDF fingerprints and quotes, rebuilds each compiled plan, and recalculates the monthly bills. Changed costs or stale evidence stop here. Review status is checked against the saved review fingerprints; no checkbox or review is approved automatically.""")
code('''PREFERENCES = InsightPreferences(priority="balanced", max_contract_months=None)
context = load_insight_context(REPORT_PATH, CONTRACTS, PREFERENCES)
print("Input review status:", context["review_status"])
print("Usage:", "SYNTHETIC" if context["synthetic_usage"] else "User-provided actual usage")
print("Comparison:", context["comparison"]["status"])
print(context["comparison"]["explanation"])
for warning in context["review_warnings"]:
    print("Review note:", warning)
show_table(context["plan_summaries"],
           ["id", "name", "contract_months", "annual_subtotal_usd"])
print(next(f["text"] for f in context["facts"] if f["id"] == "preferences"))''')
md("""## 3. Inspect the evidence provided to the writer

Every fact has an ID. Calculated facts such as `comparison` come from Python. Source interpretations have PDF filenames and exact page quotes. Scenario assumptions and unresolved terms have separate labels.

The writer must cite these IDs. `P1` means the first plan in the recalculated cost ordering, not necessarily the plan that best matches your preferences. Select a fact below to see its full evidence. The optional API request includes these curated facts, not your key, reviewer name or local absolute paths.""")
code('''facts = {f["id"]: f for f in context["facts"]}
show_table([{"id": f["id"], "kind": f["kind"], "source": f["source_file"],
             "preview": f["text"][:180]} for f in facts.values()],
           ["id", "kind", "source", "preview"])

SELECTED_FACT_ID = "P1.termination_terms" if context["plan_summaries"] else "scope"
if SELECTED_FACT_ID not in facts:
    raise ValueError("Choose an ID from the evidence table.")
selected_fact = facts[SELECTED_FACT_ID]
print(selected_fact["text"])
show_table(selected_fact["citations"], ["page_number", "quote"])''')
md("""## 4. Choose offline, live or replay

Leave `MODE = "offline"` for the first run. The offline template already produces a useful explanation and questions from your comparison.

- **offline:** deterministic template, no API key or calls.
- **live:** one GPT-5 request for both plans together in Section 5. It sends the curated facts and preferences and incurs API usage. Your existing `.env` supplies the key.
- **replay:** reuse a saved insight record with no API calls. By default, the newest matching live record is selected automatically. A changed report or preference requires a new matching record; replay never calls the API as a fallback.

For live mode, change `MODE`, rerun this section, then run Section 5 once. Sections 6–8 never make API calls. A returned draft is saved in Section 5 even when its evidence checks flag issues.""")
code('''MODE = "offline"  # "offline", "live", or "replay"
MODEL = "gpt-5"
REPLAY_FILE = None  # None finds the newest matching live insight record automatically.

if MODE not in {"offline", "live", "replay"}:
    raise ValueError("Choose offline, live, or replay.")
if MODE == "live":
    load_dotenv(ROOT / ".env", override=False)
    print("LIVE: Section 5 will make one GPT-5 request using the curated comparison facts.")
else:
    print(MODE.upper() + ": no API calls.")''')
md("""## 5. Draft → validate → supervisor

The LangGraph workflow creates the draft, checks its evidence IDs and numeric references, then assigns a route. It flags unknown references, numbers absent from cited facts, and a small set of overconfident claims. These checks do **not** prove that a sentence correctly interprets its evidence.

`draft_for_human_review` means initial checks passed. `needs_output_review` means the draft contains flagged items. Neither route approves a contract recommendation. With fewer than two comparable plans, offline mode remains useful for identifying the next information needed; live drafting is disabled.""")
code('''workflow = build_insight_workflow(MODE, model=MODEL)
state_input = {"context": context}
saved_insight_path = None

if MODE == "replay":
    if REPLAY_FILE:
        saved_insight_path = (ROOT / REPLAY_FILE).resolve()
        state_input["record"] = load_insight_record(saved_insight_path, context)
    else:
        matching = []
        for path in sorted(INSIGHT_RECORDS.glob("*.json")):
            try:
                record = InsightRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if record.origin != "live" or record.context_fingerprint != fingerprint(context):
                    continue
                record = load_insight_record(path, context)
                stamp = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Timestamp has no timezone.")
                matching.append((stamp, path.name, path, record))
            except (ValueError, OSError) as exc:
                print("Skipped saved record:", path.name, type(exc).__name__)
        if not matching:
            raise ValueError("No matching live insight record. Use offline mode or deliberately run live once.")
        _, _, saved_insight_path, state_input["record"] = max(matching, key=lambda x: (x[0], x[1]))

insight_result = workflow.invoke(state_input)
if MODE == "live":
    saved_insight_path = save_insight_record(insight_result["record"], INSIGHT_RECORDS)
if saved_insight_path:
    print("Saved/replayed:", saved_insight_path)
print("Draft origin:", insight_result["record"].origin)
print("Route:", insight_result["route"])
show_table(insight_result["issues"], ["field", "message"])''')
md("""## 6. Read the explanation and negotiation questions

The fixed cost table and scenario labels below always come from Python. Draft text cannot replace the calculated results. Each sentence or question lists the fact IDs supporting it; expand the evidence to inspect the source.

For your saved comparison, look for the tradeoff between a lower first-year modeled subtotal and a longer commitment, the unused usage credit, termination exceptions, and unresolved delivery/other fees. Questions about better rates or fee reductions are proposed requests, not promises that the provider will agree.

Review factual meaning as well as the IDs. A sentence may cite a real fact and still misinterpret it. Input scenario review from Notebook 10 does not automatically review this new prose.""")
code('''print("DRAFT FOR REVIEW |", context["review_status"])
print("Usage:", "SYNTHETIC" if context["synthetic_usage"] else "User-provided actual usage")
print("Scope: modeled subtotals only; excluded fees and eligibility remain unresolved.")
print("Negotiation questions are requests, not confirmed concessions. No provider was contacted.")
show_table(context["plan_summaries"], ["name", "annual_subtotal_usd", "contract_months"])
draft = insight_result["record"].draft
for section in type(draft).model_fields:
    content = f"<h3>{escape(section.replace('_', ' ').title())}</h3>"
    for item in getattr(draft, section):
        content += f"<p>{escape(item.text)}</p><details><summary>Evidence: {escape(', '.join(item.fact_ids))}</summary>"
        for identifier in item.fact_ids:
            evidence = facts.get(identifier)
            if not evidence:
                content += f"<p>UNKNOWN REFERENCE: {escape(identifier)}</p>"
                continue
            content += f"<p><b>{escape(identifier)} ({escape(evidence['kind'])})</b>: {escape(evidence['text'])}</p>"
            for cite in evidence["citations"]:
                content += f"<blockquote>{escape(str(evidence['source_file']))}, page {cite['page_number']}: {escape(cite['quote'])}</blockquote>"
        content += "</details>"
    display(HTML(content))
if insight_result["issues"]:
    print("Flagged draft: resolve the listed issues before reusing its wording.")''')
md("""## 7. See an unsupported number get flagged (offline)

This changes a copy of the draft to claim an invented amount while citing `comparison`. The checker should flag that amount. It does not modify your original draft or call the API.

This is a limited check: reusing a real number for the wrong meaning may still pass. End-to-end evaluation and review remain necessary.""")
code('''changed_draft = draft.model_copy(deep=True)
changed_draft.explanation[0].text = "The modeled difference is USD 999999.99."
changed_draft.explanation[0].fact_ids = ["comparison"]
exercise_issues = validate_insights(changed_draft, context)
show_table(exercise_issues, ["field", "message"])''')
md("""## 8. Save the explanation and a readable text copy

The JSON stores the context fingerprint, facts, preferences, input review status, draft origin, model metadata and validation issues. The text file includes the fixed comparison, limitations, draft and supporting facts.

These are draft artifacts. Saving does not change the Notebook 10 review or approve the new wording. You can rerun this section without another API call. If the report or preferences changed since drafting, it asks you to refresh the context instead of saving a mismatched result.""")
code('''if PREFERENCES.model_dump(mode="json") != context["preferences"]:
    raise ValueError("Preferences changed. Rerun Sections 2-6 before saving.")
if fingerprint(json.loads(REPORT_PATH.read_text(encoding="utf-8"))) != context["report_fingerprint"]:
    raise ValueError("Notebook 10 report changed. Rerun Sections 2-6 before saving.")
if insight_result["record"].context_fingerprint != fingerprint(context):
    raise ValueError("The context changed after drafting; refresh the draft before saving.")

OUTPUT.mkdir(parents=True, exist_ok=True)
report = {
    "lesson": "11_explanations_and_negotiation", "mode": MODE,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "status": insight_result["route"], "approved_for_real_plan_recommendation": False,
    "prose_review_status": "unreviewed_draft",
    "context": context, "record": insight_result["record"].model_dump(mode="json"),
    "issues": insight_result["issues"],
}
json_path = OUTPUT / f"{MODE}_insights.json"
json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

lines = ["ELECTRICITY COMPARISON — DRAFT FOR REVIEW", f"Origin: {insight_result['record'].origin}",
         f"Input status: {context['review_status']}", f"Synthetic usage: {context['synthetic_usage']}",
         "Modeled subtotals, not complete bills; eligibility is unverified.",
         "Questions are requests, not promised concessions. No provider was contacted.",
         "", "PYTHON-CALCULATED COMPARISON", context["comparison"]["explanation"], "",
         "SCENARIO ASSUMPTIONS", facts["scope"]["text"], ""]
for section in type(draft).model_fields:
    lines.append(section.replace("_", " ").upper())
    for item in getattr(draft, section):
        lines.append(item.text + " [" + ", ".join(item.fact_ids) + "]")
    lines.append("")
lines.extend(["VALIDATION ISSUES", json.dumps(insight_result["issues"], indent=2), "", "SUPPORTING FACTS"])
for fact in context["facts"]:
    lines.append(f"[{fact['id']}] {fact['kind']}: {fact['text']}")
    for cite in fact["citations"]:
        lines.append(f"  {fact['source_file']}, page {cite['page_number']}: {cite['quote']}")
text_path = OUTPUT / f"{MODE}_explanation.txt"
text_path.write_text("\\n".join(lines), encoding="utf-8")
print("Saved JSON:", json_path)
print("Saved readable draft:", text_path)''')
md("""## What comes next

We now have source extraction, general-rule compilation, comparison, and explanation/question drafting. Notebook 12 will join these stages under the full supervisor workflow; Notebook 13 will evaluate the complete system.

Optional exercise: stay offline, set a twelve-month maximum in Section 2, and rerun Sections 2–8. The global cost difference stays the same; the preference shortlist changes. Do not rerun Section 5 in live mode unless you intend another API request.

The optional GPT-5 integration follows [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and the [GPT-5 model documentation](https://developers.openai.com/api/docs/models/gpt-5). Schema parsing, numeric/reference checks and human interpretation are separate responsibilities.""")
nb.cells = cells
nb.metadata = {"kernelspec": {"display_name": "Python (.venv)", "language": "python", "name": "python3"},
               "language_info": {"name": "python"}}
nbf.validate(nb)
nbf.write(nb, Path(__file__).parent / "11_recommendations_and_negotiation.ipynb")
