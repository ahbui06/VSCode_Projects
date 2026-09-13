"""Data contracts for PDF ingestion, before any AI interpretation."""

from pydantic import BaseModel, Field


class TableCell(BaseModel):
    table_number: int
    row_number: int
    column_number: int
    bbox: tuple[float, float, float, float]
    text: str


class PDFPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    needs_review: bool
    table_cells: list[TableCell] = Field(default_factory=list)
    layout_warning: str | None = None


class PDFDocument(BaseModel):
    source_file: str
    sha256: str
    pages: list[PDFPage]


class InspectionFailure(BaseModel):
    source_file: str
    error: str


class InspectionReport(BaseModel):
    documents: list[PDFDocument] = Field(default_factory=list)
    failures: list[InspectionFailure] = Field(default_factory=list)
