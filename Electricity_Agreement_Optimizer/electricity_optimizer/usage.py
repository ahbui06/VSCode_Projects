"""Validate a year of monthly consumption before calculating bills."""

import csv
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MonthlyUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    kwh: Decimal = Field(ge=0, allow_inf_nan=False)

    @field_validator("month")
    @classmethod
    def valid_year(cls, value):
        if value.startswith("0000"):
            raise ValueError("Year must be at least 0001.")
        return value


class UsageYear(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    months: tuple[MonthlyUsage, ...] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def consecutive_months(self):
        ordinals = [int(m.month[:4]) * 12 + int(m.month[5:]) for m in self.months]
        if any(b != a + 1 for a, b in zip(ordinals, ordinals[1:])):
            raise ValueError("Usage must contain 12 consecutive months in order, without duplicates.")
        return self


def load_usage_csv(path: Path) -> UsageYear:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["month", "kwh"]:
            raise ValueError("CSV must have exactly these headers in order: month,kwh")
        rows = []
        for line, row in enumerate(reader, start=2):
            try:
                rows.append(MonthlyUsage.model_validate(row))
            except ValueError as error:
                raise ValueError(f"Invalid usage at CSV line {line}: {error}") from error
    return UsageYear(months=tuple(sorted(rows, key=lambda row: row.month)))
