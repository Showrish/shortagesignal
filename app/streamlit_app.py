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
MATCH_LABELS = {"package": "Same package", "product": "Same product",
                "drug_and_firm": "Same drug and company", "drug": "Same drug name only"}
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


def backtest_file(name):
    """The daily run's copy of a backtest file from the data branch, or the snapshot in audit/
    if the data branch doesn't have one yet. None if neither does."""
    try:
        return Path(fetch(name)).read_text(encoding="utf-8")
    except (requests.RequestException, OSError):
        pass
    try:
        return (ROOT / "audit" / name).read_text(encoding="utf-8")
    except OSError:
        return None


def backtest_numbers():
    """The latest risk backtest's numbers, worked out by every daily run."""
    try:
        return json.loads(backtest_file("risk_backtest.json") or "")
    except ValueError:
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

flags, weekly, follows, asking, health, about = st.tabs(
    ["Risk flags", "Weekly recalls", "What follows a recall", "Ask the data", "Pipeline health",
     "About"])

# ---------------------------------------------------------------- risk flags

with flags:
    days = st.selectbox("Recalls reported in the last", [30, 60, 90, 365], index=1, format_func=lambda n: f"{n} days")
    since = date.today() - timedelta(days=days)
    st.markdown("Two different questions. **Current exposure:** which recalls hit a drug that's "
                "already short, and how sure is the match? **Future monitoring:** which recalls are "
                "worth watching for a shortage that hasn't happened yet?")
    # current exposure: a link to a listing FDA has on its shortage list now, the same test the
    # high flag uses, with the strongest link first (1 is the same package, 4 the same drug name)
    exposed = con.execute("""
        WITH now_short AS (
            SELECT recall_number, min(match_rank) AS best,
                   arg_min(match_level, match_rank) AS level,
                   arg_min(shortage_generic_name, match_rank) AS listing,
                   count(DISTINCT shortage_key) AS listings
            FROM links
            WHERE shortage_list_type = 'shortage' AND lower(shortage_status) = 'current'
            GROUP BY recall_number
        )
        SELECT TRY_STRPTIME(k.report_date, '%Y%m%d')::DATE AS reported, k.drug_key AS drug,
               r.recalling_firm AS firm, n.level, n.listing, n.listings, k.root_cause,
               r.product_description AS product, k.recall_class AS class, k.recall_number
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        INNER JOIN now_short AS n ON n.recall_number = k.recall_number
        WHERE TRY_STRPTIME(k.report_date, '%Y%m%d') >= ?
        ORDER BY n.best, reported DESC
    """, [since]).df()
    recent = con.execute("""
        SELECT k.flag, TRY_STRPTIME(k.report_date, '%Y%m%d')::DATE AS reported, k.recall_number,
               r.recalling_firm AS firm, k.drug_key AS drug, k.root_cause, k.recall_class AS class,
               r.product_description AS product
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        WHERE TRY_STRPTIME(k.report_date, '%Y%m%d') >= ? AND k.flag IN ('watch', 'low')
        ORDER BY reported DESC
    """, [since]).df()
    watch_count = int((recent["flag"] == "watch").sum())
    exposure, monitoring = st.tabs([f"🔴 Current exposure ({len(exposed)})",
                                    f"🟠 Future monitoring ({watch_count})"])

    with exposure:
        st.markdown("Recalls of a drug that's **on FDA's shortage list right now**, so the recall can "
                    "make that shortage worse. That's a fact, not a prediction. The strongest match "
                    "comes first.")
        if exposed.empty:
            st.caption(f"No recall in the last {days} days hit a drug that's already short.")
        else:
            by_level = exposed["level"].value_counts()
            a, b, c = st.columns(3)
            a.metric("Same product or package", int(by_level.get("package", 0) + by_level.get("product", 0)),
                     help="The recall's NDC codes match the shortage listing's.")
            b.metric("Same drug and company", int(by_level.get("drug_and_firm", 0)))
            c.metric("Same drug name only", int(by_level.get("drug", 0)),
                     help="The weakest match: it can join different products, like an injection "
                          "and a patch of the same drug.")
            shown = exposed.copy()
            shown["level"] = shown["level"].map(MATCH_LABELS)
            shown["drug"] = shown["drug"].fillna("(not named)").str.capitalize()
            st.dataframe(shown, hide_index=True, column_config={
                "reported": st.column_config.DateColumn("Reported", format="MMM D, YYYY"),
                "drug": st.column_config.TextColumn("Drug"),
                "firm": st.column_config.TextColumn("Firm"),
                "level": st.column_config.TextColumn("Match", help="How the recall links to the "
                                                     "shortage listing, strongest first."),
                "listing": st.column_config.TextColumn("Shortage listing", width="medium"),
                "listings": st.column_config.NumberColumn("Listings", help="How many current "
                                                          "shortage listings it links to."),
                "root_cause": st.column_config.TextColumn("Root cause"),
                "product": st.column_config.TextColumn("Product", width="large"),
                "class": st.column_config.TextColumn("Class", help="FDA's recall class. Class I is "
                                                     "the most serious."),
                "recall_number": st.column_config.TextColumn("Recall"),
            })
            st.caption("A same-drug-name match is a lead to check, not a confirmed overlap.")
            st.download_button("Download this list (CSV)", shown.to_csv(index=False).encode("utf-8"),
                               file_name=f"shortagesignal_exposure_{date.today()}.csv", mime="text/csv")

    with monitoring:
        bt = backtest_numbers() or {}
        rates, lead = bt.get("rate_by_flag", {}), bt.get("lead_days") or {}
        sentence = "🟠 **Watch:** an injectable whose drug isn't short now."
        if rates.get("watch") and rates.get("low"):
            sentence += (f" {100 * rates['watch']:.1f} in 100 see their drug go short within a year, "
                         f"against {100 * rates['low']:.1f} in 100 for other recalls")
            sentence += (f", and when it happens, the shortage comes a median of {lead['median']} days "
                         "after the recall's report." if lead.get("median") else ".")
        st.markdown(sentence)
        if rates.get("watch"):
            st.caption("From drugs recalled since 2020 that have had a full year since their report, "
                       "counting a shortage of the same drug given the same way. They describe this "
                       "dataset: FDA drops resolved shortages after a while, so older years are "
                       "undercounted. Most watch flags never lead to a shortage, so this is a watch "
                       "list, not a prediction.")
        also_low = st.checkbox("Also show low flags: recalls that are neither short nor injectable")
        view = recent[recent["flag"].isin(["watch", "low"] if also_low else ["watch"])].copy()
        view["flag"] = view["flag"].map(FLAG_LABELS)
        view["drug"] = view["drug"].fillna("(not named)").str.capitalize()
        view = view[["flag", "reported", "drug", "firm", "root_cause", "product", "class", "recall_number"]]
        st.dataframe(view, hide_index=True, column_config={
            "flag": st.column_config.TextColumn("Flag"),
            "reported": st.column_config.DateColumn("Reported", format="MMM D, YYYY"),
            "drug": st.column_config.TextColumn("Drug"),
            "firm": st.column_config.TextColumn("Firm"),
            "root_cause": st.column_config.TextColumn("Root cause"),
            "product": st.column_config.TextColumn("Product", width="large"),
            "class": st.column_config.TextColumn("Class", help="FDA's recall class. Class I is the "
                                                 "most serious."),
            "recall_number": st.column_config.TextColumn("Recall"),
        })
        st.download_button("Download this list (CSV)", view.to_csv(index=False).encode("utf-8"),
                           file_name=f"shortagesignal_watch_{date.today()}.csv", mime="text/csv")
        with st.expander("Why only injectables"):
            st.markdown("Injectables were the one sign that held up when each drug in each recall "
                        "event was counted on its own, with each year starting on the recall's report "
                        "date. Sterility problems and drugs with few makers used to count too. Neither "
                        "held up, so they're shown as facts but don't change the flag. The flag is "
                        "also being tested on new recalls as they come in, which the Monday digest "
                        "reports.")

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
    backtest = backtest_file("risk_backtest.md")
    if backtest:
        with st.expander("How the risk flag did on past recalls"):
            st.markdown(backtest)
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
                        # how Claude read the question matters most when it could mean two things
                        st.caption(f"How Claude read the question: {plan['explanation']}")
                        st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True)
                        spent = ask.cost([plan["tokens"]] + ([reply["tokens"]] if reply else []))
                        with st.expander("The SQL behind this answer"):
                            st.code(plan["sql"], language="sql")
                        st.caption(f"Data as of {nice_date(updated)}, "
                                   f"{updated.hour % 12 or 12}:{updated:%M %p %Z}, and FDA's newest "
                                   f"recall report is from {nice_date(newest)}. This answer cost "
                                   f"about ${spent:.4f}.")
        st.caption(f"{max(left, 0)} of {DAILY_QUESTIONS} questions left today. Queries can only "
                   "read the tables, and return at most 200 rows.")

# ---------------------------------------------------------------- about

with health:
    st.markdown("Every daily run is logged with its numbers and its data checks. A run that fails "
                "an error check saves nothing, so the dashboard keeps the day before's data.")
    runs = run_log.copy()
    runs["when"] = (pd.to_datetime(runs["run_at_utc"]).dt.tz_localize("UTC")
                    .dt.tz_convert(BOSTON))
    last_30 = runs.tail(30)
    worked = int((last_30["status"] == "success").sum())
    warned = int((pd.to_numeric(last_30["checks_warned"], errors="coerce").fillna(0) > 0).sum())
    try:
        ndc = json.loads(Path(fetch("state.json")).read_text(encoding="utf-8")).get("ndc_refreshed")
    except (requests.RequestException, OSError, ValueError):
        ndc = None
    a, b, c, d = st.columns(4)
    a.metric("Runs that worked, last 30", f"{worked} of {len(last_30)}")
    b.metric("Runs with a warning, last 30", warned)
    c.metric("FDA's newest recall report", nice_date(newest))
    try:
        ndc = nice_date(date.fromisoformat(str(ndc)[:10]))
    except ValueError:
        ndc = "unknown"
    d.metric("NDC directory refreshed", ndc)

    st.markdown("**The last 14 runs**")
    names = {"when": "Run, Boston time", "status": "Status", "seconds": "Seconds",
             "recalls_new": "New recalls", "recalls_changed": "Changed recalls",
             "shortages_new": "New listings", "shortages_dropped": "Listings dropped",
             "checks_warned": "Checks warned", "checks_failed": "Checks failed",
             "code_version": "Code version", "error": "Error"}
    shown = last_30.iloc[::-1].head(14)
    table = shown[[c for c in names if c in shown.columns]].rename(columns=names)
    table["Run, Boston time"] = shown["when"].dt.strftime("%b %-d, %-I:%M %p")
    st.dataframe(table, hide_index=True, use_container_width=True)

    try:
        checks = pd.read_csv(fetch("check_log.csv"))
        latest = checks[checks["run_at_utc"] == checks["run_at_utc"].max()]
        st.markdown(f"**The {len(latest)} data checks on the latest run**")
        st.dataframe(latest[["check", "severity", "status", "value", "detail"]]
                     .rename(columns=str.capitalize), hide_index=True, use_container_width=True)
    except (requests.RequestException, OSError, KeyError, ValueError):
        st.caption("The check log isn't available right now.")

    try:
        made_by = con.execute(f"""
            SELECT 'Root causes' AS task, model, prompt_version, COUNT(*) AS answers,
                   max(CAST(tagged_at AS VARCHAR)) AS latest
            FROM read_parquet('{fetch("claude_tags.parquet")}') GROUP BY ALL
            UNION ALL
            SELECT 'Drug names', model, prompt_version, COUNT(*), max(CAST(extracted_at AS VARCHAR))
            FROM read_parquet('{fetch("claude_drugs.parquet")}') GROUP BY ALL
            ORDER BY task, latest DESC
        """).df()
        st.markdown("**The Claude model and prompt behind the cached answers**")
        st.dataframe(made_by.rename(columns={"task": "Task", "model": "Model",
                                             "prompt_version": "Prompt version",
                                             "answers": "Answers", "latest": "Latest answer"}),
                     hide_index=True, use_container_width=True)
    except (requests.RequestException, OSError, duckdb.Error):
        st.caption("The Claude caches aren't available right now.")
    st.caption("Code version is the commit each run used, so any result can be traced to the code "
               f"that made it. Runs before mid-November 2026 don't have one. A failed run that "
               f"didn't get logged here is on the [Actions page]({REPO_URL}/actions).")

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
5. Splits recent recalls into current exposure, a drug that's already short, and future
   monitoring, an injectable worth watching, and charts weekly recall events.
6. Runs 16 data quality checks, and saves nothing if one fails.

Every Monday, a digest of the week goes out by email, with an Excel list of items that need a
look. The **Ask the data** tab answers questions in plain English with SQL that Claude writes,
over a locked, read-only copy of the tables. The **Pipeline health** tab shows each recent run,
its data checks, and the code and Claude versions behind the numbers.

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
