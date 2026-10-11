"""
Day 1: answer the two questions that shape the rest of the build.

  Q1. How far back do the shortage dates go?   (decides how much history we can analyze)
  Q2. How many recalls carry an NDC code?       (decides how hard matching will be)

Plus a preview of how recall reasons are written, which shapes the AI step later.

Run:  python -m shortagesignal.day1_explore
Then paste everything it prints back into the chat.
"""
import duckdb

from shortagesignal.config import DB_PATH
from shortagesignal.ndc import NDC_PATTERN

DATE_FORMATS = ["%m/%d/%Y", "%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]


def parse_date(expr):
    """SQL that turns a text date into a real date, trying the formats openFDA uses."""
    text = f"CAST({expr} AS VARCHAR)"
    return "coalesce(" + ", ".join(f"try_strptime({text}, '{fmt}')" for fmt in DATE_FORMATS) + ")"


def show(con, query):
    """Run a query and print the result as a simple table."""
    rel = con.sql(query)
    print(" | ".join(rel.columns))
    for row in rel.fetchall():
        print(" | ".join("" if v is None else str(v) for v in row))


def section(title):
    print("\n" + "=" * 72 + "\n" + title + "\n" + "=" * 72)


def columns(con, table):
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
    ).fetchall()
    return [r[0] for r in rows]


def table_sizes(con):
    section("Table sizes")
    for t in ["raw_recalls", "raw_shortages"]:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n:,} rows")
    section("Shortage columns (the real field names, so we stop guessing)")
    show(con, "DESCRIBE raw_shortages")


def q1_shortage_dates(con):
    section("Q1. How far back do the shortage dates go?")
    shortage_cols = columns(con, "raw_shortages")
    date_cols = [c for c in shortage_cols if "date" in c.lower()]
    if not date_cols:
        print("No column with 'date' in its name. Check the column list above.")
    for col in date_cols:
        d = parse_date(f'"{col}"')
        print(f"\n-- {col}")
        show(con, f"""
            SELECT count("{col}") AS filled,
                   count({d}) AS parsed_ok,
                   CAST(min({d}) AS DATE) AS earliest,
                   CAST(max({d}) AS DATE) AS latest
            FROM raw_shortages
        """)
        print("by year:")
        show(con, f"""
            SELECT year({d}) AS year, count(*) AS shortages
            FROM raw_shortages
            WHERE {d} IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """)
    status_col = next((c for c in shortage_cols if c.lower() == "status"), None)
    if status_col:
        print("\n-- shortages by status")
        show(con, f"""
            SELECT "{status_col}" AS status, count(*) AS n
            FROM raw_shortages GROUP BY 1 ORDER BY 2 DESC
        """)


def q2_recall_ndcs(con):
    section("Q2. How many recalls carry an NDC code?")
    has_openfda = "openfda" in columns(con, "raw_recalls")
    fda_ndc = (
        "coalesce(json_array_length(json_extract(to_json(openfda), '$.product_ndc')), 0) > 0"
        if has_openfda else "false"
    )
    flags = """
        WITH r AS (
            SELECT
                left(CAST(report_date AS VARCHAR), 4) AS year,
                __FDA_NDC__ AS fda_ndc,
                coalesce(regexp_matches(product_description, '__NDC__'), false) AS text_ndc,
                coalesce(product_description ILIKE '%ndc%', false) AS mentions_ndc
            FROM raw_recalls
        )
    """.replace("__FDA_NDC__", fda_ndc).replace("__NDC__", NDC_PATTERN)

    print("fda_tagged = FDA attached the NDC itself | in_text = an NDC appears in the product text")
    print("odd_format = text says 'NDC' but no standard-format code was found\n")
    show(con, flags + """
        SELECT count(*) AS recalls,
               round(100 * avg(fda_ndc::INT), 1) AS pct_fda_tagged,
               round(100 * avg(text_ndc::INT), 1) AS pct_in_text,
               round(100 * avg((fda_ndc OR text_ndc)::INT), 1) AS pct_either,
               round(100 * avg((mentions_ndc AND NOT text_ndc)::INT), 1) AS pct_odd_format
        FROM r
    """)
    print("\nby report year:")
    show(con, flags + """
        SELECT year, count(*) AS recalls,
               round(100 * avg((fda_ndc OR text_ndc)::INT), 1) AS pct_either
        FROM r GROUP BY year ORDER BY year
    """)


def recall_context(con):
    section("Recall history range and classes")
    show(con, f"""
        SELECT CAST(min({parse_date('report_date')}) AS DATE) AS first_report,
               CAST(max({parse_date('report_date')}) AS DATE) AS latest_report,
               CAST(min({parse_date('recall_initiation_date')}) AS DATE) AS earliest_initiated
        FROM raw_recalls
    """)
    show(con, "SELECT classification, count(*) AS n FROM raw_recalls GROUP BY 1 ORDER BY 1")

    section("Preview for the AI step: do recall reasons start with a standard label?")
    show(con, """
        SELECT round(100 * avg((strpos(reason_for_recall, ':') BETWEEN 2 AND 60)::INT), 1)
               AS pct_with_label_before_colon
        FROM raw_recalls
    """)
    print("\ntop 20 labels:")
    show(con, """
        SELECT trim(split_part(reason_for_recall, ':', 1)) AS label, count(*) AS n
        FROM raw_recalls
        WHERE strpos(reason_for_recall, ':') BETWEEN 2 AND 60
        GROUP BY 1 ORDER BY n DESC
        LIMIT 20
    """)


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    table_sizes(con)
    q1_shortage_dates(con)
    q2_recall_ndcs(con)
    recall_context(con)
    con.close()
    print("\nDone. Paste everything above into the chat.")


if __name__ == "__main__":
    main()
