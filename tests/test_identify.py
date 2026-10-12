"""Matching IDs for recalls, shortages and the NDC directory."""
from shortagesignal.identify import directory_rows, ids_for


def test_directory_rows_one_row_per_package_and_skips_ambiguous_digits():
    products = [
        ("0409-4888", "Hospira, Inc.", "heparin", "INJECTION",
         '[{"package_ndc": "0409-4888-10"}, {"package_ndc": "0409-4888-20"}]'),
        ("12345-678", "Some Co", "drug x", "TABLET", '[{"package_ndc": "12345-678-90"}]'),
        ("1234-5678", "Other Co", "drug y", "TABLET", '[{"package_ndc": "1234-5678-90"}]'),
        ("55555-1234", "No Packages Inc", "drug z", "TABLET", None),
    ]
    rows, lookup = directory_rows(products)

    assert len(rows) == 5   # 2 + 1 + 1 packages, plus one row for the product with none
    assert rows[0] == {"ndc11": "00409-4888-10", "ndc9": "00409-4888", "firm_key": "HOSPIRA",
                       "labeler_name": "Hospira, Inc.", "generic_name": "heparin",
                       "dosage_form": "INJECTION"}
    assert lookup["0409488810"] == "00409-4888-10"
    assert "1234567890" not in lookup   # fits two different packages, so it's ambiguous


def test_ids_for_combines_sources_without_double_counting():
    lookup = {"0409488811": "00409-4888-11"}
    openfda = '{"package_ndc": ["0409-4888-10"], "product_ndc": ["0409-4888", "63323-540"]}'
    rows = ids_for("Hospira, Inc.", "Heparin, NDC 0409-4888-10, NDC 0409488811", openfda, lookup)

    assert [(r["ndc11"], r["ndc9"], r["source"]) for r in rows] == [
        ("00409-4888-10", "00409-4888", "text"),
        ("00409-4888-11", "00409-4888", "directory_lookup"),
        (None, "63323-0540", "openfda_product"),
    ]
    assert all(r["firm_key"] == "HOSPIRA" for r in rows)


def test_ids_for_keeps_one_row_when_nothing_is_found():
    assert ids_for("Some Co", "Tablets, Lot 123", None, {}) == [
        {"firm_key": "SOME", "ndc11": None, "ndc9": None, "source": "none"}
    ]
