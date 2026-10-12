"""Drug name cleanup."""
import pytest

from shortagesignal.drugs import drug_key, text_drug_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Clindamycin Phosphate Injection, USP", "clindamycin phosphate"),
        ("CLINDAMYCIN PHOSPHATE", "clindamycin phosphate"),
        ("Amoxicillin and Clavulanate Potassium for Oral Suspension",
         "amoxicillin + clavulanate potassium"),
        ("clavulanate potassium; amoxicillin", "amoxicillin + clavulanate potassium"),
        ("Bupivacaine HCl Injection", "bupivacaine hydrochloride"),
        ("Sodium Chloride 0.9% Injection, USP Bags", "sodium chloride"),
        ("Carboplatin Injection (Pharmacy Bulk Package)", "carboplatin"),
        ("", None),
        (None, None),
    ],
)
def test_drug_key(name, expected):
    assert drug_key(name) == expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Heparin Sodium Injection, USP, 1,000 USP Units/mL, NDC 0409-4888-10",
         "Heparin Sodium Injection"),
        ("Sodium Chloride 0.9% Injection", "Sodium Chloride"),
        ("Paraplatin (carboplatin) injection", "Paraplatin"),
        ("", None),
    ],
)
def test_text_drug_name(description, expected):
    assert text_drug_name(description) == expected
