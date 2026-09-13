"""Read original PDFs without changing them or sending data to a service."""

from hashlib import sha256
from pathlib import Path

import pymupdf

from .models import PDFDocument, PDFPage, TableCell


def read_pdf(path: Path, *, include_tables: bool = False) -> PDFDocument:
    # Hash and parse the same bytes so extracted text has a stable source identity.
    content = path.read_bytes()
    pages = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDF: provide an unlocked copy.")
        if document.page_count == 0:
            raise ValueError("PDF contains no pages.")
        for number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).strip()
            cells = []
            layout_warning = None
            if include_tables:
                try:
                    for table_number, table in enumerate(page.find_tables().tables, start=1):
                        for row_number, (row, values) in enumerate(zip(table.rows, table.extract()), start=1):
                            for column_number, (bbox, value) in enumerate(zip(row.cells, values), start=1):
                                if bbox is not None and value and value.strip():
                                    cells.append(TableCell(table_number=table_number,
                                        row_number=row_number, column_number=column_number,
                                        bbox=tuple(bbox), text=value.strip()))
                except Exception as error:
                    # Table detection is optional: keep the original page text intact.
                    cells = []
                    layout_warning = f"Table detection failed ({type(error).__name__}); using plain text."
            pages.append(PDFPage(
                page_number=number,
                text=text,
                # A heuristic, not proof of a scan: blank covers also trigger it.
                needs_review=len("".join(text.split())) < 40,
                table_cells=cells,
                layout_warning=layout_warning,
            ))
    return PDFDocument(
        source_file=path.name, sha256=sha256(content).hexdigest(), pages=pages
    )
