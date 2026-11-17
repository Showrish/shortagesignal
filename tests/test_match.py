"""Matching recalls to shortages."""
import duckdb

from shortagesignal.match import _directory, build_matches, check_claude_key, identify_drug
from shortagesignal.storage import load_batch, write_parquet

NDC_MAP = {"00409-4888": "heparin sodium"}
VOCABULARY = {"heparin sodium", "carboplatin"}
BRANDS = {"paraplatin": "carboplatin"}


def test_identify_drug_tries_ndc_then_openfda_then_text():
    assert identify_drug(["00409-4888"], None, "", NDC_MAP, VOCABULARY, BRANDS) == (
        "heparin sodium", "ndc_directory")
    assert identify_drug([], '{"generic_name": ["CARBOPLATIN"]}', "", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "openfda")
    assert identify_drug([], None, "Carboplatin Injection, 50 mg", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "text_name")
    assert identify_drug([], None, "Paraplatin (carboplatin) injection", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "text_brand")
    assert identify_drug([], None, "Mystery Compound tablets", NDC_MAP, VOCABULARY,
                         BRANDS) == (None, None)


def save(con, rows, path, workdir):
    columns = sorted({c for r in rows for c in r})
    load_batch(con, rows, columns, "fixture", workdir)
    write_parquet(con, "SELECT * FROM fixture", path)


def test_identify_drug_uses_claude_only_as_a_last_resort():
    assert identify_drug([], None, "Mystery Compound tablets", NDC_MAP, VOCABULARY, BRANDS,
                         claude_key="carboplatin") == ("carboplatin", "claude")
    assert identify_drug(["00409-4888"], None, "", NDC_MAP, VOCABULARY, BRANDS,
                         claude_key="carboplatin") == ("heparin sodium", "ndc_directory")


def test_check_claude_key_only_accepts_known_drugs():
    known = {"carboplatin", "ranitidine hydrochloride"}
    assert check_claude_key("carboplatin", known, BRANDS) == "carboplatin"
    assert check_claude_key("paraplatin", known, BRANDS) == "carboplatin"   # a brand
    assert check_claude_key("unobtainium", known, BRANDS) is None
    assert check_claude_key(None, known, BRANDS) is None


def test_check_claude_key_accepts_combinations_of_known_drugs():
    known = {"semaglutide", "cyanocobalamin", "lidocaine hydrochloride + epinephrine bitartrate"}
    # a compounded mix: no reference list has it, but every part is a known drug
    assert check_claude_key("cyanocobalamin + semaglutide", known, BRANDS) == "cyanocobalamin + semaglutide"
    # a part of a known combination counts as a known drug too
    assert check_claude_key("epinephrine bitartrate + semaglutide", known, BRANDS) == (
        "epinephrine bitartrate + semaglutide")
    # one unknown part is enough to say no, and a single unknown drug is still no
    assert check_claude_key("glutathione + semaglutide", known, BRANDS) is None
    assert check_claude_key("glutathione", known, BRANDS) is None


def test_identify_drug_keeps_text_names_strict_for_combinations():
    # A combination read from the description only counts when the combination itself is known.
    # Known parts aren't enough there, since a description can name a diluent, as in "fentanyl in
    # 0.9% sodium chloride". Claude, which is told to leave diluents out, gets the allowance.
    vocabulary = {"semaglutide", "cyanocobalamin"}
    text = "Semaglutide/Cyanocobalamin Injection"
    assert identify_drug([], None, text, NDC_MAP, vocabulary, BRANDS) == (None, None)
    assert identify_drug([], None, text, NDC_MAP, vocabulary, BRANDS,
                         claude_key="cyanocobalamin + semaglutide") == (
        "cyanocobalamin + semaglutide", "claude")


def test_identify_drug_reads_a_second_drug_past_a_strength_only_when_known():
    vocabulary = VOCABULARY | {"ergotamine tartrate", "caffeine + ergotamine tartrate",
                               "fentanyl citrate", "fentanyl citrate + sodium chloride"}
    text = "Ergotamine Tartrate 1 mg/Caffeine 100 mg base F Suppository (Pink) 48 suppositories, Rx"
    assert identify_drug([], None, text, NDC_MAP, vocabulary, BRANDS) == (
        "caffeine + ergotamine tartrate", "text_name")
    # a diluent isn't a second drug, so a premix keeps its drug and its shortage links
    premix = "Fentanyl Citrate 50 mcg in 0.9% Sodium Chloride 100 mL bag"
    assert identify_drug([], None, premix, NDC_MAP, vocabulary, BRANDS) == ("fentanyl citrate", "text_name")
    # it never replaces a first reading that isn't known: this goes to Claude, not bare fentanyl
    syringe = "fentaNYL in 0.9% sodium chloride, 10 mcg/1 mL, (10 mcg/mL), 3 mL syringe, Rx only"
    assert identify_drug([], None, syringe, NDC_MAP, vocabulary | {"fentanyl"}, BRANDS) == (None, None)
    assert identify_drug([], None, syringe, NDC_MAP, vocabulary | {"fentanyl"}, BRANDS,
                         claude_key="fentanyl citrate") == ("fentanyl citrate", "claude")
    # and when the fuller name isn't a known drug, the first one stands
    assert identify_drug([], None, text, NDC_MAP, vocabulary - {"caffeine + ergotamine tartrate"},
                         BRANDS) == ("ergotamine tartrate", "text_name")


def test_store_brands_never_count_as_drugs(tmp_path):
    text = "CVS pharmacy, Pain Relieving Antiseptic Spray. Benzalkonium Cl 0.13% Lidocaine HCl 2.5%"
    assert identify_drug([], None, text, NDC_MAP, VOCABULARY | {"cvs"}, BRANDS) == (None, None)
    assert check_claude_key("cvs", {"cvs"}, {}) is None
    # an NDC listing with a store brand as its generic name is skipped, brand field and all
    con, path = duckdb.connect(), tmp_path / "ndc.parquet"
    save(con, [{"product_ndc": "11111-222", "generic_name": "CVS", "brand_name": "Fentanyl"},
               {"product_ndc": "00409-4888", "generic_name": "Heparin Sodium", "brand_name": "Heparin"}],
         path, tmp_path)
    _, _, vocabulary = _directory(con, path.as_posix())
    assert vocabulary == {"heparin sodium"}


def _fixture(con, tmp_path):
    """Two directory products, four recalls (one unnamed), two shortage listings."""
    f = {name: tmp_path / f"{name}.parquet" for name in (
        "ndc", "recalls", "recall_ids", "shortage_ids", "snapshots",
        "recall_drugs", "shortage_drugs", "links", "unmatched")}

    save(con, [
        {"product_ndc": "0409-4888", "generic_name": "Heparin Sodium", "brand_name": "Heparin Sodium"},
        {"product_ndc": "63323-540", "generic_name": "Carboplatin", "brand_name": "Paraplatin"},
    ], f["ndc"], tmp_path)
    recall = {"openfda": "{}", "report_date": "20260101", "recall_initiation_date": "20251215",
              "classification": "Class II"}
    save(con, [
        {**recall, "recall_number": "D-1", "recalling_firm": "Hospira, Inc.",
         "product_description": "Heparin Sodium Injection, NDC 0409-4888-10"},
        {**recall, "recall_number": "D-2", "recalling_firm": "Acme Inc",
         "product_description": "Paraplatin (carboplatin) injection, 10 mg/mL"},
        {**recall, "recall_number": "D-3", "recalling_firm": "Teyro Labs",
         "product_description": "Carboplatin Injection, 50 mg"},
        {**recall, "recall_number": "D-4", "recalling_firm": "Unknown LLC",
         "product_description": "Mystery Compound tablets"},
    ], f["recalls"], tmp_path)
    save(con, [
        {"recall_number": "D-1", "firm_key": "HOSPIRA", "ndc11": "00409-4888-10",
         "ndc9": "00409-4888", "source": "text"},
        {"recall_number": "D-2", "firm_key": "ACME", "ndc11": None, "ndc9": None, "source": "none"},
        {"recall_number": "D-3", "firm_key": "TEYRO", "ndc11": None, "ndc9": None, "source": "none"},
        {"recall_number": "D-4", "firm_key": "UNKNOWN", "ndc11": None, "ndc9": None, "source": "none"},
    ], f["recall_ids"], tmp_path)
    save(con, [
        {"shortage_key": "S-1", "firm_key": "HOSPIRA", "ndc11": "00409-4888-10",
         "ndc9": "00409-4888", "source": "text"},
        {"shortage_key": "S-2", "firm_key": "TEYRO", "ndc11": "60505-6282-01",
         "ndc9": "60505-6282", "source": "text"},
    ], f["shortage_ids"], tmp_path)
    snapshot = {"snapshot_date": "2026-10-11", "status": "Current", "list_type": "shortage"}
    save(con, [
        {**snapshot, "shortage_key": "S-1", "generic_name": "Heparin Sodium Injection",
         "company_name": "Hospira, Inc.", "initial_posting_date": "01/15/2026"},
        {**snapshot, "shortage_key": "S-2", "generic_name": "Carboplatin Injection",
         "company_name": "Teyro Labs", "initial_posting_date": "05/01/2023"},
    ], f["snapshots"], tmp_path)
    return f


def test_build_matches_links_at_the_strongest_level(tmp_path):
    con = duckdb.connect()
    f = _fixture(con, tmp_path)
    stats = build_matches(con, f, tmp_path)

    links = con.execute(
        f"SELECT recall_number, shortage_key, match_level FROM read_parquet('{f['links'].as_posix()}') "
        "ORDER BY 1, 2"
    ).fetchall()
    assert links == [("D-1", "S-1", "package"), ("D-2", "S-2", "drug"), ("D-3", "S-2", "drug_and_firm")]

    unmatched = con.execute(
        f"SELECT recall_number FROM read_parquet('{f['unmatched'].as_posix()}')"
    ).fetchall()
    assert unmatched == [("D-4",)]
    assert stats["identified"] == 3 and stats["unmatched"] == 1
    assert stats["linked_recalls"] == 3 and stats["linked_shortages"] == 2
    assert stats["by_level"] == {"package": 1, "product": 0, "drug_and_firm": 1, "drug": 1}


def test_build_matches_uses_claude_names_only_for_known_drugs(tmp_path):
    con = duckdb.connect()
    f = _fixture(con, tmp_path)

    stats = build_matches(con, f, tmp_path, claude_keys={"D-4": "carboplatin"})
    sources = dict(con.execute(
        f"SELECT recall_number, id_source FROM read_parquet('{f['recall_drugs'].as_posix()}')"
    ).fetchall())
    assert sources["D-4"] == "claude"
    assert (stats["by_source"]["claude"], stats["unmatched"], stats["claude_rejected"]) == (1, 0, 0)
    links = con.execute(
        f"SELECT shortage_key, match_level FROM read_parquet('{f['links'].as_posix()}') "
        "WHERE recall_number = 'D-4'").fetchall()
    assert links == [("S-2", "drug")]

    stats = build_matches(con, f, tmp_path, claude_keys={"D-4": "unobtainium"})
    assert (stats["unmatched"], stats["claude_rejected"]) == (1, 1)
