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

The "Ask the data" tab needs two secrets, set under the app's Settings, then Secrets on
Streamlit Community Cloud: ANTHROPIC_API_KEY (its own key, in a Console workspace with a
monthly spend limit) and ASK_PASSCODE. Locally it falls back to environment variables.
"""
import hmac
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import duckdb
import pandas as pd
import requests
import streamlit as st

# The chatbot's logic lives in the pipeline's package, which only needs duckdb and anthropic.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shortagesignal import ask  # noqa: E402

REPO = "Showrish/shortagesignal"
REPO_URL = f"https://github.com/{REPO}"
GITHUB_PROFILE = "https://github.com/Showrish"
LINKEDIN_URL = "https://www.linkedin.com/in/showrish-reddy-sampath-b508a22a6"
BOSTON = ZoneInfo("America/New_York")
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
# One palette for every chart
BLUE, GRAY, RED, ORANGE = "#2E6FD8", "#8C8C8C", "#D64545", "#E8913A"
FLAG_LABELS = {"high": "🔴 High", "watch": "🟠 Watch", "low": "⚪ Low"}
DAILY_QUESTIONS = 50
EXAMPLES = [
    "Which root causes had the most recall events in 2025?",
    "Which firms had the most high-risk recalls in the last year?",
    "How many recall numbers per year mention heparin as the drug?",
    "Which drugs on the current shortage list were recalled in the last 90 days?",
    "How many companies make the drugs with the most sterility recalls?",
    "Which shortage listings have dropped off FDA's list since tracking started?",
]

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


def backtest_numbers():
    """The latest risk backtest, saved by python -m shortagesignal.risk backtest."""
    try:
        return json.loads((ROOT / "audit" / "risk_backtest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def nice_date(value):
    return f"{value:%b} {value.day}, {value.year}"


def secret(name):
    """A Streamlit secret, or the environment variable of the same name when running locally."""
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name)


@st.cache_resource(ttl=3600)
def sandbox():
    """The locked, read-only copy of the tables that the chatbot's queries run against."""
    return ask.build_sandbox({
        "recalls": fetch("recalls.parquet"), "root_causes": fetch("recall_root_causes.parquet"),
        "risk": fetch("recall_risk.parquet"), "shortages": fetch("shortages_current.parquet"),
        "shortage_drugs": fetch("shortage_drugs.parquet"),
        "links": fetch("recall_shortage_links.parquet"), "weekly": fetch("weekly_recalls.parquet"),
        "makers": fetch("drug_makers.parquet"), "history": fetch("shortage_history.parquet")})


@st.cache_resource
def question_counter():
    """Questions asked today, shared by everyone using the app."""
    return {"day": None, "count": 0}


try:
    con = connect()
    run_log = pd.read_csv(fetch("run_log.csv"))
except Exception as exc:   # show the problem on the page instead of a stack trace
    st.error(f"Couldn't load the pipeline data: {exc}")
    st.stop()

# ---------------------------------------------------------------- header

# The latest run that got as far as the numbers. A failed run's row has blanks.
last = run_log.dropna(subset=["recalls_total", "recalls_named_pct", "recalls_linked"]).iloc[-1]
# The run log is in UTC. Show Boston time, which is EDT or EST depending on the season.
updated = datetime.fromisoformat(str(last["run_at_utc"])).replace(tzinfo=timezone.utc).astimezone(BOSTON)
today = datetime.now(BOSTON).date()
newest = con.execute(
    "SELECT max(TRY_STRPTIME(report_date, '%Y%m%d'))::DATE FROM recalls").fetchone()[0]

st.title("ShortageSignal")
st.markdown("Every day, a pipeline pulls FDA drug recalls and the drug shortage list, works out "
            "which drug each recall is about, tags why it happened, links recalls to shortages, "
            "and flags the recalls worth watching.")
st.caption(f"Updated {nice_date(updated)}, {updated.hour % 12 or 12}:{updated:%M %p %Z}. "
           f"FDA's newest recall report: {nice_date(newest)} ({(today - newest).days} days ago).")

current = con.execute("""
    SELECT COUNT(DISTINCT shortage_key) FROM shortages_current
    WHERE list_type = 'shortage' AND lower(status) = 'current'
""").fetchone()[0]
a, b, c, d = st.columns(4)
a.metric("Recalls since 2012", f"{int(last['recalls_total']):,}",
         help="Every drug recall in FDA's enforcement reports since June 2012.")
b.metric("Drug named", f"{float(last['recalls_named_pct']):.0f}%",
         help="Recalls where the pipeline worked out which drug it is, from NDC codes, the "
              "product text, or Claude.")
c.metric("Recalls linked to a shortage", f"{int(last['recalls_linked']):,}",
         help="Recalls of a drug that's on FDA's shortage list, by package, product, "
              "drug and company, or drug.")
d.metric("Shortages FDA lists today", f"{current:,}",
         help="Current listings on FDA's drug shortage list.")

flags, weekly, follows, asking, about = st.tabs(
    ["Risk flags", "Weekly recalls", "What follows a recall", "Ask the data", "About"])

# ---------------------------------------------------------------- risk flags

with flags:
    left, right = st.columns([1, 2])
    days = left.selectbox("Recalls reported in the last", [30, 90, 365],
                          format_func=lambda n: f"{n} days")
    levels = right.multiselect("Flags", ["high", "watch", "low"], default=["high", "watch"],
                               format_func=lambda f: FLAG_LABELS[f])
    recent = con.execute("""
        SELECT k.flag, k.points,
               TRY_STRPTIME(k.report_date, '%Y%m%d')::DATE AS reported,
               k.recall_number, r.recalling_firm AS firm, k.drug_key AS drug, k.root_cause,
               k.reasons, k.recall_class AS class, r.product_description AS product
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        WHERE TRY_STRPTIME(k.report_date, '%Y%m%d') >= ?
        ORDER BY k.points DESC, reported DESC
    """, [date.today() - timedelta(days=days)]).df()
    counts = recent["flag"].value_counts()
    x, y, z = st.columns(3)
    x.metric("🔴 High", int(counts.get("high", 0)))
    y.metric("🟠 Watch", int(counts.get("watch", 0)))
    z.metric("⚪ Low", int(counts.get("low", 0)))

    view = recent[recent["flag"].isin(levels)].copy()
    view["flag"] = view["flag"].map(FLAG_LABELS)
    view["drug"] = view["drug"].fillna("(not named)").str.capitalize()
    view["reasons"] = view["reasons"].fillna("").str.capitalize()
    st.dataframe(view, hide_index=True, column_config={
        "flag": st.column_config.TextColumn("Flag"),
        "points": st.column_config.NumberColumn("Points", help="0 to 5. 4 or more is high."),
        "reported": st.column_config.DateColumn("Reported", format="MMM D, YYYY"),
        "recall_number": st.column_config.TextColumn("Recall"),
        "firm": st.column_config.TextColumn("Firm"),
        "drug": st.column_config.TextColumn("Drug"),
        "root_cause": st.column_config.TextColumn("Root cause"),
        "reasons": st.column_config.TextColumn("Why flagged"),
        "class": st.column_config.TextColumn("Class", help="FDA's recall class. Class I is the most serious."),
        "product": st.column_config.TextColumn("Product", width="large"),
    })
    st.download_button("Download this list (CSV)", view.to_csv(index=False).encode("utf-8"),
                       file_name=f"shortagesignal_flags_{date.today()}.csv", mime="text/csv")
    lift = (backtest_numbers() or {}).get("lift", {})
    lift_sentence = ""
    if lift.get("high") and lift.get("watch"):
        lift_sentence = (f"On drugs recalled since 2020, high flags were followed by a shortage of the "
                         f"same drug **{lift['high']:.1f} times** as often as average, and watch flags "
                         f"**{lift['watch']:.1f} times**. ")
    with st.expander("How to read this"):
        st.markdown(
            "Each recall gets points for the signs that came before past shortages: **2** for a "
            "sterility problem, **2** when only 1 or 2 companies make the drug (**1** for 3 to 5), "
            "and **1** for an injectable. **4 or more is high, 2 or 3 is watch.**\n\n"
            + lift_sentence +
            "Most recalls never lead to a shortage, so this is a watch list, not a prediction.")

# ---------------------------------------------------------------- control chart

with weekly:
    chart = con.execute("""
        SELECT * FROM weekly_recalls
        WHERE week >= (SELECT max(week) FROM weekly_recalls) - INTERVAL 104 WEEK
    """).df()
    names = {"events": "Recall events", "center": "Average", "ucl": "Normal range", "lcl": "Normal range"}
    long = chart.melt(id_vars=["week"], value_vars=list(names), var_name="series", value_name="value")
    long["line"] = long["series"].map(names)
    lines = alt.Chart(long).mark_line().encode(
        x=alt.X("week:T", title=None),
        y=alt.Y("value:Q", title="Recall events per week"),
        color=alt.Color("line:N", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=["Recall events", "Average", "Normal range"],
                                        range=[BLUE, GRAY, RED])),
        strokeDash=alt.condition(alt.datum.line == "Recall events", alt.value([1, 0]), alt.value([5, 4])),
        detail="series:N",
        tooltip=[alt.Tooltip("week:T", title="Week of"), alt.Tooltip("line:N", title="Line"),
                 alt.Tooltip("value:Q", title="Value", format=".1f")])
    unusual = alt.Chart(chart[chart["signal"].fillna("") != ""]).mark_point(
        color=RED, size=110, filled=True).encode(
        x="week:T", y="events:Q",
        tooltip=[alt.Tooltip("week:T", title="Unusual week of"), alt.Tooltip("events:Q", title="Recall events")])
    st.altair_chart(lines + unusual)
    with st.expander("How to read this"):
        st.markdown(
            "This is a control chart of recall events per week, by the week FDA reported them. "
            "The red dashed lines mark the normal range, set from the two years before the last "
            "13 weeks. A **red dot** is a week outside that range, which is worth a closer look. "
            "Events are counted instead of recall numbers, since one event can cover hundreds of "
            "products.")

# ---------------------------------------------------------------- the analysis

with follows:
    lag_sql = sql_file("lag_by_root_cause.sql")
    if lag_sql is None:
        st.info("sql/lag_by_root_cause.sql isn't in the repo yet.")
    else:
        lag = con.execute(lag_sql).df()
        total, hit = int(lag["recalled_drugs"].sum()), int(lag["followed"].sum())
        overall = 100 * hit / total if total else 0
        st.subheader(f"{overall:.1f}% of drugs recalled since 2020 were followed within a year by a "
                     "shortage of the same drug that FDA still lists")
        line = f"{hit:,} of {total:,} recalled drugs, counting each drug in each recall event once."
        sterility = lag[lag["root_cause"] == "Sterility"]
        if len(sterility) and overall:
            s = sterility.iloc[0]
            line += (f" For **Sterility** recalls it's {s['pct_followed']:.1f}%, "
                     f"{s['pct_followed'] / overall:.1f} times the average")
            line += f", a median of {s['median_days']:.0f} days later." if pd.notna(s["median_days"]) else "."
        st.markdown(line)
        lag["label"] = lag["pct_followed"].map(lambda v: f"{v:.1f}%")
        base = alt.Chart(lag).encode(
            y=alt.Y("root_cause:N", sort="-x", title=None),
            x=alt.X("pct_followed:Q", title="% of recalled drugs followed by a shortage within a year"))
        bars = base.mark_bar().encode(
            color=alt.condition(alt.datum.root_cause == "Sterility", alt.value(RED), alt.value(GRAY)),
            tooltip=[alt.Tooltip("root_cause:N", title="Root cause"),
                     alt.Tooltip("recalled_drugs:Q", title="Recalled drugs"),
                     alt.Tooltip("followed:Q", title="Followed by a shortage"),
                     alt.Tooltip("median_days:Q", title="Median days", format=".0f")])
        st.altair_chart(bars + base.mark_text(align="left", dx=4).encode(text="label:N"))
        st.dataframe(lag.drop(columns=["label"]), hide_index=True, column_config={
            "root_cause": st.column_config.TextColumn("Root cause"),
            "recalled_drugs": st.column_config.NumberColumn("Recalled drugs", format="%d"),
            "followed": st.column_config.NumberColumn("Followed by a shortage", format="%d"),
            "pct_followed": st.column_config.NumberColumn("Share", format="%.1f%%"),
            "median_days": st.column_config.NumberColumn("Median days to the shortage", format="%d"),
        })
    backtest = ROOT / "audit" / "risk_backtest.md"
    if backtest.exists():
        with st.expander("How the risk flag did on past recalls"):
            st.markdown(backtest.read_text())
    with st.expander("How to read this, and its limits"):
        st.markdown(
            "Each drug in each recall event is followed for a year to see whether FDA posted a "
            "shortage of that same drug. A pharmacy recalling 298 products that cover 40 drugs "
            "counts as 40 recalled drugs, not 298 and not 1. Recalls whose drug couldn't be named "
            "are left out. **Limits:** FDA's shortage feed mostly lists shortages that are still going "
            "on, so ones that ended long ago are missing. Some links are by drug name only, so a "
            "few could be coincidence. The pipeline has kept a daily copy of the shortage list "
            "since October 11, 2026, so every new shortage is kept from here on.")

# ---------------------------------------------------------------- ask the data

with asking:
    passcode, api_key = (str(v) if v else None for v in (secret("ASK_PASSCODE"), secret("ANTHROPIC_API_KEY")))
    st.markdown("Ask a question in plain English. Claude writes one read-only SQL query over "
                "the pipeline's tables, the app runs it, and Claude answers from the results. "
                "The query is shown under every answer, so you can check it.")
    if not passcode or not api_key:
        st.info("Ask the data isn't switched on here yet.")
    elif not st.session_state.get("ask_ok"):
        entered = st.text_input("Passcode", type="password",
                                help="This tab uses paid AI calls, so it's behind a passcode.")
        if entered:
            if hmac.compare_digest(entered.encode(), passcode.encode()):
                st.session_state["ask_ok"] = True
                st.rerun()
            else:
                st.error("That passcode isn't right.")
    else:
        counter = question_counter()
        if counter["day"] != today:
            counter.update(day=today, count=0)
        st.caption("Try one: " + " · ".join(EXAMPLES))
        question = st.text_input("Your question", placeholder=EXAMPLES[0], max_chars=300)
        left = DAILY_QUESTIONS - counter["count"]
        if st.button("Ask", type="primary", disabled=not question.strip()):
            if left <= 0:
                st.warning("Today's questions are used up. Try again tomorrow.")
            else:
                import anthropic

                counter["count"] += 1
                left -= 1
                client = anthropic.Anthropic(api_key=api_key, max_retries=2)
                with st.spinner("Writing the query..."):
                    plan = ask.write_sql(client, question)
                if plan is None:
                    st.error("Couldn't reach Claude just now. Try again in a minute.")
                elif not plan["sql"]:
                    st.info(f"The tables can't answer that one. {plan['explanation']}")
                else:
                    try:
                        columns, rows = ask.run_query(sandbox(), plan["sql"])
                    except ValueError as exc:
                        st.warning(f"The query was blocked, because {exc}.")
                        rows = None
                    except Exception as exc:
                        st.warning(f"The query didn't run: {str(exc)[:200]}")
                        rows = None
                    if rows is not None:
                        with st.spinner("Reading the results..."):
                            reply = ask.write_answer(client, question, plan["explanation"], columns, rows)
                        if reply:
                            st.markdown(f"**{reply['text']}**")
                        st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True)
                        spent = ask.cost([plan["tokens"]] + ([reply["tokens"]] if reply else []))
                        with st.expander("The SQL behind this answer"):
                            st.caption(plan["explanation"])
                            st.code(plan["sql"], language="sql")
                        st.caption(f"This answer cost about ${spent:.4f}.")
        st.caption(f"{max(left, 0)} of {DAILY_QUESTIONS} questions left today. Queries can only "
                   "read the tables, and return at most 200 rows.")

# ---------------------------------------------------------------- about

with about:
    st.markdown("""
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

Every Monday, a digest of the week goes out by email, with an Excel list of items that need a
look. The **Ask the data** tab answers questions in plain English with SQL that Claude writes,
over a locked, read-only copy of the tables.

**Data:** [openFDA](https://open.fda.gov/) drug enforcement reports, drug shortages and the NDC
directory. Everything is public, and nothing here is medical advice.
""")

# ---------------------------------------------------------------- footer

st.divider()
links = [f"[GitHub]({GITHUB_PROFILE})", f"[Project code and docs]({REPO_URL})"]
if LINKEDIN_URL:
    # A link without https:// would open as a page inside the app, so add it if it's missing.
    linkedin = LINKEDIN_URL if LINKEDIN_URL.startswith("http") else "https://" + LINKEDIN_URL
    links.insert(0, f"[LinkedIn]({linkedin})")
st.caption("Built by Showrish Reddy Sampath · " + " · ".join(links))
