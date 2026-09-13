"""Step 3: explicit routing around extraction and local validation."""

from pathlib import Path
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .agreements import ExtractionRecord
from .extraction import extract_agreement, validate_terms
from .ingestion import read_pdf
from .models import PDFDocument


class WorkflowState(TypedDict, total=False):
    pdf_path: str
    document: PDFDocument | None
    record: ExtractionRecord | None
    error: str | None
    status: str
    trace: list[str]


def build_workflow(*, saved_record_path: Path | None = None,
                   live: bool = False,
                   extractor: Callable[[PDFDocument], ExtractionRecord] = extract_agreement):
    """Choose replay OR live explicitly. Replay never falls back to a paid call."""
    if live == (saved_record_path is not None):
        raise ValueError("Choose exactly one: saved_record_path for replay, or live=True.")

    def update(state, node, **changes):
        return {"trace": [*state.get("trace", []), node], **changes}

    def load_document(state):
        # Reset all output state for a fresh run, including after earlier failures.
        base = {"document": None, "record": None, "error": None,
                "status": "loading", "trace": ["load_document"]}
        try:
            # Keep plain text and detected cells for the same source PDF.
            base["document"] = read_pdf(Path(state["pdf_path"]), include_tables=True)
            base["status"] = "loaded"
        except (OSError, ValueError, RuntimeError) as error:
            base["error"] = f"PDF loading failed ({type(error).__name__}). Check the selected file."
        return base

    def extract_terms(state):
        try:
            document = state["document"]
            if saved_record_path is not None:
                record = ExtractionRecord.model_validate_json(saved_record_path.read_text(encoding="utf-8"))
            else:
                record = extractor(document)
            if record.source_sha256 != document.sha256 or record.source_file != document.source_file:
                return update(state, "extract_terms", error="Source mismatch: result does not belong to this PDF.", record=None)
            return update(state, "extract_terms", record=record, status="extracted")
        except (OSError, ValueError, RuntimeError) as error:
            return update(state, "extract_terms", record=None,
                          error=f"Extraction/replay failed ({type(error).__name__}). Check the record or API configuration.")

    def validate_evidence(state):
        record = state["record"]
        # Recompute issues: a saved result's old validation flags are not trusted.
        issues = validate_terms(record.terms, state["document"])
        return update(state, "validate_evidence", status="validated",
                      record=record.model_copy(update={"issues": issues, "review_status": "needs_human_review"}))

    def supervisor(state):
        has_errors = any(issue.severity == "error" for issue in state["record"].issues)
        return update(state, "supervisor", status="correction_required" if has_errors else "human_review_required")

    def correction(state):
        return update(state, "correction_required")

    def review(state):
        return update(state, "human_review")

    def failed(state):
        return update(state, "failed", status="failed", record=None)

    def after_load(state) -> Literal["extract_terms", "failed"]:
        return "failed" if state.get("error") else "extract_terms"

    def after_extract(state) -> Literal["validate_evidence", "failed"]:
        return "failed" if state.get("error") else "validate_evidence"

    def route_review(state) -> Literal["correction_required", "human_review"]:
        return "correction_required" if state["status"] == "correction_required" else "human_review"

    builder = StateGraph(WorkflowState)
    for name, node in [("load_document", load_document), ("extract_terms", extract_terms),
                       ("validate_evidence", validate_evidence), ("supervisor", supervisor),
                       ("correction_required", correction), ("human_review", review), ("failed", failed)]:
        builder.add_node(name, node)
    builder.add_edge(START, "load_document")
    builder.add_conditional_edges("load_document", after_load)
    builder.add_conditional_edges("extract_terms", after_extract)
    builder.add_edge("validate_evidence", "supervisor")
    builder.add_conditional_edges("supervisor", route_review)
    for terminal in ["correction_required", "human_review", "failed"]:
        builder.add_edge(terminal, END)
    return builder.compile()
