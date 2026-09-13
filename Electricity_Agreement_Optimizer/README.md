# Electricity Agreement Optimizer

Compare electricity agreements against 12 months of usage. We are building this
in learning-sized stages: AI interprets terms; Python will calculate costs.

## Step 1: Read and inspect PDFs (implemented)

### Recommended learning workflow: Jupyter in VS Code

Open `01_pdf_ingestion.ipynb` in the project root. Install the Microsoft Jupyter
extension in VS Code if prompted. Choose **Select Kernel > Python Environments**
and select `.venv/Scripts/python.exe`. Run cells from top to bottom with Shift+Enter.
The notebook explains each step and calls the same reusable Python modules as the CLI.
Future learning stages will also use notebooks.

To recreate the notebook environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-notebook.txt
```

You do not need to start a separate Jupyter server for VS Code. After changing a
Python module, restart the notebook kernel and run all cells to reload it.
Notebook outputs can contain agreement text; clear outputs before sharing.

### Optional command-line workflow

Run these commands in PowerShell from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m electricity_optimizer inspect
```

If `.venv` already exists, skip the first command. Activation is unnecessary.
No API key is needed for this stage. Processing happens locally.

### How the code works

1. `__main__.py` finds PDFs directly inside `contracts/` and coordinates inspection.
2. `ingestion.py` opens each PDF with PyMuPDF and extracts text page by page.
3. `models.py` uses Pydantic to define the shape of the results and validate them.
4. The command saves readable `.txt` files and `report.json` under `output/inspection/`.

The JSON stores the source filename, a SHA-256 fingerprint, page numbers, text,
and review flags. Preserving page numbers now lets later recommendations cite
their source. A fingerprint identifies the exact file even if its name changes.

Pages with fewer than 40 non-whitespace characters are flagged for review.
This can mean a scan, a blank page, or a sparse cover; OCR is not implemented yet.
Text extraction does not prove tables or columns were read correctly. Compare
important passages with the original before treating extracted terms as reliable.
Unreadable files are reported without stopping inspection of the remaining PDFs;
the command returns a nonzero exit code if any file fails.

Re-running refreshes outputs for the current inputs. `report.json` is the authoritative
list for that run; old text exports for removed PDFs may remain in the output folder.
Original contracts are never modified. Contracts, generated outputs, and `.env`
are excluded from future Git commits to reduce accidental exposure of personal data.

### Learning exercise

Open the Reliant text export alongside its original PDF. Locate the contract
length, energy charge, and termination fee. Then locate the same page in
`report.json`. This is the evidence the extraction agent will receive in Step 2.

## Step 2: Extract cited terms with GPT-5 (implemented; live run needs a key)

Open `02_contract_extraction.ipynb` and select the same `.venv` kernel.
The notebook explains the schema, provides a clearly labeled synthetic practice
example, previews the real PDF input, and runs one selected agreement through GPT-5.

1. Install updated packages: `.\.venv\Scripts\python.exe -m pip install -r requirements-notebook.txt`.
2. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` locally. Leave
   `OPENAI_MODEL=gpt-5` to use the model specified for this project.
3. Run notebook cells in order. Set `RUN_LIVE_EXTRACTION = True` in the live cell
   when ready. This sends the selected PDF's extracted text to OpenAI and uses
   your API account. It does not upload other contracts. Rerunning sends another request.

The Responses API parses output into `AgreementTerms` using Pydantic. Every field
records `found`, `not_stated`, or `ambiguous`, with a value and supporting quotes.
Unknown fees remain unknown; they do not become zero. Units and conditions remain
in text for human review; this schema is not yet an executable pricing model.

`extraction.py` checks that quoted text exists on the cited page (allowing whitespace
differences), flags missing or ambiguous values, and attaches local provenance.
Quote matching does **not** prove that the quote supports the interpretation or
that all clauses were found. Every result remains `needs_human_review`.
Structured output ensures shape, not factual accuracy.

Full documents up to 150,000 input JSON characters are supported in this lesson.
Larger documents fail explicitly instead of losing pages. OCR and chunking come later.
Refusals, incomplete results, and API errors do not produce accepted extraction records.
No automatic retries are enabled. API response storage is disabled with `store=False`;
this does not replace OpenAI's applicable data retention policies.

Saved live results go under `output/extraction/`; practice examples are never saved
as real extractions. No live extraction was verified during setup because no key
was configured. Run the offline regression checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

References: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5](https://developers.openai.com/api/docs/models/gpt-5).

## Step 3: LangGraph orchestration

Open `03_langgraph_workflow.ipynb`, select `.venv`, and run from the top. It is
self-contained and defaults to replaying a saved Step 2 record without an API call.
Select the PDF and matching JSON explicitly in the notebook. A source fingerprint
check rejects mismatched documents; replay never falls back to live extraction.

`workflow.py` builds a `StateGraph` with loading, extraction/replay, validation,
supervisor, correction, human-review, and failure nodes. Nodes return partial state
updates; conditional edges decide what runs next. Validation errors route to
correction; warnings or no issues route to human review. Neither route approves a
plan for calculation. The saved record's issues are recalculated from the PDF.

This stage has a rule-based supervisor and one AI extraction capability. It is
the foundation for the planned multi-agent system, not yet several reasoning agents.
Review nodes end the run with a review status; persistent checkpoints, interrupts,
human approval/resume, and automatic correction loops are not implemented yet.
The notebook can optionally run live extraction once you select live mode.

Reference: [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api).

## Remaining stages

Notebook 03 now includes a layout lesson before Section 7. Restart the kernel and
run in replay mode. `read_pdf(..., include_tables=True)` preserves plain page text
and adds detected cells with table/row/column numbers and PDF bounding boxes.
The lesson rechecks citations within individual cells and displays a crop of the
original fee cell. It leaves the saved extraction and original workflow state intact.
Table detection is optional, with plain-text fallback and explicit detection warnings.
It is not OCR and does not guarantee every table is detected correctly. The main workflow now enables table detection for citation validation and saves
that updated outcome. Standalone reading still defaults to plain text. Live API
input remains plain page text; table cells supplement local validation.

## Step 4: Synthetic usage and deterministic costs

Open `04_usage_and_costs.ipynb` with `.venv` and run from the top. No other notebook
or API key is needed. It generates an explicitly synthetic CSV intermediate in
`output/lesson04_synthetic/`, validates 12 consecutive months, and compares two
fictional fixed-rate plans. `usage.py` rejects missing/duplicate months, negative
or nonfinite consumption. `pricing.py` uses Decimal arithmetic for energy, base,
delivery and monthly threshold-credit components. The notebook includes a hand
calculation, threshold experiment, monthly breakdown, and consumption scenario.

The fictional rules round each component to cents half up and cap the credit at
the subtotal. Rates stay constant across the year. Taxes, switching costs, time-of-use,
tiers, renewals and actual-provider conversion are not implemented in this lesson.
The saved JSON records assumptions, inputs and base-case results; scenario results
remain in the notebook. All results are teaching examples, not real plan recommendations.

## Step 5: Comparison workflow and explanations

Open `05_comparison_workflow.ipynb` with `.venv`. It loads the synthetic inputs
saved by Notebook 04 Section 9, recalculates costs, and runs validation, calculation
and explanation nodes through LangGraph. All steps are local; no API key is needed.
Explanations are deterministic prose built from monthly bills, including ties and
credited months. The notebook demonstrates the base year, a 20% usage increase,
and an invalid 11-month input that stops before calculation.

The base report is saved under `output/lesson05_synthetic/` with inputs, trace,
explanation and monthly evidence. This is a separate comparison graph, not yet
connected to real PDF extractions. An explicit reviewed-pricing conversion step
is needed before joining it to the document supervisor. No real contract is approved
or priced by this lesson.

## Step 6: Review real pricing inputs

Section 4 now provides an ipywidgets review form. Expand each field to edit its
value and source/page quotes, enter reviewer/date once, and select only fields
you have checked. Save review & check writes the draft and displays remaining
blockers. Rendering the form never saves or approves fields. Existing reviews
survive unchanged values/evidence; edits clear prior review unless explicitly
reviewed again. A backup is saved, and external edits are protected from overwrites.
The narrow candidate converter recognizes exact cited energy charges in cents/kWh
and divides by 100. It does not infer currency or unknown fees, and candidates
remain unapproved. Restart the kernel after updating notebook dependencies.
After saving, rerun Sections 5–7 to refresh downstream results.

Open `06_reviewed_pricing.ipynb` with `.venv`. It uses the saved Reliant workflow
report from Notebook 03 and creates `output/review/Reliant_pricing_review.json`
only if that draft does not exist. The draft preserves unapproved candidates and
requires explicit values, source/page quotes, reviewer names and dates. Zero charges
also require evidence. Additional matching PDF sources can be listed in the notebook.

The expected initial result is blocked; unknown fees are not inferred. `review.py`
checks evidence and supported scope before compiling a real fixed-rate plan for
the shared monthly arithmetic. This first adapter supports USD flat rates without
credits, tiers, time-of-use or minimum bills. It can calculate an energy/base/delivery
subtotal with synthetic usage after review, under constant rates and explicit rounding.
It excludes taxes, switching charges and deposits; it is not a forecast or a current
offer check. Source matches do not establish semantic correctness or eligibility.
The reviewer entries are an audit trail, not authenticated approval.

Readiness reports retain blockers and the review snapshot. Notebook 05 remains a
fictional comparison graph; real-plan ranking and supervisor integration require
compatible, complete reviewed inputs and are not enabled by this lesson.

## Step 7: Compare source-backed Power Savings examples

Open `07_real_plan_comparison.ipynb` with `.venv`. It uses the two downloaded Power
Savings PDFs, matching saved extraction records, and Notebook 04 synthetic usage.
No live API calls occur. The narrow `efl_comparison.py` adapter reads labeled fields
directly from the PDF and retains exact quotes, page numbers and file fingerprints.
It rejects missing/conflicting values and mismatched territory, currency or dates.
AI extraction issues are displayed separately; model output is not silently approved.

The lesson uses the downloaded snapshot dates/rates (which can differ from earlier
web-search results), evaluates inclusive usage credits, and compares 12 months only.
It includes a threshold exercise, higher-usage scenario and contract-length discussion.
It excludes taxes, switching charges, changing tariffs and special-territory adjustments;
listed delivery totals are used without independently estimating an ITR adjustment.
The report in `output/lesson07/` is labeled an unapproved demonstration with synthetic
usage. Notebook 06's original incomplete real-plan review remains separate.

## Step 8: Inventory and compare the portfolio

Open `08_portfolio_comparison.ipynb` with the project `.venv` kernel and run sections
in order. It scans every top-level PDF, audits available matching saved extractions,
and groups supported source prices by territory, currency and PDF date. No API calls
are made. Unsupported, unreadable, duplicate and incomplete documents remain visible
with reasons; missing saved extractions and citation errors are reported separately.
Only the existing Power Savings adapter is supported, and results remain unapproved
demonstrations using Notebook 04's synthetic usage. The complete inventory, evidence,
assumptions and bills are saved to `output/lesson08/portfolio_comparison.json`.

## Step 9: General pricing schema and GPT-5 extraction

Open `09_general_pricing_extraction.ipynb` with `.venv` and run Sections 1–7.
Default `MODE = "example"` uses two explicitly authored fictional page-text/answer
pairs, not real PDF or model extraction results. No prior notebook kernel or API key
is needed. It demonstrates the provider-independent schema, exact citation checks,
unit conversion and LangGraph supervisor routes.

In Section 3, `MODE = "live"` sends the selected PDFs' extracted text and table cells
to GPT-5 through Structured Outputs. Start with one PDF. Each run incurs API usage;
there are no automatic retries. New source-bound records are saved under
`output/lesson09/records/`. Use `MODE = "replay"` with those record paths for offline
revalidation; mismatched fingerprints/versions are rejected without a live fallback.
Notebook 02 agreement records are a different schema and are not accepted here.
Mode-specific review summaries are saved in `output/lesson09/`.

`pricing_schema.py` retains original units, thresholds, tier bands, time windows,
conditions, charge coverage and source quotes. `pricing_extraction.py` provides the
general extraction and review-routing graph. One graph node calls an LLM in live
mode; validation and routing are deterministic. No result is automatically approved
or ranked. Tiered/time-of-use/indexed/demand descriptions still require appropriate
calculators, and monthly kWh alone cannot price time-of-use or demand charges.
This lesson does not replace Notebook 08's narrow calculation adapter. Linking the
new schema to reviewed calculations, compatibility checks and negotiation agents
is subsequent work. OCR, long-document chunking and multi-document linking remain
unsupported; this lesson rejects oversized inputs without truncation.

API references: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5](https://developers.openai.com/api/docs/models/gpt-5).

## Step 10: Compile general pricing rules and compare subtotals

Open `10_general_rule_comparison.ipynb` with `.venv` and run Sections 1–8. It discovers
the latest matching Notebook 09 pricing record for each PDF, revalidates source
fingerprints/quotes, and compiles a bounded subset of the general rule schema.
No live API call or provider-specific PDF pricing parser is used. The shared Python
calculator computes monthly and twelve-month subtotals with Notebook 04's usage.

Supported structures are one flat energy rate, fixed base charge, fixed plus per-kWh
delivery, and one inclusive lower-threshold monthly credit. Unsupported structures,
missing values, duplicate mappings and incompatible territory/dates are reported.
Every numeric conversion retains its source evidence and original units.

The current lesson explicitly models a standard-territory snapshot subtotal. Country,
USD and residential usage are labeled scenario assumptions when absent from the PDF.
The saved 24-month record's unpriced ITR rule has a visible, exact-rule-fingerprint
exclusion; it is not silently interpreted as zero. Taxes, termination, minimum/demand
charges and other fees remain outside the subtotal, not asserted absent. Conditions,
outstanding documents and exclusions are displayed for review.

Section 5 provides initially unchecked per-plan review controls. The preview runs
without asserting approval; Section 8 saves review decisions bound to the exact
record/scope/exclusions together with source records, compiled plans and monthly
bills in `output/lesson10/general_rule_comparison.json`. Existing source records and
Notebook 06 review files are preserved. This is not a complete-bill or eligibility
recommendation. Additional engines and recommendation agents remain future work.

## Step 11: Explain the comparison and draft negotiation questions

Open `11_recommendations_and_negotiation.ipynb` with `.venv` and run Sections 1–8.
The default offline template uses the saved Notebook 10 comparison and makes no
API calls. `insight_context.py` revalidates PDF fingerprints/quotes, recompiles plans
and recalculates bills before constructing a registry of calculated facts, source
interpretations, assumptions and unresolved terms. Changed inputs/results are rejected.
Scenario-review status is checked and retained; unreviewed reports can still be used
for clearly labeled draft explanations. Priority and optional maximum contract length
guide a shortlist without changing the cost table or claiming complete eligibility.

`insights.py` provides the LangGraph draft/validate/supervisor workflow. Optional live
mode makes one GPT-5 request for the curated facts and preferences, with no automatic
retries. Each returned live draft is saved to `output/lesson11/records/`; replay selects
the newest matching live record automatically, or accepts an explicit path. Context
fingerprints bind replay to the report and preferences; replay never falls back to a
paid call. Live inputs omit reviewer names and local absolute paths.

The fixed cost table is generated by Python. Draft items cite registry IDs; numeric
references and selected overconfident wording are checked. These checks do not prove
semantic correctness. Explanations and negotiation questions always remain drafts
for human review, even when Notebook 10 scenario inputs were reviewed. No provider
is contacted, concession guaranteed, or agreement modified. The lesson exports
mode-specific JSON and a readable text copy under `output/lesson11/`.

The optional API integration follows [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [GPT-5](https://developers.openai.com/api/docs/models/gpt-5).

## Remaining project work

4. Extend pricing to reviewed real plans and add applicable tiers and switching costs.
5. Rank compatible plans, explain assumptions, and suggest negotiation questions.
6. Add a Streamlit upload, review, and comparison interface.

The current sample set mixes US, UK, and Australian documents. They are useful
for extraction practice, but must not be ranked together as competing plans.
General terms also need a matching pricing schedule before cost calculation.
Historical sample prices are test fixtures, not current offers.

## Library references

- [PyMuPDF text extraction](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
