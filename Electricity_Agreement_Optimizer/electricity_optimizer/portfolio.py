"""Inventory every PDF and compare only supported source-backed demonstrations."""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .agreements import ExtractionRecord
from .efl_comparison import compare_efls, parse_power_savings
from .extraction import validate_terms
from .ingestion import read_pdf


def scan_portfolio(contracts: Path, extractions: Path) -> dict:
    """Read top-level PDFs only. One bad PDF or saved record cannot stop the scan."""
    if not contracts.is_dir():
        raise FileNotFoundError(f"Contracts folder not found: {contracts}")
    records, record_errors = [], []
    for path in sorted(extractions.glob("*.json")):
        try:
            record = ExtractionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(record.extracted_at.replace("Z", "+00:00"))
            stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
            records.append((stamp, path.name, record))
        except (ValueError, OSError) as exc:
            record_errors.append({"file": path.name, "error": str(exc)})
    rows, plans, seen = [], [], {}
    for path in sorted(contracts.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        row = {"file": path.name, "status": "unreadable", "reason": "",
               "extraction_status": "not_checked", "issues": []}
        rows.append(row)
        try:
            document = read_pdf(path, include_tables=True)
        except Exception as exc:
            row["reason"] = str(exc)
            continue
        row.update(sha256=document.sha256, pages=len(document.pages))
        matches = [r for r in records if r[2].source_file == document.source_file
                   and r[2].source_sha256 == document.sha256]
        if matches:
            _, record_name, record = max(matches, key=lambda r: (r[0], r[1]))
            row.update(extraction_status="saved_matching_unapproved", extraction_file=record_name,
                       issues=[i.model_dump() for i in validate_terms(record.terms, document)])
        else:
            stale = any(r[2].source_file == document.source_file for r in records)
            row["extraction_status"] = "stale_source_hash" if stale else "no_matching_saved_record"
        if document.sha256 in seen:
            row.update(status="duplicate", reason=f"Same PDF bytes as {seen[document.sha256]}; counted once.")
            continue
        seen[document.sha256] = path.name
        if any(p.needs_review for p in document.pages):
            row.update(status="needs_text_review", reason="At least one page has sparse text; inspect it or add OCR.")
            continue
        try:
            plan = parse_power_savings(document)
        except ValueError as exc:
            row.update(status="unsupported_or_incomplete", reason=str(exc) +
                       " Only the Power Savings 12/24 layout is supported; this does not prove the PDF lacks prices.")
            continue
        row.update(status="demo_ready", reason="Labeled PDF prices parsed independently; not human-approved.",
                   plan_name=plan.name)
        plans.append(plan)
    return {"inventory": rows, "plans": plans, "saved_record_errors": record_errors}


def compare_portfolio(scan: dict, usage) -> list[dict]:
    """Keep incompatible snapshots separate; never invent a winner for a singleton."""
    groups = defaultdict(list)
    for plan in scan["plans"]:
        groups[(plan.market, plan.currency, plan.document_date)].append(plan)
    output = []
    for (market, currency, date), plans in sorted(groups.items()):
        group = {"market": market, "currency": currency, "document_date": date,
                 "files": [p.source_file for p in plans], "results": []}
        if len(plans) < 2:
            group.update(status="waiting_for_comparable_plan", reason="Only one supported plan in this group.")
        else:
            try:
                results = compare_efls(usage, plans)
                group.update(status="demonstration_only", results=[r.model_dump(mode="json") for r in results])
            except ValueError as exc:
                group.update(status="needs_review", reason=str(exc))
        output.append(group)
    return output
