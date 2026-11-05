"""Turns a price-sheet PDF into records. Every row is checked before anything is written."""

import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pdfplumber

HEADER = "sku,name,price"


class ImportRejected(Exception):
    """The file is readable but its content is wrong. The message lists every problem."""


@dataclass(frozen=True)
class Record:
    sku: str
    name: str
    price: Decimal


def parse_lines(lines: list[str]) -> list[Record]:
    rows = [line.strip() for line in lines if line.strip()]
    if not rows or rows[0].lower() != HEADER:
        raise ImportRejected(f"Line 1: expected header '{HEADER}'")

    records: dict[str, Record] = {}
    errors: list[str] = []
    for number, row in enumerate(rows[1:], start=2):
        parts = [part.strip() for part in row.split(",")]
        if len(parts) != 3 or not all(parts):
            errors.append(f"Line {number}: expected 3 values")
            continue
        sku, name, raw_price = parts
        try:
            price = Decimal(raw_price)
        except InvalidOperation:
            errors.append(f"Line {number}: '{raw_price}' is not a price")
            continue
        if not price.is_finite() or price < 0:
            errors.append(f"Line {number}: '{raw_price}' is not a price")
        elif sku in records:
            errors.append(f"Line {number}: duplicate SKU '{sku}'")
        else:
            records[sku] = Record(sku, name, price)

    if errors:
        raise ImportRejected("; ".join(errors))
    if not records:
        raise ImportRejected("The file has no rows")
    return list(records.values())


def parse_pdf(data: bytes) -> list[Record]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        lines = [line for page in pdf.pages for line in (page.extract_text() or "").splitlines()]
    return parse_lines(lines)
