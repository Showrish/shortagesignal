"""Company name cleanup."""
import pytest

from shortagesignal.firms import firm_key


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Pfizer Inc.", "PFIZER"),
        ("PFIZER INC", "PFIZER"),
        ("Pfizer Laboratories Div Pfizer Inc", "PFIZER"),
        ("Hospira, Inc.", "HOSPIRA"),
        ("Gland Pharma Limited", "GLAND"),
        ("Teva Pharmaceuticals USA, Inc.", "TEVA"),
        ("Fresenius Kabi USA, LLC", "FRESENIUS KABI"),
        ("Dr. Reddy's Laboratories Limited", "DR REDDY"),
        ("Sagent Pharmaceuticals", "SAGENT"),
        ("", None),
        (None, None),
    ],
)
def test_firm_key(name, expected):
    assert firm_key(name) == expected
