import csv
from pathlib import Path

import pymupdf

from .models import UsageHistory, UsageMonth


def read_pdf(path: str | Path) -> list[str]:
    with pymupdf.open(path) as doc:
        if doc.is_encrypted:
            raise ValueError("Encrypted PDF: supply an unlocked copy")
        if not 0 < len(doc) <= 80:
            raise ValueError("PDF must contain 1 to 80 pages")
        pages = [page.get_text(sort=True).strip() for page in doc]
    if any(not page for page in pages):
        raise ValueError("PDF contains a page without text; OCR it before extraction")
    if sum(map(len, pages)) > 180_000:
        raise ValueError("Contract exceeds text limit; provide a shorter complete agreement")
    return pages


def load_usage(path: str | Path) -> UsageHistory:
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return UsageHistory(months=[UsageMonth.model_validate(row) for row in rows])
