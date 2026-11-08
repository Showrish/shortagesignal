"""Day 14: the data dictionary, built from the real files so it can't drift.

  python -m shortagesignal.dictionary     write docs/data_dictionary.md from the files in DATA_DIR

For every file the pipeline keeps, it lists what one row means, which step makes it, how many
rows it has, and each column with its real type and a description. The columns and types come
from the files themselves. The descriptions live below, next to the code that knows them.

Two things keep the descriptions honest. A column that's in a file but not described here shows
up as "not described yet". A described column that a file no longer has is printed as a warning
when the dictionary is built. Either one means this file needs an update.
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

import duckdb

from shortagesignal.config import DATA_DIR, ROOT

OUT_PATH = ROOT / "docs" / "data_dictionary.md"
ENFORCEMENT_DOCS = "https://open.fda.gov/apis/drug/enforcement/"
SHORTAGE_DOCS = "https://open.fda.gov/apis/drug/drugshortages/"
NDC_DOCS = "https://open.fda.gov/apis/drug/ndc/"

FIRM_ADDRESS = "Part of the recalling firm's address."
YYYYMMDD = "as YYYYMMDD text"
MMDDYYYY = "as MM/DD/YYYY text"

RECALL_COLUMNS = {
    "recall_number": "FDA's ID for one recalled product, like D-0598-2026.",
    "event_id": "FDA's ID for the recall event. One event can cover hundreds of recall numbers, "
                "like a pharmacy recalling everything it made.",
    "report_date": f"The week FDA published the recall in its enforcement report, {YYYYMMDD}.",
    "recall_initiation_date": f"The day the firm started the recall, {YYYYMMDD}. The analysis "
                              "uses this one for when a recall happened.",
    "center_classification_date": f"The day FDA classified the recall, {YYYYMMDD}.",
    "termination_date": f"The day FDA closed the recall, if it has, {YYYYMMDD}.",
    "classification": "Class I (could cause serious harm or death), Class II (temporary or "
                      "reversible harm) or Class III (unlikely to cause harm).",
    "status": "Ongoing, Completed or Terminated.",
    "product_description": "FDA's free text about the product, often with strengths, package "
                           "sizes and NDCs. Matching and Claude read it.",
    "reason_for_recall": "FDA's free text on why. The root-cause rules and Claude read it.",
    "recalling_firm": "The company recalling the product.",
    "code_info": "Lot numbers and expiry dates of the recalled units.",
    "more_code_info": "The rest of code_info, when it's long.",
    "product_quantity": "How much was recalled, as FDA wrote it.",
    "distribution_pattern": "Where the product was shipped, as FDA wrote it.",
    "voluntary_mandated": "Whether the firm recalled on its own or FDA ordered it.",
    "initial_firm_notification": "How the firm told its customers, like a letter or a phone call.",
    "product_type": "Always Drugs here.",
    "address_1": FIRM_ADDRESS, "address_2": FIRM_ADDRESS, "city": FIRM_ADDRESS,
    "state": FIRM_ADDRESS, "postal_code": FIRM_ADDRESS, "country": FIRM_ADDRESS,
    "openfda": "FDA's annotations as JSON text, like generic names and NDCs, when FDA could match "
               "the product. Often empty for compounded or unusual products.",
    "_content_hash": "A fingerprint of the recall report, leaving out openfda. It shows when FDA "
                     "really changed a recall.",
    "_first_seen": "The day the pipeline first stored this recall number.",
    "_pulled_at": "When this version was pulled.",
}

SHORTAGE_COLUMNS = {
    "snapshot_date": "The day the list was pulled.",
    "shortage_key": "The pipeline's ID for one listing: package NDC, list type and company. "
                    "Listings without an NDC get a fingerprint of the name, company and "
                    "presentation instead, starting with h:.",
    "list_type": "shortage or discontinuation, read from the status.",
    "fda_listings": "How many times FDA listed this exact key that day. Usually 1, and duplicates "
                    "are merged into one row.",
    "package_ndc": "The package NDC as FDA wrote it.",
    "generic_name": "The drug's generic name as FDA wrote it, like Dopamine Hydrochloride Injection.",
    "company_name": "The company with the listing.",
    "presentation": "The strength and package, as FDA wrote it.",
    "dosage_form": "Like Injection or Tablet.",
    "status": "Current, Resolved or To Be Discontinued.",
    "availability": "FDA's note on how available it is, like Limited.",
    "shortage_reason": "The reason the company gave FDA, like increased demand.",
    "therapeutic_category": "FDA's categories as JSON list text, like [\"Anesthesia\"].",
    "initial_posting_date": f"When FDA first posted the listing, {MMDDYYYY}. The analysis "
                            "uses it as the day a shortage started.",
    "update_date": f"When FDA last updated the listing, {MMDDYYYY}.",
    "update_type": "What the last update was, as FDA wrote it.",
    "discontinued_date": f"When the product was discontinued, {MMDDYYYY}.",
    "change_date": f"When the listing last changed status, {MMDDYYYY}.",
    "resolved_note": "FDA's note when a shortage was resolved.",
    "openfda": "FDA's annotations as JSON text, when FDA could match the product.",
}

NDC_COLUMNS = {
    "product_ndc": "The labeler and product part of the NDC, like 0409-1105.",
    "generic_name": "The drug's generic name.",
    "brand_name": "The brand name, if it has one.",
    "labeler_name": "The company that lists the product, which can be a repackager.",
    "dosage_form": "Like INJECTION, SOLUTION.",
    "route": "How it's given, as JSON list text, like [\"INTRAVENOUS\"].",
    "product_type": "Like HUMAN PRESCRIPTION DRUG.",
    "marketing_category": "Like ANDA, NDA or BLA.",
    "active_ingredients": "Names and strengths as JSON list text.",
    "packaging": "Each package and its 11-digit code, as JSON list text.",
    "marketing_start_date": f"When marketing started, {YYYYMMDD}.",
    "marketing_end_date": f"When marketing ended, if it has, {YYYYMMDD}.",
    "listing_expiration_date": f"When the listing expires, {YYYYMMDD}.",
    "finished": "true for finished products, false for bulk ingredients.",
}

ID_COLUMNS = {
    "firm_key": "The company name cleaned up for matching (see firms.py), like HOSPIRA.",
    "ndc11": "A package NDC in 5-4-2 form, like 00409-1105-01. Empty when only a product "
             "code was found.",
    "ndc9": "The product part, 5-4, like 00409-1105. Empty when no NDC was found at all.",
    "source": "Where the code came from: text, text_product, directory_lookup, openfda, "
              "openfda_product, or none.",
}

TABLES = [
    {"file": "recalls.parquet", "name": "recalls",
     "row": "one recall number, with FDA's latest version of it",
     "made_by": "ingest.py, step 1. The first run loads FDA's full history from openFDA's bulk "
                "files. Every run after that pulls the last 60 days again and merges them in by "
                "recall number, so FDA's corrections land too.",
     "columns": RECALL_COLUMNS,
     "others": f"FDA's enforcement report field, kept as sent. See {ENFORCEMENT_DOCS}"},
    {"file": "recall_versions.parquet", "name": "recall_versions",
     "row": "one version of a recall. A new row only when FDA changes a recall's content",
     "made_by": "ingest.py, step 1. Nothing is ever deleted, so this is the full edit history.",
     "columns": RECALL_COLUMNS,
     "others": f"FDA's enforcement report field, kept as sent. See {ENFORCEMENT_DOCS}"},
    {"file": "shortage_snapshots.parquet", "name": "shortage_snapshots",
     "row": "one listing on FDA's shortage or discontinuation list on one day",
     "made_by": "ingest.py, step 2. Every run saves the whole list as that day's snapshot. "
                "Running twice in a day replaces that day. It keeps the lean columns, so the "
                "file stays small for years.",
     "columns": {k: v for k, v in SHORTAGE_COLUMNS.items() if k != "openfda"}},
    {"file": "shortages_current.parquet", "name": "shortages_current",
     "row": "one listing on FDA's lists today, with every field FDA sends",
     "made_by": "ingest.py, step 2. Replaced every run.",
     "columns": SHORTAGE_COLUMNS,
     "others": f"FDA's drug shortage field, kept as sent. See {SHORTAGE_DOCS}"},
    {"file": "shortage_history.parquet", "name": "shortage_history",
     "row": "one listing ever seen in the daily snapshots",
     "made_by": "ingest.py, step 2, from shortage_snapshots.",
     "columns": {
         "shortage_key": SHORTAGE_COLUMNS["shortage_key"],
         "first_seen": "The first day the pipeline saw the listing.",
         "last_seen": "The last day it saw the listing. Before the latest snapshot means it "
                      "dropped off FDA's list.",
         "days_seen": "How many daily snapshots had it.",
         "latest_status": "Its status on the last day it was seen.",
         "generic_name": "Its latest generic name.",
         "company_name": "Its latest company.",
     }},
    {"file": "ndc.parquet", "name": None,
     "row": "one product in FDA's NDC directory",
     "made_by": "ingest.py, step 3, from openFDA's bulk file once a week. Only the columns "
                "matching and maker counts need are kept.",
     "columns": NDC_COLUMNS,
     "others": f"FDA's NDC directory field. See {NDC_DOCS}"},
    {"file": "ndc_directory.parquet", "name": "ndc_directory",
     "row": "one package in the NDC directory, with codes in the pipeline's format",
     "made_by": "identify.py, in step 4.",
     "columns": {**{k: ID_COLUMNS[k] for k in ("ndc11", "ndc9", "firm_key")},
                 "labeler_name": NDC_COLUMNS["labeler_name"],
                 "generic_name": NDC_COLUMNS["generic_name"],
                 "dosage_form": NDC_COLUMNS["dosage_form"]}},
    {"file": "recall_ids.parquet", "name": "recall_ids",
     "row": "one NDC found for a recall. A recall with no NDC still gets one row, for its "
            "firm key",
     "made_by": "identify.py, in step 4. Codes come from the product text, the openfda "
                "annotations, and the NDC directory for codes written without dashes.",
     "columns": {"recall_number": RECALL_COLUMNS["recall_number"], **ID_COLUMNS}},
    {"file": "shortage_ids.parquet", "name": "shortage_ids",
     "row": "one NDC found for a shortage listing, for every listing ever seen",
     "made_by": "identify.py, in step 4, so listings that dropped off FDA's list keep their IDs.",
     "columns": {"shortage_key": SHORTAGE_COLUMNS["shortage_key"], **ID_COLUMNS}},
    {"file": "recall_drugs.parquet", "name": "recall_drugs",
     "row": "one recall number, with the drug it's about",
     "made_by": "match.py, in steps 5 and 6.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "drug_key": "The drug's cleaned generic name, like heparin sodium. Empty when nothing "
                     "could name it.",
         "id_source": "How the drug was named, first that works: ndc_directory, openfda, "
                      "text_name, text_brand, or claude. Empty when nothing could.",
     }},
    {"file": "shortage_drugs.parquet", "name": "shortage_drugs",
     "row": "one shortage listing, with its drug and company keys",
     "made_by": "match.py, in step 5.",
     "columns": {
         "shortage_key": SHORTAGE_COLUMNS["shortage_key"],
         "drug_key": "The drug's cleaned generic name, written the same way as recall_drugs.",
         "firm_key": ID_COLUMNS["firm_key"],
         "generic_name": "FDA's name for the drug.",
     }},
    {"file": "recall_shortage_links.parquet", "name": "links",
     "row": "one recall and one shortage listing of the same drug, at the strongest level "
            "that matched",
     "made_by": "match.py, in steps 5 and 6. This is the way to connect recalls and shortages.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "shortage_key": SHORTAGE_COLUMNS["shortage_key"],
         "match_rank": "1 to 4, strongest first.",
         "match_level": "package (the same 11-digit NDC), product (the same product code), "
                        "drug_and_firm (the same drug and company) or drug (the same drug, any "
                        "company, the loosest).",
         "recall_report_date": RECALL_COLUMNS["report_date"],
         "recall_initiation_date": RECALL_COLUMNS["recall_initiation_date"],
         "recall_class": RECALL_COLUMNS["classification"],
         "shortage_generic_name": "The listing's generic name.",
         "shortage_status": "The listing's latest status.",
         "shortage_list_type": "shortage or discontinuation.",
         "shortage_posted": SHORTAGE_COLUMNS["initial_posting_date"],
     }},
    {"file": "unmatched_recalls.parquet", "name": "unmatched_recalls",
     "row": "one recall with no NDC and no drug name the pipeline could recognize",
     "made_by": "match.py. It's the work queue for Claude's drug names.",
     "columns": {name: RECALL_COLUMNS[name] for name in
                 ("recall_number", "recalling_firm", "product_description", "report_date",
                  "classification")}},
    {"file": "recall_root_causes.parquet", "name": "root_causes",
     "row": "one recall number, with its root cause",
     "made_by": "tagging.py, step 7. The rules in sql/root_cause_rules.sql go first, and Claude "
                "Haiku tags what they can't.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "root_cause": "One of the 12 categories in audit.py, like Sterility or CGMP. Empty when "
                       "nothing has tagged it yet.",
         "source": "rule or claude.",
         "confidence": "Claude's own: high, medium or low. Empty for rules.",
         "why": "Claude's one-line reason. Empty for rules.",
     }},
    {"file": "claude_tags.parquet", "name": "claude_tags",
     "row": "one Claude answer for one recall's reason text. It's the cache, so nothing is "
            "asked twice",
     "made_by": "tagging.py, step 7.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "reason_hash": "A fingerprint of the reason text. Each distinct reason is asked once.",
         "root_cause": "Claude's category, limited to the 12 by the tool's schema.",
         "confidence": "high, medium or low.",
         "why": "Claude's one-line reason.",
         "model": "The Claude model that answered.",
         "prompt_version": "The prompt it answered. A new prompt version asks again.",
         "tagged_at": "When it answered.",
     }},
    {"file": "tag_review.csv", "name": None,
     "row": "one distinct reason text Claude tagged with low or medium confidence, for a "
            "person to check",
     "made_by": "tagging.py, step 7. The weekly digest's Excel file has it too.",
     "columns": {
         "reason_for_recall": RECALL_COLUMNS["reason_for_recall"],
         "recalls": "How many recalls share this reason text.",
         "root_cause": "Claude's category.",
         "confidence": "low or medium.",
         "why": "Claude's one-line reason.",
         "example_recall": "One recall number with this reason, to look it up.",
     }},
    {"file": "claude_drugs.parquet", "name": "claude_drugs",
     "row": "one Claude reading of one product description. It's the cache, so nothing is "
            "asked twice",
     "made_by": "extract.py, step 6.",
     "columns": {
         "text_hash": "A fingerprint of the product description.",
         "ingredients": "The active ingredients by generic name, as Claude read them.",
         "drug_key": "Claude's drug as a cleaned name. Matching only uses it when it's a drug "
                     "known to exist, or a combination whose every part is one.",
         "strength": "The strength, as Claude read it.",
         "dosage_form": "The dosage form, as Claude read it.",
         "compounded": "Whether Claude thinks it was compounded.",
         "confidence": "high, medium or low.",
         "model": "The Claude model that answered.",
         "prompt_version": "The prompt it answered. A new prompt version asks again.",
         "extracted_at": "When it answered.",
     }},
    {"file": "extract_review.csv", "name": None,
     "row": "one recall whose Claude drug name wasn't used, with why",
     "made_by": "extract.py, step 6. The weekly digest's Excel file has it too.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "recalling_firm": RECALL_COLUMNS["recalling_firm"],
         "product_description": RECALL_COLUMNS["product_description"],
         "ingredients": "The active ingredients, as Claude read them.",
         "confidence": "high, medium or low.",
         "problem": "Why it wasn't used, like low confidence or a drug that isn't known to exist.",
     }},
    {"file": "recall_risk.parquet", "name": "recall_risk",
     "row": "one recall number, with its risk flag",
     "made_by": "risk.py, step 8. See risk.py for why the flag is built the way it is.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "event_id": RECALL_COLUMNS["event_id"],
         "report_date": RECALL_COLUMNS["report_date"],
         "recall_class": RECALL_COLUMNS["classification"],
         "root_cause": "The recall's root cause, from root_causes.",
         "drug_key": "The recall's drug, from recall_drugs.",
         "labelers": "How many companies list this drug in the NDC directory, leaving out "
                     "declared repackagers. Shown as a fact, not part of the flag.",
         "injectable": "Whether the product is an injectable, read from the product text. Eye "
                       "drops in vials don't count.",
         "in_shortage": "Whether the drug is on FDA's shortage list right now, at any match level.",
         "points": "0 to 3: 2 when in_shortage, 1 when injectable.",
         "flag": "high (2 points or more), watch (1, an injectable) or low (0).",
         "reasons": "The signs behind the points, like on the shortage list now, injectable.",
     }},
    {"file": "risk_log.csv", "name": None,
     "row": "one flag given to a newly reported recall, on the day it was given",
     "made_by": "risk.py, step 8. Each recall is logged once, within 30 days of its report. "
                "Checking these flags against shortages that come later is the honest test of "
                "the flag, which python -m shortagesignal.risk check-log runs. Flags before "
                "2026-10-26 used the old points.",
     "columns": {
         "recall_number": RECALL_COLUMNS["recall_number"],
         "report_date": RECALL_COLUMNS["report_date"],
         "flagged_on": "The day the flag was given.",
         "flag": "high, watch or low.",
         "points": "The points behind it.",
         "reasons": "The signs behind the points.",
     }},
    {"file": "drug_makers.parquet", "name": "drug_makers",
     "row": "one drug in the NDC directory, with how many companies list it",
     "made_by": "risk.py, step 8.",
     "columns": {
         "drug_key": "The drug's cleaned generic name.",
         "labelers": "How many companies list it, leaving out declared repackagers.",
     }},
    {"file": "weekly_recalls.parquet", "name": "weekly_recalls",
     "row": "one week, Monday to Sunday, by the week FDA reported the recalls",
     "made_by": "risk.py, step 8, from sql/weekly_recall_events.sql. Weeks with no recalls are "
                "there as zeros, and the current week is left out until it's over.",
     "columns": {
         "week": "The Monday the week starts on.",
         "events": "Recall events reported that week. The control chart counts these.",
         "recalls": "Recall numbers reported that week.",
         "center": "The average weekly events over the baseline: the 2 years before the "
                   "latest 13 weeks.",
         "ucl": "The upper control limit. A week above it is unusually busy.",
         "lcl": "The lower control limit, never below 0.",
         "signal": "above or below when the week falls outside the limits. Empty otherwise.",
     }},
    {"file": "run_log.csv", "name": None,
     "row": "one pipeline run, whether it worked or not",
     "made_by": "ingest.py, at the end of every run. The weekly digest and the dashboard read it.",
     "columns": {
         "run_at_utc": "When the run started, in UTC.",
         "status": "success or failed.",
         "seconds": "How long it took.",
         "recalls_mode": "Full history on the first run, then the last 60 days.",
         "recalls_pulled": "Recall rows pulled this run.",
         "recalls_new": "Recall numbers never stored before.",
         "recalls_changed": "Stored recalls FDA changed since the last version.",
         "recalls_total": "Recall numbers stored after the run.",
         "shortage_rows": "Listings in today's snapshot.",
         "shortages_new": "Listings that weren't in the last snapshot.",
         "shortages_dropped": "Listings that dropped off since the last snapshot.",
         "shortage_status_changes": "Listings whose status changed since the last snapshot.",
         "duplicate_listings_merged": "Rows FDA listed twice under the same key.",
         "ndc_refreshed": "yes when the NDC directory was refreshed this run.",
         "recalls_with_ndc_pct": "Percent of recalls with at least one NDC found.",
         "shortages_with_ndc_pct": "Percent of shortage listings with an NDC.",
         "recalls_identified_pct": "Percent of recalls with an NDC or a drug name.",
         "recalls_unmatched": "Recalls with neither, the unmatched_recalls table.",
         "recalls_linked": "Recalls linked to at least one shortage listing.",
         "shortages_linked": "Shortage listings linked to at least one recall.",
         "recalls_named_pct_before": "Percent of recalls with a drug name before Claude's names.",
         "recalls_named_pct": "Percent with a drug name after Claude's names.",
         "recalls_named_by_claude": "Recalls named only by Claude.",
         "extract_calls": "Claude calls for drug names this run.",
         "extract_cost_usd": "What they cost, in dollars.",
         "extract_waiting": "Recalls still waiting for Claude to name the drug.",
         "recalls_tagged_pct": "Percent of recalls with a root cause.",
         "tag_backlog": "Recalls still waiting for a root cause.",
         "claude_calls": "Claude calls for root causes this run.",
         "claude_cost_usd": "What they cost, in dollars.",
         "risk_high_30d": "Recalls reported in the last 30 days flagged high.",
         "risk_watch_30d": "Recalls reported in the last 30 days flagged watch.",
         "weekly_events_last": "Recall events in the latest complete week.",
         "weekly_signal": "above or below when that week is outside the control limits.",
         "checks_warned": "Data checks that warned.",
         "checks_failed": "Data checks that failed. Any failure stops the run before saving.",
         "error": "What went wrong, when the run failed.",
     }},
    {"file": "check_log.csv", "name": None,
     "row": "one data check in one run",
     "made_by": "checks.py, at the end of every run. The spike and went-quiet rules compare "
                "against this history. The runbook says what each check means.",
     "columns": {
         "run_at_utc": "When the run started, in UTC.",
         "check": "The check's name.",
         "severity": "error (stops the run) or warning (only reported).",
         "value": "The number the check looked at.",
         "status": "pass, warn or fail.",
         "detail": "What was wrong, when something was.",
     }},
    {"file": "state.json", "name": None,
     "row": "the pipeline's bookkeeping, one value per key",
     "made_by": "ingest.py.",
     "columns": {
         "ndc_refreshed": "The day the NDC directory was last refreshed. It's refreshed when "
                          "this is 7 days old.",
         "last_run": "The time of the last successful run, in UTC.",
     }},
]

TYPES = {"VARCHAR": "text", "BIGINT": "whole number", "INTEGER": "whole number",
         "SMALLINT": "whole number", "TINYINT": "whole number", "HUGEINT": "whole number",
         "DOUBLE": "number", "FLOAT": "number", "BOOLEAN": "true/false", "DATE": "date"}


def nice_type(duckdb_type):
    """A plain name for a DuckDB type, like text or date."""
    t = str(duckdb_type).upper()
    if t.startswith("TIMESTAMP"):
        return "timestamp"
    if t.startswith("DECIMAL"):
        return "number"
    return TYPES.get(t, t.lower())


def read_schema(con, path):
    """([(column, type)], rows) for a Parquet, CSV or JSON file."""
    p = path.as_posix()
    if path.suffix == ".parquet":
        columns = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall()
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
        return [(c[0], nice_type(c[1])) for c in columns], rows
    if path.suffix == ".csv":
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
        return [(c, "text") for c in header], rows
    state = json.loads(path.read_text(encoding="utf-8"))
    return [(k, type(v).__name__.replace("str", "text")) for k, v in state.items()], 1


def build(data_dir, today):
    """(markdown, warnings) for every file in data_dir that the dictionary knows about."""
    con = duckdb.connect()
    found, warnings = [], []
    for table in TABLES:
        path = Path(data_dir) / table["file"]
        if not path.exists():
            warnings.append(f"{table['file']}: not in {data_dir}, so it's left out")
            continue
        columns, rows = read_schema(con, path)
        names = {c for c, _ in columns}
        for described in table["columns"]:
            if described not in names and not table.get("others"):
                warnings.append(f"{table['file']}: describes {described}, which the file "
                                "doesn't have")
        found.append((table, columns, rows))

    lines = ["# Data dictionary", "",
             "Every file the daily pipeline keeps, what one row means, and what each column "
             "holds. The files live on the `data` branch. This page was built from them on "
             f"{today:%b} {today.day}, {today.year} by `python -m shortagesignal.dictionary`, "
             "so the columns and types are exactly what's in the data. Run it again after the "
             "pipeline changes.", "",
             "To query the Parquet tables, `python -m shortagesignal.run_sql` gives each one the "
             "short name in the second column. The dashboard's Ask the data tab sees simpler "
             "versions of six of them, described in `ask.py`.", "",
             "| File | Query it as | One row is | Rows |", "|---|---|---|---|"]
    for table, _, rows in found:
        name = f"`{table['name']}`" if table["name"] else ""
        lines.append(f"| [{table['file']}](#{table['file'].replace('.', '')}) | {name} | "
                     f"{table['row']} | {rows:,} |")
    for table, columns, rows in found:
        lines += ["", f"## {table['file']}", "",
                  f"**One row is** {table['row']}. **Made by** {table['made_by']}", "",
                  "| Column | Type | What it holds |", "|---|---|---|"]
        for column, kind in columns:
            text = table["columns"].get(column) or table.get("others") or "*Not described yet.*"
            lines.append(f"| `{column}` | {kind} | {text} |")
    return "\n".join(lines) + "\n", warnings


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        sys.exit("usage: python -m shortagesignal.dictionary")
    text, warnings = build(DATA_DIR, date.today())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    undescribed = text.count("*Not described yet.*")
    for w in warnings:
        print("warning:", w)
    print(f"Saved {OUT_PATH} ({undescribed} columns not described yet)")


if __name__ == "__main__":
    main()
