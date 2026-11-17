"""A hand check of the backtest's automatic route and company comparisons.

  python -m shortagesignal.link_check sample   30 links into audit/link_check_sheet.xlsx, to label blind
  python -m shortagesignal.link_check score    score the automatic comparisons against your labels

The backtest counts a recall as followed three ways: through any link, by a shortage of the same
route, and by one from the same company. The route comes from the recall's text and the shortage
listing's dosage form, and the company from the two sides' cleaned names, both worked out by code.
This checks them by hand on 30 links: 4 package, 4 product, 7 drug and company, and 15 drug-only,
since drug-only links carry most outcomes. It's a pilot. 30 links can show an obvious problem, not
pin down an accuracy.

The sheet is blind: each row shows the recall's text next to the shortage listing's, and not the
link's level or what the code concluded. Those are frozen in audit/link_check_auto.csv when the
sample is drawn. Don't open it until you've scored.
"""
import argparse
import csv
import hashlib
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from shortagesignal.audit import AUDIT_DIR, BOLD, FONT, GREY, WRAP, YELLOW
from shortagesignal.config import (LINKS_PATH, RECALL_IDS_PATH, RECALLS_PATH, SHORTAGE_DRUGS_PATH,
                                   SNAPSHOTS_PATH)
from shortagesignal.risk import route_of

SHEET = AUDIT_DIR / "link_check_sheet.xlsx"
AUTO = AUDIT_DIR / "link_check_auto.csv"
RESULTS = AUDIT_DIR / "link_check.md"
SEED = "shortagesignal-links-1"
PER_LEVEL = {"package": 4, "product": 4, "drug_and_firm": 7, "drug": 15}
SHOWN = ["row", "recall_text", "recall_firm", "shortage_drug", "shortage_presentation",
         "shortage_form", "shortage_company"]
YOURS = ["same_ingredient", "same_route", "same_company", "notes"]
ANSWERS = ["yes", "no", "unclear"]
AUTO_COLUMNS = ["row", "recall_number", "shortage_key", "match_level", "recall_route",
                "shortage_route", "auto_route", "auto_company"]
WIDTHS = {"row": 6, "recall_text": 60, "recall_firm": 22, "shortage_drug": 26,
          "shortage_presentation": 34, "shortage_form": 14, "shortage_company": 22,
          "same_ingredient": 14, "same_route": 12, "same_company": 14, "notes": 28}
HOW_TO = [
    ("same_ingredient", "yes if both sides are the same active drug, ignoring salts and strength. "
                        "no if they're different drugs. unclear if you can't tell"),
    ("same_route", "yes if both are given the same way: injected, by mouth, on the skin, in the "
                   "eye, inhaled and so on. no if not. unclear if a side doesn't say"),
    ("same_company", "yes if the recall's firm and the listing's company are the same company, "
                     "counting a parent and its subsidiary as the same. no if not"),
    ("notes", "Anything worth remembering. Optional"),
]

SAMPLE_SQL = """
WITH listing AS (
    SELECT shortage_key, arg_max(generic_name, snapshot_date) AS generic_name,
           arg_max(presentation, snapshot_date) AS presentation,
           arg_max(dosage_form, snapshot_date) AS dosage_form,
           arg_max(company_name, snapshot_date) AS company_name
    FROM read_parquet('{snapshots}') GROUP BY shortage_key
),
recall_firm AS (
    SELECT recall_number, any_value(firm_key) AS firm_key
    FROM read_parquet('{recall_ids}') GROUP BY recall_number
)
SELECT l.recall_number, l.shortage_key, l.match_level, r.product_description, r.recalling_firm,
       s.generic_name, s.presentation, s.dosage_form, s.company_name,
       f.firm_key AS recall_firm_key, d.firm_key AS shortage_firm_key
FROM read_parquet('{links}') AS l
JOIN read_parquet('{recalls}') AS r ON r.recall_number = l.recall_number
JOIN listing AS s ON s.shortage_key = l.shortage_key
LEFT JOIN recall_firm AS f ON f.recall_number = l.recall_number
LEFT JOIN read_parquet('{shortage_drugs}') AS d ON d.shortage_key = l.shortage_key
WHERE l.match_level = ? AND l.shortage_list_type = 'shortage'
QUALIFY row_number() OVER (PARTITION BY r.event_id ORDER BY md5(l.recall_number || l.shortage_key || '{seed}')) = 1
ORDER BY md5(l.recall_number || l.shortage_key || '{seed}')
LIMIT ?
"""


def compare(recall_text, form, presentation, generic, recall_firm, shortage_firm):
    """What the backtest's code concludes about one link: each side's route, and whether the
    routes and the companies are the same, as same, different or unknown."""
    recall_route = route_of(recall_text)
    shortage_route = route_of(" ".join(x for x in (form, presentation, generic) if x))
    route = ("unknown" if not (recall_route and shortage_route)
             else "same" if recall_route == shortage_route else "different")
    company = ("unknown" if not (recall_firm and shortage_firm)
               else "same" if recall_firm == shortage_firm else "different")
    return recall_route or "", shortage_route or "", route, company


def sample_rows(con, paths, seed=SEED, per_level=PER_LEVEL):
    p = {name: Path(path).as_posix() for name, path in paths.items()}
    sql = SAMPLE_SQL.format(seed=seed, **p)
    rows = []
    for level, n in per_level.items():
        for (number, key, match_level, text, firm, generic, presentation, form, company,
             recall_firm, shortage_firm) in con.execute(sql, [level, n]).fetchall():
            recall_route, shortage_route, route, same_company = compare(
                text, form, presentation, generic, recall_firm, shortage_firm)
            rows.append({"recall_number": number, "shortage_key": key, "match_level": match_level,
                         "recall_text": text or "", "recall_firm": firm or "",
                         "shortage_drug": generic or "", "shortage_presentation": presentation or "",
                         "shortage_form": form or "", "shortage_company": company or "",
                         "recall_route": recall_route, "shortage_route": shortage_route,
                         "auto_route": route, "auto_company": same_company})
    # a shuffled order, so the levels can't be told apart in the sheet
    rows.sort(key=lambda r: hashlib.md5((r["recall_number"] + r["shortage_key"] + "order").encode()).hexdigest())
    for i, row in enumerate(rows, start=1):
        row["row"] = i
    return rows


def make_sheet(rows, path):
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
    choices = DataValidation(type="list", formula1='"' + ",".join(ANSWERS) + '"', allow_blank=True)
    for name in YOURS[:3]:
        letter = ws.cell(row=1, column=columns.index(name) + 1).column_letter
        choices.add(f"{letter}2:{letter}{len(rows) + 1}")
    ws.add_data_validation(choices)
    ws.freeze_panes = "B2"
    guide = wb.create_sheet("How to fill")
    guide.column_dimensions["A"].width = 20
    guide.column_dimensions["B"].width = 100
    for label, text in [("Label blind", "Use only the two texts on each row. Don't open "
                                         "audit/link_check_auto.csv or look the link up first"),
                        ("Grey columns", "The recall on the left, the shortage listing on the right"),
                        ("Yellow columns", "Yours: yes, no or unclear from the drop-down"),
                        ("", "")] + HOW_TO:
        guide.append([label, text])
    for row in guide.iter_rows():
        for cell in row:
            cell.font = FONT
            cell.alignment = WRAP
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def save_auto(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUTO_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------- the score

def read_labels(path):
    ws = load_workbook(path, read_only=True, data_only=True)["Labels"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows)]
    return [{h: str(v).strip().lower() if v is not None else "" for h, v in zip(header, values)}
            for values in rows if any(v is not None and str(v).strip() for v in values)]


def score(labels, auto):
    """How often the code's route and company answers agree with yours, where you said yes or
    no, and how often each link level joins the same ingredient."""
    by_row = {str(a["row"]): a for a in auto}
    result = {}
    for field, auto_field in (("same_route", "auto_route"), ("same_company", "auto_company")):
        pairs = Counter()
        for label in labels:
            a = by_row.get(str(label.get("row", "")).split(".")[0])
            if a and label.get(field) in ("yes", "no"):
                pairs[(a[auto_field], label[field])] += 1
        judged = sum(n for (code, _), n in pairs.items() if code != "unknown")
        agree = pairs[("same", "yes")] + pairs[("different", "no")]
        result[field] = {"pairs": pairs, "judged": judged, "agree": agree,
                         "code_unknown": sum(n for (code, _), n in pairs.items() if code == "unknown")}
    levels = {}
    for label in labels:
        a = by_row.get(str(label.get("row", "")).split(".")[0])
        if a and label.get("same_ingredient") in ("yes", "no"):
            yes, n = levels.get(a["match_level"], (0, 0))
            levels[a["match_level"]] = (yes + (label["same_ingredient"] == "yes"), n + 1)
    result["ingredient_by_level"] = levels
    result["labeled"] = len(labels)
    return result


def write_results(result, today, path=RESULTS):
    lines = ["# Link hand check", "",
             f"Scored on {today}: {result['labeled']} links labeled blind. A pilot, so it can show an "
             "obvious problem with the automatic comparisons, not pin down their accuracy.", ""]
    for field, name in (("same_route", "Route"), ("same_company", "Company")):
        r, p = result[field], result[field]["pairs"]
        share = f" ({r['agree'] / r['judged']:.0%})" if r["judged"] else ""
        lines += [f"## {name}", "",
                  f"The code agreed with you on {r['agree']} of {r['judged']}{share} links where it gave "
                  f"an answer and you said yes or no. It couldn't tell on {r['code_unknown']}.", "",
                  "| Code said | You said yes | You said no |", "|---|---|---|"]
        for code in ("same", "different", "unknown"):
            lines.append(f"| {code} | {p[(code, 'yes')]} | {p[(code, 'no')]} |")
        lines.append("")
    lines += ["## Same ingredient, by link level", "",
              "| Level | Same ingredient | Labeled |", "|---|---|---|"]
    for level in PER_LEVEL:
        yes, n = result["ingredient_by_level"].get(level, (0, 0))
        lines.append(f"| {level} | {yes} | {n} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m shortagesignal.link_check")
    parser.add_argument("step", choices=["sample", "score"])
    parser.add_argument("--force", action="store_true", help="draw the sample again")
    args = parser.parse_args(argv)
    if args.step == "sample":
        if SHEET.exists() and not args.force:
            sys.exit(f"{SHEET} already exists, and it may have your labels in it. "
                     "Add --force to draw the sample again.")
        import duckdb
        paths = {"links": LINKS_PATH, "recalls": RECALLS_PATH, "snapshots": SNAPSHOTS_PATH,
                 "recall_ids": RECALL_IDS_PATH, "shortage_drugs": SHORTAGE_DRUGS_PATH}
        rows = sample_rows(duckdb.connect(), paths)
        make_sheet(rows, SHEET)
        save_auto(rows, AUTO)
        print(f"Wrote {len(rows)} links to {SHEET}. Download it, fill in the yellow columns from "
              "the two texts on each row, upload it back to the same place, then run: "
              "python -m shortagesignal.link_check score")
    else:
        if not AUTO.exists():
            sys.exit("Draw the sample first: python -m shortagesignal.link_check sample")
        with open(AUTO, newline="", encoding="utf-8") as f:
            auto = list(csv.DictReader(f))
        lines = write_results(score(read_labels(SHEET), auto), date.today().isoformat())
        print("\n".join(lines))
        print(f"\nSaved {RESULTS}")


if __name__ == "__main__":
    main()
