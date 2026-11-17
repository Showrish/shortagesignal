from shortagesignal.link_check import compare, score


def test_compare_reads_routes_and_companies():
    assert compare("Fentanyl Citrate Injection, 2 mL vial", "Injection", "50 mcg/mL", "Fentanyl Citrate",
                   "HOSPIRA", "HOSPIRA") == ("injectable", "injectable", "same", "same")
    assert compare("Fentanyl Citrate Injection, 2 mL vial", "Patch", "25 mcg/hr", "Fentanyl Transdermal",
                   "HOSPIRA", "MYLAN")[2:] == ("different", "different")
    assert compare("Sodium Chloride 0.9%", "Injection", "", "Sodium Chloride", None, "BAXTER")[2:] == (
        "unknown", "unknown")


def test_score_counts_agreement_only_where_both_gave_an_answer():
    auto = [{"row": "1", "match_level": "drug", "auto_route": "same", "auto_company": "different"},
            {"row": "2", "match_level": "drug", "auto_route": "different", "auto_company": "different"},
            {"row": "3", "match_level": "package", "auto_route": "unknown", "auto_company": "same"}]
    labels = [{"row": "1", "same_ingredient": "yes", "same_route": "yes", "same_company": "no"},
              {"row": "2", "same_ingredient": "no", "same_route": "yes", "same_company": "unclear"},
              {"row": "3", "same_ingredient": "yes", "same_route": "no", "same_company": "yes"}]
    result = score(labels, auto)
    route = result["same_route"]
    assert (route["agree"], route["judged"], route["code_unknown"]) == (1, 2, 1)   # row 2 disagrees
    company = result["same_company"]
    assert (company["agree"], company["judged"]) == (2, 2)                        # row 2 was unclear
    assert result["ingredient_by_level"] == {"drug": (1, 2), "package": (1, 1)}
