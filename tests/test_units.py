import uuid
from decimal import Decimal

import pytest

from importer import common, sample_pdf
from importer.edge import validate
from importer.parser import ImportRejected, parse_lines, parse_pdf


def test_sample_pdf_round_trips_through_the_real_parser():
    records = parse_pdf(sample_pdf.build_pdf(sample_pdf.VALID))
    assert [(r.sku, r.price) for r in records] == [
        ("A-100", Decimal("89.50")),
        ("A-200", Decimal("129.00")),
    ]


def test_every_bad_row_is_reported_at_once():
    with pytest.raises(ImportRejected) as error:
        parse_lines(sample_pdf.INVALID)
    assert "Line 2" in str(error.value) and "Line 3" in str(error.value)


@pytest.mark.parametrize(
    "lines",
    [
        [],
        ["wrong,header"],
        ["sku,name,price"],
        ["sku,name,price", "A,B,-1"],
        ["sku,name,price", "A,B,NaN"],
        ["sku,name,price", "A,B,1", "A,C,2"],
    ],
)
def test_bad_sheets_are_rejected(lines):
    with pytest.raises(ImportRejected):
        parse_lines(lines)


@pytest.mark.parametrize(
    ("size", "first_bytes", "expected"),
    [
        (10, b"%PDF-", None),
        (11, b"%PDF-", "FILE_TOO_LARGE"),
        (10, b"MZ\x90\x00\x03", "INVALID_FILE_TYPE"),
        (0, b"", "INVALID_FILE_TYPE"),
    ],
)
def test_edge_validation(size, first_bytes, expected):
    assert validate(size, first_bytes, max_size=10) == expected


def test_only_uuid_keys_are_accepted():
    task_id = uuid.uuid4()
    assert common.task_id_from_key(f"{task_id}.pdf") == task_id
    assert common.task_id_from_key(f"{task_id}.exe") is None
    assert common.task_id_from_key("../evil.pdf") is None
    assert common.task_id_from_key("unknown") is None


def test_signature_rejects_tampering():
    signature = common.sign(b"payload")
    assert common.verify(b"payload", signature)
    assert not common.verify(b"payload2", signature)
