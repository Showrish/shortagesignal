"""
Ask the data: Claude turns a question into one read-only SQL query over the pipeline's tables.

  python -m shortagesignal.ask eval     score Claude's SQL on test questions with known answers

The dashboard's "Ask the data" tab uses this module. How it stays safe and cheap:
  1. The tables are copied into an in-memory database, and then the database is locked, so
     no query can read files, reach the internet or change a setting (build_sandbox).
  2. Claude answers through a tool that returns one SQL query, check_sql only lets a single
     SELECT through, and every query runs with a 200-row limit.
  3. A second short call turns the result rows into a sentence or two, using only those rows.
  4. The dashboard asks for a passcode, caps the questions per day, and uses its own API key
     in a workspace with a monthly spend limit.

The eval runs each test question's reference SQL to get today's right answer, so it never
goes stale as the data changes. A question counts as right when every value in the
reference answer shows up in Claude's result.

This module only needs duckdb and the anthropic SDK, so the dashboard can import it without
installing the pipeline.
"""
import csv
import io
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

MODEL = "claude-haiku-5-5"                     # the same model as tagging.py
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6   # dollars per token
ROW_LIMIT = 200
ROOT_CAUSES = ["Sterility", "CGMP", "Microbial contamination", "Impurities", "Potency",
               "Particulates", "Chemical or foreign contamination", "Failed specification",
               "Container or device defect", "Unapproved drug", "Labeling or packaging", "Other"]

# The tables Claude can query, each built from the pipeline's files with friendlier names.
SANDBOX_SQL = {
    "recalls": """
        SELECT r.recall_number, r.event_id,
               TRY_STRPTIME(r.report_date, '%Y%m%d')::DATE AS report_date,
               TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d')::DATE AS initiation_date,
               r.classification AS recall_class, r.status AS recall_status,
               r.recalling_firm AS firm, r.product_description AS product,
               r.reason_for_recall AS reason, k.drug_key AS drug, c.root_cause,
               k.flag AS risk_flag, k.points AS risk_points, k.reasons AS risk_reasons,
               k.labelers, k.injectable
        FROM read_parquet('{recalls}') AS r
        LEFT JOIN read_parquet('{root_causes}') AS c ON c.recall_number = r.recall_number
        LEFT JOIN read_parquet('{risk}') AS k ON k.recall_number = r.recall_number""",
    "shortages": """
        SELECT shortage_key, generic_name AS drug, company_name AS company, list_type, status,
               availability, shortage_reason,
               NULLIF(trim(regexp_replace(therapeutic_category, '[\\[\\]"]', '', 'g')), '')
                   AS therapeutic_category,
               dosage_form,
               TRY_STRPTIME(initial_posting_date, '%m/%d/%Y')::DATE AS posted
        FROM read_parquet('{shortages}')""",
    "links": """
        SELECT recall_number, shortage_key, match_level, shortage_generic_name AS shortage_drug,
               shortage_status, shortage_list_type,
               TRY_STRPTIME(shortage_posted, '%m/%d/%Y')::DATE AS shortage_posted
        FROM read_parquet('{links}')""",
    "weekly_recalls": """
        SELECT week, events, recalls, center, ucl, lcl, signal FROM read_parquet('{weekly}')""",
    "drug_makers": """
        SELECT drug_key AS drug, labelers AS companies FROM read_parquet('{makers}')""",
    "shortage_history": """
        SELECT shortage_key, generic_name AS drug, company_name AS company, first_seen, last_seen,
               days_seen, latest_status,
               last_seen = (SELECT max(last_seen) FROM read_parquet('{history}')) AS still_listed
        FROM read_parquet('{history}')""",
}

SCHEMA = f"""Tables (DuckDB):

recalls: one row per FDA drug recall number, since June 2012. One recall event can cover many
recall numbers, one per product.
  recall_number (text, like D-0598-2026), event_id (text, the recall event),
  report_date (DATE, when FDA reported it), initiation_date (DATE, when the firm started it;
  use initiation_date for when recalls happened, and report_date only when a question says
  reported),
  recall_class ('Class I', 'Class II' or 'Class III'; Class I is the most serious),
  recall_status ('Ongoing', 'Completed' or 'Terminated'), firm, product, reason,
  drug (lowercase generic name like 'heparin sodium', NULL when not known),
  root_cause (one of: {', '.join(ROOT_CAUSES)}),
  risk_flag ('high', 'watch' or 'low'), risk_points (0 to 5), risk_reasons (text),
  labelers (how many companies list the drug, NULL when not known), injectable (boolean)

shortages: one row per listing on FDA's drug shortage list today.
  shortage_key, drug (generic name, mixed case), company, list_type ('shortage' or
  'discontinuation'), status ('Current', 'Resolved' or 'To Be Discontinued'), availability,
  shortage_reason, therapeutic_category (a listing can have several, joined by ', ', so to
  count by single category use unnest(string_split(therapeutic_category, ', '))), dosage_form,
  posted (DATE, when FDA first posted it)

links: one row per recall and shortage listing of the same drug.
  recall_number, shortage_key, match_level ('package', 'product', 'drug_and_firm' or 'drug',
  strongest first), shortage_drug, shortage_status, shortage_list_type, shortage_posted (DATE)

weekly_recalls: one row per week (Mondays), by FDA report week.
  week (DATE), events (recall events), recalls (recall numbers), center, ucl and lcl (the
  control chart's average and normal range), signal ('above', 'below' or '' for normal)

drug_makers: one row per drug in FDA's NDC directory.
  drug (lowercase generic name, the same style as recalls.drug), companies (how many companies
  list it, leaving out ones that call themselves repackagers or relabelers)

shortage_history: one row per shortage listing ever seen in the daily snapshots.
  shortage_key, drug, company, first_seen and last_seen (DATE, the first and last daily
  snapshot that had it), days_seen, latest_status, still_listed (boolean, on the list in the
  latest snapshot). Daily snapshots started on 2026-10-11, so a listing first seen that day
  may have started earlier, and one that is no longer listed left FDA's list after last_seen.
"""

SQL_PROMPT = "\n".join([
    "You write one DuckDB SQL query that answers a question about FDA drug recalls and "
    "shortages.",
    "",
    SCHEMA,
    "Rules:",
    "1. One SELECT query (WITH is fine). Never change data.",
    "2. Use only the tables and columns above.",
    "3. When a question asks how often something happened, count recall events with "
    "COUNT(DISTINCT event_id). When it asks about recall numbers or products, use COUNT(*).",
    "4. Match drug, firm and product names with ILIKE '%name%', since names vary.",
    "5. Keep results small: aggregate, sort, and add LIMIT 20 unless the question asks for more.",
    "6. If the tables can't answer the question, leave sql empty and say why.",
])

ANSWER_PROMPT = ("Answer the question in one or two plain sentences, using only the query "
                 "results given. Include the key numbers. If the results are empty, say nothing "
                 "matched. Don't add anything the results don't show.")

SQL_TOOL = {
    "name": "answer_with_sql",
    "description": "Give one DuckDB query that answers the question, or say why the tables can't.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One SELECT query. Empty if the tables can't answer."},
            "explanation": {"type": "string",
                            "description": "One sentence on what the query counts, or why it can't be answered."},
        },
        "required": ["sql", "explanation"],
    },
}

FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|create|drop|alter|attach|detach|copy|"
                       r"export|import|install|load|pragma|set|reset|call|checkpoint|vacuum|use|"
                       r"grant|revoke|truncate|summarize|describe)\b", re.I)
FILE_FUNCTIONS = re.compile(r"\b(read_\w+|glob|sniff_csv|parquet_\w+|getenv|query_table)\s*\(", re.I)


# ---------------------------------------------------------------- the database

def build_sandbox(paths):
    """An in-memory database with the four tables, locked so queries can only read them.
    paths maps recalls, root_causes, risk, shortages, links, weekly, makers and history to
    file paths."""
    files = {name: Path(path).as_posix() for name, path in paths.items()}
    con = duckdb.connect()
    for table, sql in SANDBOX_SQL.items():
        con.execute(f"CREATE TABLE {table} AS {sql.format(**files)}")
    con.execute("SET enable_external_access = false")   # no files, no internet, no extensions
    con.execute("SET lock_configuration = true")        # and no way to switch it back on
    return con


def check_sql(sql):
    """The query, if it's one read-only SELECT. Raises ValueError with the reason if not."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise ValueError("there's no query")
    bare = re.sub(r"'(?:[^']|'')*'", "''", text)          # ignore what's inside quoted text
    bare = re.sub(r"--[^\n]*|/\*.*?\*/", " ", bare, flags=re.S)
    if ";" in bare:
        raise ValueError("it has more than one statement")
    if not re.match(r"(?is)^\s*(with|select)\b", bare):
        raise ValueError("it isn't a SELECT query")
    word = FORBIDDEN.search(bare)
    if word:
        raise ValueError(f"it uses {word.group(1).upper()}, which could change things")
    function = FILE_FUNCTIONS.search(bare)
    if function:
        raise ValueError(f"it calls {function.group(1)}, which reads outside the tables")
    return text


def run_query(con, sql, limit=ROW_LIMIT):
    """(columns, rows) for a checked query, at most limit rows."""
    text = check_sql(sql)
    result = con.cursor().execute(f"SELECT * FROM ({text}) AS answer LIMIT {int(limit)}")
    return [d[0] for d in result.description], result.fetchall()


# ---------------------------------------------------------------- Claude

def _usage(message):
    return message.usage.input_tokens, message.usage.output_tokens


def cost(tokens):
    """Dollars for (input tokens, output tokens) pairs."""
    return sum(i * PRICE_IN + o * PRICE_OUT for i, o in tokens)


def write_sql(client, question):
    """{"sql", "explanation", "tokens"} from Claude, or None if the call fails."""
    try:
        message = client.messages.create(
            model=MODEL, max_tokens=700, system=SQL_PROMPT, tools=[SQL_TOOL],
            tool_choice={"type": "tool", "name": SQL_TOOL["name"]},
            messages=[{"role": "user", "content": question}])
    except Exception as exc:
        print(f"    Claude call failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    for block in message.content:
        if getattr(block, "type", "") == "tool_use":
            return {"sql": str(block.input.get("sql") or "").strip(),
                    "explanation": str(block.input.get("explanation") or "").strip(),
                    "tokens": _usage(message)}
    return None


def write_answer(client, question, explanation, columns, rows):
    """A sentence or two answering the question from the result rows, or None on failure."""
    table = io.StringIO()
    writer = csv.writer(table)
    writer.writerow(columns)
    writer.writerows(rows[:30])
    shown = f"{len(rows)} rows" + (", the first 30 shown" if len(rows) > 30 else "")
    try:
        message = client.messages.create(
            model=MODEL, max_tokens=250, system=ANSWER_PROMPT,
            messages=[{"role": "user", "content": f"Question: {question}\n"
                       f"What the query counts: {explanation}\nResults ({shown}):\n{table.getvalue()}"}])
    except Exception as exc:
        print(f"    Claude call failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    text = "".join(getattr(b, "text", "") for b in message.content).strip()
    return {"text": text, "tokens": _usage(message)}


# ---------------------------------------------------------------- the eval

# (question, reference SQL, kind). A "value" question has one answer, and the reference
# returns every acceptable one, so ties count. A "set" question's answer is a list.
EVAL_QUESTIONS = [
    ("How many recall numbers did FDA report in 2025?",
     "SELECT COUNT(*) FROM recalls WHERE year(report_date) = 2025", "value"),
    ("How many recall events that started in 2020 or later had a sterility root cause?",
     "SELECT COUNT(DISTINCT event_id) FROM recalls WHERE root_cause = 'Sterility' "
     "AND initiation_date >= DATE '2020-01-01'", "value"),
    ("Which root cause has the most recall events overall?",
     "WITH c AS (SELECT root_cause, COUNT(DISTINCT event_id) AS n FROM recalls GROUP BY root_cause) "
     "SELECT root_cause FROM c WHERE n = (SELECT max(n) FROM c)", "value"),
    ("Which firm had the most recall numbers reported in 2024?",
     "WITH c AS (SELECT firm, COUNT(*) AS n FROM recalls WHERE year(report_date) = 2024 GROUP BY firm) "
     "SELECT firm FROM c WHERE n = (SELECT max(n) FROM c)", "value"),
    ("How many recall numbers are flagged high risk?",
     "SELECT COUNT(*) FROM recalls WHERE risk_flag = 'high'", "value"),
    ("How many listings are on FDA's shortage list right now with a current status?",
     "SELECT COUNT(*) FROM shortages WHERE list_type = 'shortage' AND status = 'Current'", "value"),
    ("What are the 3 drugs with the most recall numbers?",
     "SELECT drug FROM recalls WHERE drug IS NOT NULL GROUP BY drug ORDER BY COUNT(*) DESC LIMIT 3", "set"),
    ("How many recall numbers are linked to at least one shortage listing?",
     "SELECT COUNT(DISTINCT recall_number) FROM links", "value"),
    ("How many Class I recall numbers were reported in 2023?",
     "SELECT COUNT(*) FROM recalls WHERE recall_class = 'Class I' AND year(report_date) = 2023", "value"),
    ("Which week in the last two years had the most recall events?",
     "WITH w AS (SELECT week, events FROM weekly_recalls "
     "WHERE week >= (SELECT max(week) FROM weekly_recalls) - INTERVAL 104 WEEK) "
     "SELECT week FROM w WHERE events = (SELECT max(events) FROM w)", "value"),
    ("How many recall numbers have heparin as the drug?",
     "SELECT COUNT(*) FROM recalls WHERE drug ILIKE '%heparin%'", "value"),
    ("What percent of recall events since 2020 were Class I?",
     "SELECT 100.0 * COUNT(DISTINCT event_id) FILTER (WHERE recall_class = 'Class I') "
     "/ COUNT(DISTINCT event_id) FROM recalls WHERE initiation_date >= DATE '2020-01-01'", "value"),
    ("Which therapeutic category has the most current shortage listings?",
     "WITH c AS (SELECT trim(category) AS category, COUNT(*) AS n FROM shortages, "
     "unnest(string_split(therapeutic_category, ', ')) AS t(category) "
     "WHERE list_type = 'shortage' AND status = 'Current' GROUP BY 1) "
     "SELECT category FROM c WHERE n = (SELECT max(n) FROM c)", "value"),
    ("How many companies list heparin sodium in the NDC directory?",
     "SELECT companies FROM drug_makers WHERE drug = 'heparin sodium'", "value"),
    ("How many shortage listings have dropped off FDA's list since the daily snapshots started?",
     "SELECT COUNT(*) FROM shortage_history WHERE NOT still_listed", "value"),
    ("What was the weather in Boston yesterday?", None, None),   # the tables can't answer this
]


def _norm(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, Decimal)):
        return f"{float(value):.1f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value).strip().lower()


def results_match(reference_rows, candidate_rows, kind="set"):
    """Whether Claude's result answers the question.

    "value": Claude's top row holds one of the acceptable answers (the reference lists every
    tie). A ranked list with the right answer first counts, since that's how people read it.
    "set": every value in the reference shows up somewhere in Claude's result, and the result
    isn't so big that it would match by luck."""
    if kind == "value":
        acceptable = {_norm(row[0]) for row in reference_rows}
        return bool(candidate_rows) and bool(acceptable & {_norm(v) for v in candidate_rows[0]})
    reference = {_norm(v) for row in reference_rows for v in row}
    candidate = {_norm(v) for row in candidate_rows for v in row}
    return (bool(reference) and reference <= candidate
            and len(candidate_rows) <= max(10, 3 * len(reference_rows)))


def report_eval():
    from shortagesignal.config import (CURRENT_SHORTAGES_PATH, HISTORY_PATH, LINKS_PATH,
                                       MAKERS_PATH, RECALLS_PATH, RISK_PATH, ROOT,
                                       ROOT_CAUSES_PATH, WEEKLY_PATH)
    from shortagesignal.tagging import make_client

    paths = {"recalls": RECALLS_PATH, "root_causes": ROOT_CAUSES_PATH, "risk": RISK_PATH,
             "shortages": CURRENT_SHORTAGES_PATH, "links": LINKS_PATH, "weekly": WEEKLY_PATH,
             "makers": MAKERS_PATH, "history": HISTORY_PATH}
    for path in paths.values():
        if not path.exists():
            sys.exit(f"{path} is missing. Copy the data branch in first: "
                     "git fetch origin data, then git archive origin/data | tar -x -C data")
    client = make_client()
    if not client:
        sys.exit("ANTHROPIC_API_KEY isn't set. Add it as a Codespaces secret, then reopen the codespace.")
    con = build_sandbox(paths)

    rows, tokens = [], []
    print(f"Asking Claude {len(EVAL_QUESTIONS)} questions...")
    for question, reference, kind in EVAL_QUESTIONS:
        answer = write_sql(client, question)
        if answer:
            tokens.append(answer["tokens"])
        sql = (answer or {}).get("sql", "")
        if reference is None:                               # should decline
            right, note = (not sql), "declined" if not sql else "should have declined"
        elif not sql:
            right, note = False, "declined"
        else:
            try:
                _, got = run_query(con, sql)
                _, expected = run_query(con, reference)
                right = results_match(expected, got, kind)
                note = "" if right else f"expected {[list(r) for r in expected][:3]}"
            except Exception as exc:
                right, note = False, f"error: {str(exc)[:80]}"
        rows.append((question, right, sql, note))

    score = sum(1 for _, right, _, _ in rows if right)
    lines = ["# Ask the data: eval", "",
             f"Claude's SQL answered {score} of {len(rows)} test questions right "
             f"({round(100 * score / len(rows))}%). Each reference answer is worked out from "
             "today's data, so the test never goes stale. For a question with one answer, "
             "Claude's top row has to hold it, and ties count. For a list, every value has to "
             "show up. One question can't be answered from the tables, and the right answer "
             "there is to decline.", "",
             "| | Question | Note |", "|---|---|---|",
             *[f"| {'✅' if right else '❌'} | {q} | {note} |" for q, right, _, note in rows],
             "", f"Model: {MODEL}. These questions cost about ${cost(tokens):.4f}."]
    out = ROOT / "audit" / "ask_eval.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    for question, right, sql, _ in rows:
        if not right and sql:
            print(f"\nWrong: {question}\n  {sql}")
    print(f"\nSaved {out}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["eval"]:
        report_eval()
    else:
        sys.exit("usage: python -m shortagesignal.ask eval")


if __name__ == "__main__":
    main()
