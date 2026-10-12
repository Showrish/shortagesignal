"""NDC patterns and normalization. The pattern also runs inside DuckDB (RE2), which matches it the same way."""
import re

import pytest

from shortagesignal.ndc import NDC_PATTERN, extract_ndcs, normalize_ndc, normalize_product_ndc

PATTERN = re.compile(NDC_PATTERN)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Heparin Sodium Injection, NDC 0409-2720-01", True),  # 4-4-2
        ("NDC 00409-2720-01 carton", True),                    # 5-4-2, the 11-digit form
        ("NDC 63323-540-31", True),                            # 5-3-2
        ("NDC 12345-6789-0", True),                            # 5-4-1
        ("NDC 0409488810 with no dashes", False),
        ("NDC 0143-9876-1, an invalid layout", False),
        ("Lot 12345-678, exp 2026", False),
        ("NDC 00409-4888-102, last part too long", False),
    ],
)
def test_ndc_pattern(text, expected):
    assert bool(PATTERN.search(text)) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("0409-4888-10", "00409-4888-10"),   # 4-4-2 gets a zero on the labeler
        ("63323-540-31", "63323-0540-31"),   # 5-3-2 gets a zero on the product
        ("12345-6789-0", "12345-6789-00"),   # 5-4-1 gets a zero on the package
        ("00409-4888-10", "00409-4888-10"),  # already 5-4-2
        ("00409488810", "00409-4888-10"),    # 11 digits with no dashes
        ("0409488810", None),                # 10 digits with no dashes fit three layouts
        ("0409-488-1", None),                # not a real layout
        (None, None),
    ],
)
def test_normalize_ndc(code, expected):
    assert normalize_ndc(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("0409-4888", "00409-4888"),
        ("63323-540", "63323-0540"),
        ("12345-6789", "12345-6789"),
        ("123-45", None),
        ("0409-4888-10", None),   # a package code, not a product code
    ],
)
def test_normalize_product_ndc(code, expected):
    assert normalize_product_ndc(code) == expected


def test_extract_ndcs_finds_every_kind_and_skips_lot_numbers():
    text = ("Heparin Injection, NDC 0409-2720-01 and 0409-2720-02. Also NDC# 63323-540, "
            "NDC 00409488810, NDC: 0409488811. Lot 1234-5678, exp 12/2027")
    found = extract_ndcs(text)
    assert found["package"] == ["00409-2720-01", "00409-2720-02", "00409-4888-10"]
    assert found["product"] == ["63323-0540"]
    assert found["digits10"] == ["0409488811"]
