"""
ShortageSignal dashboard, deployed on Streamlit Community Cloud.

It reads the pipeline's latest files straight from the repo's data branch, at most once an
hour, so it shows each daily run's data without being redeployed. The analysis tab runs the
same SQL files that are in sql/.

Run it locally:
  pip install -r app/requirements.txt
  streamlit run app/streamlit_app.py
Add SHORTAGESIGNAL_DATA=local in front of the second command to read the data/ folder
instead of GitHub.
"""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import requests
import streamlit as st

REPO = "Showrish/shortagesignal"
DATA_URL = f"https://raw.githubusercontent.com/{REPO}/data/"
ROOT = Path(__file__).resolve().parents[1]
VIEWS = {   # table name in the SQL -> file on the data branch
    "recalls": "recalls.parquet",
    "recall_risk": "recall_risk.parquet",
    "root_causes": "recall_root_causes.parquet",
    "links": "recall_shortage_links.parquet",
    "weekly_recalls": "weekly_recalls.parquet",
    "shortages_current": "shortages_current.parquet",
}
RED, GRAY = "#d62728", "#888888"

st.set_page_config(page_title="ShortageSignal", page_icon="💊", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Loading the latest pipeline data...")
def fetch(name):
    """A local path to one data file, downloaded from the data branch at most once an hour."""
    if os.getenv("SHORTAGESIGNAL_DATA") == "local":
        return str(ROOT / "data" / name)
    response = requests.get(DATA_URL + name, timeout=120)
    response.raise_for_status()
    path = Path(tempfile.gettempdir()) / "shortagesignal" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return str(path)


def connect():
    con = duckdb.connect()
    for view, name in VIEWS.items():
        con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{fetch(name)}')")
    return con


def sql_file(name):
    path = ROOT / "sql" / name
    return path.read_text().strip().rstrip(";") if path.exists() else None


try:
    con = connect()
    run_log = pd.read_csv(fetch("run_log.csv"))
except Exception as exc:   # show the problem on the page instead of a stack trace
    st.error(f"Couldn't load the pipeline data: {exc}")
    st.stop()

# ---------------------------------------------------------------- header

# The latest run that got as far as the numbers. A failed run's row has blanks.
last = run_log.dropna(subset=["recalls_total", "recalls_named_pct", "recalls_linked"]).iloc[-1]
st.title("ShortageSignal")
st.write("Every day, a pipeline pulls FDA drug recalls and the drug shortage list, works out "
         "which drug each recall is about, tags why it happened, links recalls to shortages, "
         "and flags the recalls worth watching.")
st.caption(f"Data from the pipeline run at {last['run_at_utc']} UTC. "
           f"[Code and docs on GitHub](https://github.com/{REPO})")

current = con.execute("""
    SELECT COUNT(DISTINCT shortage_key) FROM shortages_current
    WHERE list_type = 'shortage' AND lower(status) = 'current'
""").fetchone()[0]
a, b, c, d = st.columns(4)
a.metric("Recalls since 2012", f"{int(last['recalls_total']):,}")
b.metric("Drug named", f"{float(last['recalls_named_pct']):.0f}%")
c.metric("Recalls linked to a shortage", f"{int(last['recalls_linked']):,}")
d.metric("Shortages FDA lists today", f"{current:,}")

flags, weekly, follows, about = st.tabs(
    ["Risk flags", "Weekly recalls", "What follows a recall", "About"])

# ---------------------------------------------------------------- risk flags

with flags:
    left, right = st.columns([1, 2])
    days = left.selectbox("Recalls reported in the last", [30, 90, 365],
                          format_func=lambda n: f"{n} days")
    levels = right.multiselect("Flags", ["high", "watch", "low"], default=["high", "watch"])
    recent = con.execute("""
        SELECT k.flag, k.points,
               strftime(TRY_STRPTIME(k.report_date, '%Y%m%d'), '%Y-%m-%d') AS reported,
               k.recall_number, r.recalling_firm AS firm, k.drug_key AS drug, k.root_cause,
               k.reasons, k.recall_class AS class, r.product_description AS product
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        WHERE TRY_STRPTIME(k.report_date, '%Y%m%d') >= ?
        ORDER BY k.points DESC, reported DESC
    """, [date.today() - timedelta(days=days)]).df()
    counts = recent["flag"].value_counts()
    x, y, z = st.columns(3)
    x.metric("High", int(counts.get("high", 0)))
    y.metric("Watch", int(counts.get("watch", 0)))
    z.metric("Low", int(counts.get("low", 0)))
    st.dataframe(recent[recent["flag"].isin(levels)], hide_index=True)
    st.caption("Points: 2 for a Sterility root cause, 2 when only 1 or 2 companies list the drug "
               "in the NDC directory (1 for 3 to 5), and 1 for an injectable. 4 or more is high, "
               "2 or 3 is watch. On recall events since 2020, high flags were followed by a "
               "shortage about 4 times as often as average, and watch about 2 times.")

# ---------------------------------------------------------------- control chart

with weekly:
    chart = con.execute("""
        SELECT * FROM weekly_recalls
        WHERE week >= (SELECT max(week) FROM weekly_recalls) - INTERVAL 104 WEEK
    """).df()
    base = alt.Chart(chart).encode(x=alt.X("week:T", title=None))
    events = base.mark_line(point=True).encode(
        y=alt.Y("events:Q", title="Recall events per week"),
        tooltip=[alt.Tooltip("week:T", title="Week of"), "events:Q", "recalls:Q"])
    center = base.mark_line(strokeDash=[4, 4], color=GRAY).encode(y="center:Q")
    upper = base.mark_line(strokeDash=[2, 2], color=RED).encode(y="ucl:Q")
    lower = base.mark_line(strokeDash=[2, 2], color=RED).encode(y="lcl:Q")
    unusual = base.transform_filter(alt.datum.signal != "").mark_point(
        color=RED, size=90, filled=True).encode(y="events:Q")
    st.altair_chart(events + center + upper + lower + unusual)
    st.caption("A control chart (XmR) on recall events per week, by FDA report week. The dashed "
               "lines are the average and the normal range, set from the two years before the "
               "last 13 weeks. Red dots are weeks outside that range.")

# ---------------------------------------------------------------- the analysis

with follows:
    lag_sql = sql_file("lag_by_root_cause.sql")
    if lag_sql is None:
        st.info("sql/lag_by_root_cause.sql isn't in the repo yet.")
    else:
        lag = con.execute(lag_sql).df()
        total, hit = int(lag["events"].sum()), int(lag["followed"].sum())
        st.subheader(f"About {100 * hit / total:.0f}% of recall events since 2020 were followed "
                     "within a year by a shortage FDA still lists")
        st.write(f"{hit} of {total:,} events. Sterility recalls stand out, at about three times the "
                 "average, usually 4 to 5 months later. Counts are by recall event, since one "
                 "event can cover hundreds of products.")
        st.altair_chart(alt.Chart(lag).mark_bar().encode(
            x=alt.X("pct_followed:Q", title="% of events followed by a shortage within a year"),
            y=alt.Y("root_cause:N", sort="-x", title=None),
            color=alt.condition(alt.datum.root_cause == "Sterility", alt.value(RED), alt.value(GRAY)),
            tooltip=["root_cause:N", "events:Q", "followed:Q", "pct_followed:Q", "median_days:Q"]))
        st.dataframe(lag, hide_index=True)
    backtest = ROOT / "audit" / "risk_backtest.md"
    if backtest.exists():
        with st.expander("How the risk flag did on past recall events"):
            st.markdown(backtest.read_text())
    st.caption("Limits: FDA's shortage feed mostly lists shortages that are still going on, so "
               "shortages that ended long ago are missing. Some links are drug-level only, so a "
               "few could be coincidence. The pipeline has kept a daily copy of the shortage list "
               "since October 11, 2026, so new shortages are all kept from here on.")

# ---------------------------------------------------------------- about

with about:
    st.markdown(f"""
**What runs every day, on GitHub Actions**
1. Pulls FDA's drug recall reports, the drug shortage list and the NDC directory from openFDA.
2. Works out which drug each recall is about: NDC codes, then the product text, then Claude
   Haiku for the rest, keeping only names that exist in the NDC directory, the shortage list
   or past recalls.
3. Tags why each recall happened: SQL rules first, then Claude Haiku, scored against a hand
   audit of 99 recalls.
4. Links recalls to shortages of the same drug, by package, product, drug and firm, or drug.
5. Flags each recall's shortage risk and charts weekly recall events.
6. Runs 16 data quality checks, and saves nothing if one fails.

**Data:** [openFDA](https://open.fda.gov/) drug enforcement reports, drug shortages and the
NDC directory. Everything is public, and nothing here is medical advice.

[Code, decision log and docs on GitHub](https://github.com/{REPO})
""")
