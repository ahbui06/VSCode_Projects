"""Step 2: cited, reviewable terms. These are not executable pricing rules."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(StrictModel):
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, description="Exact supporting text from this page.")


class ContractTerm(StrictModel):
    status: Literal["found", "not_stated", "ambiguous"]
    value: str | None = Field(description="Include original units, currency, conditions and exceptions. Null if not stated.")
    citations: list[Citation]


class AgreementTerms(StrictModel):
    # Required fields ensure the model must explicitly account for missing terms.
    provider: ContractTerm
    plan_name: ContractTerm
    market: ContractTerm = Field(description="Country, region and service territory only as supported by text.")
    customer_type: ContractTerm
    document_type: ContractTerm
    effective_date: ContractTerm
    rate_type: ContractTerm
    energy_charges: ContractTerm = Field(description="Actual unit rates, tiers and time periods; never substitute average prices.")
    average_prices: ContractTerm = Field(description="Illustrative prices at usage levels, separate from unit energy charges.")
    recurring_charges: ContractTerm
    delivery_charges: ContractTerm
    credits_and_minimum_usage: ContractTerm
    contract_length: ContractTerm
    termination_fee: ContractTerm
    renewal_terms: ContractTerm
    price_change_rules: ContractTerm


class ReviewIssue(StrictModel):
    field: str
    severity: Literal["error", "warning"]
    message: str


class ExtractionRecord(StrictModel):
    source_file: str
    source_sha256: str
    model: str
    response_id: str
    extracted_at: str
    prompt_version: str
    terms: AgreementTerms
    issues: list[ReviewIssue]
    review_status: Literal["needs_human_review"] = "needs_human_review"
