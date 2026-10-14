"""
Day 5: match recalls to shortages, and measure how well that works.

Two separate questions:
  1. Identified: can we tell which drug a recall is about? Recalls we can't identify go
     to unmatched_recalls, the work queue for the AI step on Day 9.
  2. Linked: does that drug also appear on the shortage list? Most recalled drugs never
     go short, so "not linked" is normal. Timing (did the recall come first?) is Day 10.

Links come in four strengths, strongest first:
  package        same 11-digit package NDC
  product        same product NDC (same company and drug, any package size)
  drug_and_firm  same drug name and the same company
  drug           same drug name, any company

Day 9 adds a last resort for naming the drug: Claude's reading of the product text (see
extract.py). Its name only counts when it's a drug we know exists: one in the NDC
directory, on the shortage list, or attached by openFDA to some past recall. The last one
covers drugs that are off the market now, like ranitidine.

Tables written:
  recall_drugs           one row per recall: its drug key and where the key came from
  shortage_drugs         one row per shortage listing: its drug key and firm key
  recall_shortage_links  one row per recall and shortage listing that share a drug
  unmatched_recalls      recalls with no NDC and no recognizable drug name
"""
from collections import defaultdict
from pathlib import Path

from shortagesignal.drugs import drug_key, text_drug_name
from shortagesignal.firms import firm_key
from shortagesignal.identify import json_list
from shortagesignal.ndc import normalize_product_ndc
from shortagesignal.storage import load_batch, write_parquet

LEVELS = {1: "package", 2: "product", 3: "drug_and_firm", 4: "drug"}


def identify_drug(ndc9s, openfda_text, description, ndc_map, vocabulary, brand_map,
                  claude_key=None):
    """The drug a recall is about, and how we know. (None, None) if we can't tell.

    claude_key is Claude's answer, already checked against the known drugs. It's only used
    when every other way comes up empty.
    """
    for ndc9 in ndc9s:
        if ndc9 in ndc_map:
            return ndc_map[ndc9], "ndc_directory"
    names = json_list(openfda_text, "generic_name")
    if names:
        key = drug_key(names[0])
        if key:
            return key, "openfda"
    # A name from the description only counts if it's a drug we know exists.
    key = drug_key(text_drug_name(description))
    if key in vocabulary:
        return key, "text_name"
    if key in brand_map:
        return brand_map[key], "text_brand"
    if claude_key:
        return claude_key, "claude"
    return None, None


def check_claude_key(key, known, brand_map):
    """Claude's drug key if it's a known drug, the generic for a known brand, else None."""
    if not key:
        return None
    if key in known:
        return key
    return brand_map.get(key)


def _directory(con, ndc_path):
    """Product code to drug key, brand to generic, and every generic in the NDC directory."""
    ndc_map, brand_map, vocabulary = {}, {}, set()
    for product_ndc, generic, brand in con.execute(
        f"SELECT product_ndc, generic_name, brand_name FROM read_parquet('{ndc_path}')"
    ).fetchall():
        key = drug_key(generic)
        if not key:
            continue
        vocabulary.add(key)
        ndc9 = normalize_product_ndc(product_ndc)
        if ndc9:
            ndc_map.setdefault(ndc9, key)
        brand_key = drug_key(brand)
        if brand_key and brand_key != key:
            brand_map.setdefault(brand_key, key)
    return ndc_map, brand_map, vocabulary


def _shortage_rows(con, snapshots_path):
    """One row per shortage listing, with its latest name and company."""
    rows = []
    for shortage_key, generic, company in con.execute(f"""
        SELECT shortage_key, arg_max(generic_name, snapshot_date), arg_max(company_name, snapshot_date)
        FROM read_parquet('{snapshots_path}')
        GROUP BY shortage_key
    """).fetchall():
        rows.append({"shortage_key": shortage_key, "drug_key": drug_key(generic),
                     "firm_key": firm_key(company), "generic_name": generic})
    return rows


def _openfda_names(recall_list):
    """Every generic name openFDA has attached to a recall, as drug keys."""
    names = set()
    for _, _, openfda_text in recall_list:
        for name in json_list(openfda_text, "generic_name"):
            key = drug_key(name)
            if key:
                names.add(key)
    return names


def _recall_list(con, recalls_path):
    return con.execute(
        f"SELECT recall_number, product_description, openfda FROM read_parquet('{recalls_path}')"
    ).fetchall()


def known_drugs(con, ndc_path, snapshots_path, recalls_path):
    """(known drug keys, brand map) for checking Claude's answers outside the daily run."""
    _, brand_map, vocabulary = _directory(con, Path(ndc_path).as_posix())
    vocabulary |= {r["drug_key"] for r in _shortage_rows(con, Path(snapshots_path).as_posix())
                   if r["drug_key"]}
    return vocabulary | _openfda_names(_recall_list(con, Path(recalls_path).as_posix())), brand_map


def build_matches(con, f, workdir, claude_keys=None):
    """f maps names to file paths: inputs ndc, recalls, recall_ids, shortage_ids, snapshots,
    and outputs recall_drugs, shortage_drugs, links, unmatched. claude_keys maps recall
    numbers to Claude's drug keys (see extract.py). Returns stats."""
    p = {name: path.as_posix() for name, path in f.items()}
    claude_keys = claude_keys or {}

    # 1. What drugs exist: every generic name in the NDC directory and on the shortage list.
    ndc_map, brand_map, vocabulary = _directory(con, p["ndc"])
    shortage_rows = _shortage_rows(con, p["snapshots"])
    vocabulary |= {r["drug_key"] for r in shortage_rows if r["drug_key"]}

    # 2. A drug identity for every recall. Claude's answers are checked against a wider list
    #    that also has the names openFDA attached to past recalls.
    ndc9s = defaultdict(list)
    for recall_number, ndc9 in con.execute(
        f"SELECT recall_number, ndc9 FROM read_parquet('{p['recall_ids']}') WHERE ndc9 IS NOT NULL"
    ).fetchall():
        ndc9s[recall_number].append(ndc9)

    recall_list = _recall_list(con, p["recalls"])
    known = (vocabulary | _openfda_names(recall_list)) if claude_keys else vocabulary
    recall_rows, claude_rejected = [], 0
    for recall_number, description, openfda_text in recall_list:
        raw = claude_keys.get(recall_number)
        key, source = identify_drug(ndc9s.get(recall_number, []), openfda_text, description,
                                    ndc_map, vocabulary, brand_map,
                                    claude_key=check_claude_key(raw, known, brand_map))
        if raw and source is None:
            claude_rejected += 1
        recall_rows.append({"recall_number": recall_number, "drug_key": key, "id_source": source})

    load_batch(con, recall_rows, ["recall_number", "drug_key", "id_source"], "recall_drugs", workdir)
    load_batch(con, shortage_rows, ["shortage_key", "drug_key", "firm_key", "generic_name"],
               "shortage_drugs", workdir)
    write_parquet(con, "SELECT * FROM recall_drugs ORDER BY recall_number", f["recall_drugs"])
    write_parquet(con, "SELECT * FROM shortage_drugs ORDER BY shortage_key", f["shortage_drugs"])

    # 3. Links, keeping only the strongest level for each recall and shortage pair.
    con.execute(f"""
        CREATE OR REPLACE TABLE links AS
        WITH r_ids AS (
            SELECT DISTINCT recall_number, ndc11, ndc9 FROM read_parquet('{p['recall_ids']}')
            WHERE ndc9 IS NOT NULL
        ),
        s_ids AS (
            SELECT DISTINCT shortage_key, ndc11, ndc9 FROM read_parquet('{p['shortage_ids']}')
            WHERE ndc9 IS NOT NULL
        ),
        r_firm AS (
            SELECT recall_number, any_value(firm_key) AS firm_key
            FROM read_parquet('{p['recall_ids']}') GROUP BY recall_number
        ),
        candidates AS (
            SELECT r.recall_number, s.shortage_key, 1 AS strength
            FROM r_ids r JOIN s_ids s ON r.ndc11 = s.ndc11
            UNION ALL
            SELECT r.recall_number, s.shortage_key, 2
            FROM r_ids r JOIN s_ids s ON r.ndc9 = s.ndc9
            UNION ALL
            SELECT d.recall_number, s.shortage_key,
                   CASE WHEN rf.firm_key = s.firm_key THEN 3 ELSE 4 END
            FROM recall_drugs d
            JOIN shortage_drugs s ON d.drug_key = s.drug_key
            LEFT JOIN r_firm rf ON rf.recall_number = d.recall_number
            WHERE d.drug_key IS NOT NULL
        ),
        best AS (
            SELECT recall_number, shortage_key, min(strength) AS match_rank
            FROM candidates GROUP BY recall_number, shortage_key
        ),
        shortage_latest AS (
            SELECT * FROM read_parquet('{p['snapshots']}')
            QUALIFY row_number() OVER (PARTITION BY shortage_key ORDER BY snapshot_date DESC) = 1
        )
        SELECT b.recall_number, b.shortage_key, b.match_rank,
               CASE b.match_rank WHEN 1 THEN 'package' WHEN 2 THEN 'product'
                                 WHEN 3 THEN 'drug_and_firm' ELSE 'drug' END AS match_level,
               r.report_date AS recall_report_date,
               r.recall_initiation_date,
               r.classification AS recall_class,
               sl.generic_name AS shortage_generic_name,
               sl.status AS shortage_status,
               sl.list_type AS shortage_list_type,
               sl.initial_posting_date AS shortage_posted
        FROM best b
        JOIN read_parquet('{p['recalls']}') r ON r.recall_number = b.recall_number
        JOIN shortage_latest sl ON sl.shortage_key = b.shortage_key
    """)
    write_parquet(con, "SELECT * FROM links ORDER BY recall_number, shortage_key", f["links"])

    # 4. Recalls we can't identify at all: no NDC and no recognizable drug name.
    write_parquet(con, f"""
        SELECT r.recall_number, r.recalling_firm, r.product_description,
               r.report_date, r.classification
        FROM read_parquet('{p['recalls']}') r
        JOIN recall_drugs d ON d.recall_number = r.recall_number
        WHERE d.drug_key IS NULL
          AND r.recall_number NOT IN (
              SELECT recall_number FROM read_parquet('{p['recall_ids']}') WHERE ndc9 IS NOT NULL
          )
        ORDER BY r.report_date DESC
    """, f["unmatched"])

    # 5. Stats for the run log.
    recalls, unmatched, linked_recalls, linked_shortages, shortages = con.execute(f"""
        SELECT
            (SELECT count(*) FROM recall_drugs),
            (SELECT count(*) FROM read_parquet('{p['unmatched']}')),
            (SELECT count(DISTINCT recall_number) FROM links),
            (SELECT count(DISTINCT shortage_key) FROM links),
            (SELECT count(*) FROM shortage_drugs)
    """).fetchone()
    by_level = dict(con.execute("""
        SELECT best, count(*) FROM (
            SELECT recall_number, min(match_rank) AS best FROM links GROUP BY recall_number
        ) GROUP BY best
    """).fetchall())
    identified = recalls - unmatched
    by_source = defaultdict(int)
    for r in recall_rows:
        by_source[r["id_source"] or "none"] += 1
    named = recalls - by_source["none"]
    return {
        "recalls": recalls,
        "named": named,
        "named_pct": round(100 * named / recalls, 1) if recalls else 0.0,
        "by_source": dict(by_source),
        "claude_rejected": claude_rejected,
        "identified": identified,
        "identified_pct": round(100 * identified / recalls, 1) if recalls else 0.0,
        "unmatched": unmatched,
        "linked_recalls": linked_recalls,
        "linked_shortages": linked_shortages,
        "shortages": shortages,
        "by_level": {LEVELS[k]: by_level.get(k, 0) for k in LEVELS},
    }
