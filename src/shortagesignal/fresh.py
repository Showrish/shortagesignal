"""Day 14: fresh hand labels, for honest scores on recalls nothing was tuned on.

  python -m shortagesignal.fresh sample   30 new recalls into audit/fresh_sheet.xlsx, to label blind
  python -m shortagesignal.fresh score    score the pipeline against your labels

The first hand audit (Day 7) became the answer key that the root-cause rules, Claude's prompts
and the drug-name checks were tuned on, so scores on it are optimistic. These recalls are new:
none of them was in the first audit's sheet. They come in three groups of 10, so each part gets
tested even though Claude handles only a small share of recalls:
  rules        root cause tagged by the rules in sql/root_cause_rules.sql
  claude_tag   root cause tagged by Claude
  claude_drug  drug named by Claude
Each group takes at most one recall per recall event, so one big event can't fill a group.

The sheet is blind: it shows each recall's text and nothing the pipeline concluded, in a
shuffled order. What the pipeline concluded is frozen in audit/fresh_pipeline.csv when the
sample is drawn, so the score is against those answers as they were. Don't open that file
until you've scored.
"""
import argparse
import csv
import hashlib
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from shortagesignal.audit import (
    AUDIT_DIR,
    BOLD,
    FONT,
    GREY,
    ROOT_CAUSES,
    SHEET_PATH,
    WRAP,
    YELLOW,
    read_sheet,
)
from shortagesignal.config import RECALL_DRUGS_PATH, RECALLS_PATH, ROOT_CAUSES_PATH
from shortagesignal.drugs import drug_key
from shortagesignal.extract import base_key

FRESH_SHEET = AUDIT_DIR / "fresh_sheet.xlsx"
FRESH_PIPELINE = AUDIT_DIR / "fresh_pipeline.csv"
FRESH_KEY = AUDIT_DIR / "fresh_key.csv"
FRESH_RESULTS = AUDIT_DIR / "fresh_labels.md"
SEED = "shortagesignal-fresh-1"
PER_GROUP = 10
GROUPS = {
    "rules": "rc.source = 'rule'",
    "claude_tag": "rc.source = 'claude'",
    "claude_drug": "d.id_source = 'claude'",
}
SHOWN = ["recall_number", "report_date", "class", "firm", "product_description",
         "reason_for_recall"]
YOURS = ["root_cause", "drug", "notes"]
PIPELINE = ["recall_number", "group", "root_cause", "root_cause_source", "confidence",
            "drug_key", "drug_source"]
CANT_TELL = "can't tell"
WIDTHS = {"firm": 24, "product_description": 60, "reason_for_recall": 50, "root_cause": 26,
          "drug": 30, "notes": 30}
HOW_TO = [
    ("root_cause", "The one category that best fits reason_for_recall. See the list below"),
    ("drug", "The active ingredient by its generic name, with the salt if the text gives it, "
             "like heparin sodium. For a combination, join them with +, like lidocaine + "
             "epinephrine. Write can't tell if the text doesn't say which drug it is"),
    ("notes", "Anything worth remembering. Optional"),
]


# ---------------------------------------------------------------- the sample

def already_audited(sheet_path=SHEET_PATH, key_path=AUDIT_DIR / "answer_key.csv"):
    """Every recall number in the first audit's sheet or its answer key."""
    numbers = set()
    if Path(sheet_path).exists():
        numbers |= {r["recall_number"] for r in read_sheet(sheet_path) if r.get("recall_number")}
    if Path(key_path).exists():
        with open(key_path, newline="", encoding="utf-8") as f:
            numbers |= {r["recall_number"] for r in csv.DictReader(f) if r.get("recall_number")}
    return numbers


def sample_rows(con, paths, exclude, seed=SEED, per_group=PER_GROUP):
    """per_group recalls from each group, at most one per recall event, none in exclude and
    none in two groups. Returns dicts with the recall's text and what the pipeline concluded."""
    p = {name: Path(path).as_posix() for name, path in paths.items()}
    con.execute("CREATE OR REPLACE TEMP TABLE excluded (recall_number VARCHAR)")
    if exclude:
        con.executemany("INSERT INTO excluded VALUES (?)", [(n,) for n in sorted(exclude)])
    picked, rows = set(), []
    for group, where in GROUPS.items():
        found = con.execute(f"""
            SELECT r.recall_number, r.report_date, r.classification, r.recalling_firm,
                   r.product_description, r.reason_for_recall, rc.root_cause,
                   rc.source, rc.confidence, d.drug_key, d.id_source
            FROM read_parquet('{p['recalls']}') AS r
            JOIN read_parquet('{p['root_causes']}') AS rc ON rc.recall_number = r.recall_number
            JOIN read_parquet('{p['recall_drugs']}') AS d ON d.recall_number = r.recall_number
            WHERE {where}
              AND r.recall_number NOT IN (SELECT recall_number FROM excluded)
            QUALIFY row_number() OVER (
                PARTITION BY r.event_id ORDER BY md5(r.recall_number || '{seed}')) = 1
            ORDER BY md5(r.recall_number || '{seed}')
        """).fetchall()
        taken = 0
        for (number, reported, recall_class, firm, description, reason, root_cause, source,
             confidence, key, key_source) in found:
            if number in picked:
                continue
            picked.add(number)
            rows.append({"recall_number": number, "report_date": reported, "class": recall_class,
                         "firm": firm, "product_description": description,
                         "reason_for_recall": reason, "group": group,
                         "root_cause": root_cause or "", "root_cause_source": source or "",
                         "confidence": confidence or "", "drug_key": key or "",
                         "drug_source": key_source or ""})
            taken += 1
            if taken == per_group:
                break
    # a shuffled order, so the groups can't be told apart in the sheet
    return sorted(rows, key=lambda r: hashlib.md5((r["recall_number"] + "order").encode()).hexdigest())


def make_sheet(rows, path):
    """The blind workbook: a Labels tab to fill in, and a How to fill tab."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Labels"
    columns = SHOWN + YOURS
    ws.append(columns)
    for row in rows:
        ws.append([row.get(c, "") if c in SHOWN else "" for c in columns])
    for i, name in enumerate(columns, start=1):
        letter = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[letter].width = WIDTHS.get(name, 15)
        for cell in ws[letter]:
            cell.font = FONT
            cell.alignment = WRAP
            if name in YOURS:
                cell.fill = YELLOW
        ws.cell(row=1, column=i).font = BOLD
        if name not in YOURS:
            ws.cell(row=1, column=i).fill = GREY
    rule = DataValidation(type="list", formula1='"' + ",".join(ROOT_CAUSES) + '"', allow_blank=True)
    letter = ws.cell(row=1, column=columns.index("root_cause") + 1).column_letter
    rule.add(f"{letter}2:{letter}{len(rows) + 1}")
    ws.add_data_validation(rule)
    ws.freeze_panes = "B2"

    guide = wb.create_sheet("How to fill")
    guide.column_dimensions["A"].width = 32
    guide.column_dimensions["B"].width = 100
    lines = [("Label blind", "Use only the recall's own text. Don't look the recall up in the "
                             "dashboard, the data or audit/fresh_pipeline.csv first"),
             ("Grey columns", "The recall, as FDA reported it. Don't edit these"),
             ("Yellow columns", "Yours to fill in, one row per recall"), ("", "")]
    lines += HOW_TO + [("", ""), ("Root causes", "")] + list(ROOT_CAUSES.items())
    for label, text in lines:
        guide.append([label, text])
    for row in guide.iter_rows():
        for cell in row:
            cell.font = FONT
            cell.alignment = WRAP
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def save_pipeline(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PIPELINE, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["recall_number"]))


# ---------------------------------------------------------------- the score

def read_labels(path):
    ws = load_workbook(path, read_only=True, data_only=True)["Labels"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows)]
    return [{h: str(v).strip() if v is not None else "" for h, v in zip(header, values)}
            for values in rows if any(v is not None and str(v).strip() for v in values)]


def score(labels, pipeline):
    """Root causes by who tagged them, and drug names by who named them, against your labels."""
    answers = {p["recall_number"]: p for p in pipeline}
    causes = {"rule": [0, 0], "claude": [0, 0]}
    drugs = {"claude": [0, 0, 0], "matching": [0, 0, 0]}   # exact, ignoring salts, scored
    result = {"labeled": 0, "cant_tell": 0, "not_named": 0, "misses": []}
    for row in labels:
        p = answers.get(row.get("recall_number"))
        if not p:
            continue
        result["labeled"] += 1
        mine = row.get("root_cause", "")
        if mine and p["root_cause_source"] in causes:
            right = mine == p["root_cause"]
            causes[p["root_cause_source"]][0] += right
            causes[p["root_cause_source"]][1] += 1
            if not right:
                result["misses"].append((p["recall_number"], p["group"], "root cause", mine,
                                         p["root_cause"] or "nothing"))
        named = row.get("drug", "")
        if not named or named.lower() == CANT_TELL:
            result["cant_tell"] += 1
            continue
        truth, theirs = drug_key(named), p["drug_key"]
        if not theirs:
            result["not_named"] += 1
            result["misses"].append((p["recall_number"], p["group"], "drug", truth or named,
                                     "nothing"))
            continue
        by = "claude" if p["drug_source"] == "claude" else "matching"
        exact, loose = truth == theirs, base_key(truth) == base_key(theirs)
        drugs[by][0] += exact
        drugs[by][1] += loose
        drugs[by][2] += 1
        if not loose:
            result["misses"].append((p["recall_number"], p["group"], "drug", truth or named,
                                     theirs))
    result["causes"], result["drugs"] = causes, drugs
    return result


def _rate(part, whole):
    return f"{part} of {whole} ({round(100 * part / whole)}%)" if whole else "none to score"


def write_results(labels, result, today, out_path=FRESH_RESULTS, key_path=FRESH_KEY):
    with open(key_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["recall_number"] + YOURS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(labels, key=lambda r: r["recall_number"]))
    c, d = result["causes"], result["drugs"]
    lines = [
        "# Fresh hand labels", "",
        f"{result['labeled']} recalls labeled blind on {today}. None of them was in the first "
        "audit, so nothing was tuned on them. They were drawn as three groups of 10: root cause "
        "tagged by the rules, root cause tagged by Claude, and drug named by Claude, with at "
        "most one recall per recall event. The scores below count every recall by who actually "
        "tagged or named it, so the rows don't add up to 10 each.", "",
        "For the scores on the first audit, see tagging_results.md and extraction_results.md.", "",
        "## Root causes", "",
        "| Tagged by | Right |", "|---|---|",
        f"| Rules | {_rate(*c['rule'])} |",
        f"| Claude | {_rate(*c['claude'])} |",
        f"| All | {_rate(c['rule'][0] + c['claude'][0], c['rule'][1] + c['claude'][1])} |", "",
        "## Drug names", "",
        "Recall text often leaves the salt off, so the second column counts fentanyl and fentanyl "
        "citrate as the same drug.", "",
        "| Named by | Exact name | Ignoring salts |", "|---|---|---|",
        f"| Claude | {_rate(d['claude'][0], d['claude'][2])} | {_rate(d['claude'][1], d['claude'][2])} |",
        f"| Matching (NDC, FDA's annotations or the text) | {_rate(d['matching'][0], d['matching'][2])} "
        f"| {_rate(d['matching'][1], d['matching'][2])} |", "",
        f"The pipeline named no drug for {result['not_named']} recalls where the label did. "
        f"{result['cant_tell']} recalls didn't say which drug they were, so they're left out.", "",
        "## Misses", "",
    ]
    if result["misses"]:
        lines += ["| Recall | Group | What | Label | Pipeline |", "|---|---|---|---|---|"]
        lines += [f"| {n} | {g} | {what} | {mine} | {theirs} |"
                  for n, g, what, mine, theirs in sorted(result["misses"])]
    else:
        lines.append("None.")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m shortagesignal.fresh")
    parser.add_argument("step", choices=["sample", "score"])
    parser.add_argument("--force", action="store_true", help="draw the sample again")
    args = parser.parse_args(argv)

    if args.step == "sample":
        if FRESH_SHEET.exists() and not args.force:
            sys.exit(f"{FRESH_SHEET} already exists, and it may have your labels in it. "
                     "Add --force to draw the sample again.")
        import duckdb
        paths = {"recalls": RECALLS_PATH, "root_causes": ROOT_CAUSES_PATH,
                 "recall_drugs": RECALL_DRUGS_PATH}
        rows = sample_rows(duckdb.connect(), paths, already_audited())
        make_sheet(rows, FRESH_SHEET)
        save_pipeline(rows, FRESH_PIPELINE)
        print(f"Wrote {len(rows)} recalls to {FRESH_SHEET}. Download it, fill in the yellow "
              "columns using only each recall's text, upload it back to the same place, then run: "
              "python -m shortagesignal.fresh score")
    else:
        if not FRESH_PIPELINE.exists():
            sys.exit("Draw the sample first: python -m shortagesignal.fresh sample")
        labels = read_labels(FRESH_SHEET)
        with open(FRESH_PIPELINE, newline="", encoding="utf-8") as f:
            pipeline = list(csv.DictReader(f))
        lines = write_results(labels, score(labels, pipeline), date.today().isoformat())
        print("\n".join(lines))
        print(f"\nSaved {FRESH_RESULTS} and {FRESH_KEY}")


if __name__ == "__main__":
    main()
