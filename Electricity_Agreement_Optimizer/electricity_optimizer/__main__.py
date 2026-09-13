"""Run with: python -m electricity_optimizer inspect"""

import argparse
from pathlib import Path

from .ingestion import read_pdf
from .models import InspectionFailure, InspectionReport


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect electricity agreement PDFs.")
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    parser.add_argument("--output", type=Path, default=Path("output/inspection"))
    args = parser.parse_args()
    if not args.contracts.is_dir():
        parser.error(f"Contracts directory does not exist: {args.contracts}")
    files = sorted(p for p in args.contracts.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not files:
        parser.error(f"No PDF files found in {args.contracts}")

    args.output.mkdir(parents=True, exist_ok=True)
    report = InspectionReport()
    for path in files:
        try:
            document = read_pdf(path)
        except (OSError, ValueError, RuntimeError) as error:
            report.failures.append(InspectionFailure(source_file=path.name, error=str(error)))
            print(f"FAILED {path.name}: {error}")
            continue
        report.documents.append(document)
        text = "\n\n".join(f"--- Page {p.page_number} ---\n{p.text}" for p in document.pages)
        (args.output / f"{path.name}.txt").write_text(text, encoding="utf-8")
        flagged = [p.page_number for p in document.pages if p.needs_review]
        characters = sum(len(p.text) for p in document.pages)
        print(f"OK {path.name}: {len(document.pages)} pages, {characters:,} characters; review pages: {flagged}")

    (args.output / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nRead {len(report.documents)}/{len(files)} PDFs. Report: {args.output / 'report.json'}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
