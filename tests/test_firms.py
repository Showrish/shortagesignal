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
        # a parent company named after the firm is dropped
        ("Hospira, Inc., a Pfizer Company", "HOSPIRA"),
        ("Sandoz Inc., a Novartis company", "SANDOZ"),
        ("Merck Sharp & Dohme Corp., a subsidiary of Merck & Co., Inc.", "MERCK SHARP AND DOHME"),
        ("Bausch & Lomb Incorporated, a division of Bausch Health", "BAUSCH AND LOMB"),
        ("Mylan Institutional, an affiliate of Viatris", "MYLAN INSTITUTIONAL"),
        ("Teva Parenteral Medicines, Inc., a wholly-owned subsidiary of Teva", "TEVA PARENTERAL MEDICINES"),
        ("", None),
        (None, None),
    ],
)
def test_firm_key(name, expected):
    assert firm_key(name) == expected
