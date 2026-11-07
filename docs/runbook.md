# Runbook

How ShortageSignal runs day to day, and what to do when something breaks. For what each file and column holds, see [data_dictionary.md](data_dictionary.md). For why things are built the way they are, see [decision_log.md](decision_log.md).

## What runs, and when

| What | When | Where it runs | What it leaves |
|---|---|---|---|
| Daily pipeline | Every day at 12:00 UTC (8 AM Boston in summer, 7 AM in winter), and on demand | GitHub Actions, `.github/workflows/daily.yml` | The latest files on the `data` branch, in one commit, plus a 30-day backup on the run's page |
| Weekly digest | Mondays at 13:00 UTC, an hour after the daily run, and on demand | GitHub Actions, `.github/workflows/weekly.yml` | A GitHub issue labeled `digest` (or an email), plus the digest and its Excel list on the run's page for 90 days |
| CI | Every pull request and every change to `main` | GitHub Actions, `.github/workflows/ci.yml` | A pass or fail on the pull request. `main` only takes pull requests that pass |
| Dashboard | Always on | Streamlit Community Cloud | Redeploys on every change to `main`, and downloads the data branch's files at most once an hour |
| Power BI report | When you open it | Power BI Desktop on Windows | Nothing. Refresh pulls the data branch's files straight from GitHub |
| Keep-awake | Every 6 hours, at 17 past | GitHub Actions, `.github/workflows/keep-awake.yml` | Nothing. It opens the dashboard in a headless browser so Streamlit doesn't put it to sleep, and clicks the wake button if it's asleep |

Only one daily run happens at a time. A second one waits, and the weekly digest waits for a daily run that's still going.

## Keys, secrets and settings

| Name | Where it lives | What it's for | Needed? |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | GitHub, Actions secrets | Claude in the daily run: root causes and drug names | Without it, those recalls just wait |
| `OPENFDA_API_KEY` | GitHub, Actions secrets | Higher openFDA rate limits | Optional |
| `SHORTAGESIGNAL_USE_CLAUDE` | Set to `1` in `daily.yml` | Turns Claude on. Runs anywhere else leave it off, so they never spend money by accident | Only in the daily run |
| `CLAUDE_CREDITS_USD`, `CLAUDE_CREDITS_SINCE`, `CLAUDE_KEY_EXPIRES` | GitHub, Actions variables (not secrets) | The digest's Keeping it running section: credits left and the key's expiry | Optional |
| `DIGEST_SMTP_USER`, `DIGEST_SMTP_PASSWORD`, `DIGEST_TO` | GitHub, Actions secrets | Emailing the digest. Without them it's posted as an issue, which GitHub emails to you | Optional |
| `ANTHROPIC_API_KEY` (the chatbot's) | Streamlit, the app's Secrets | The Ask the data tab. A separate key in the Console's `dashboard` workspace, which has a $1 monthly spend limit | For the tab |
| `ASK_PASSCODE` | Streamlit, the app's Secrets | The passcode for the Ask the data tab. Share it only when demoing | For the tab |
| `SHORTAGESIGNAL_DATA_DIR` | Set by the workflows | Where the data files live. Defaults to `data/` | No |
| `SHORTAGESIGNAL_DATA=local` | Your terminal | Makes the dashboard read `data/` instead of the data branch | Local only |

Keys never go in git. `.env.example` lists the names, and a local `.env` (git-ignored) holds the values.

## The weekly routine

1. **Read the Monday digest.** It covers the week's recalls against the normal range, the high and watch flags, recalls of drugs already in shortage, changes to FDA's shortage list, and Keeping it running.
2. **Open its Excel list** from the run's page. It has the flagged recalls, Claude's unsure root causes (`tag_review.csv`) and the drug names Claude gave that weren't used (`extract_review.csv`).
3. **Fix patterns, not rows.** When the same kind of reason keeps landing in the unsure list, add a rule to `sql/root_cause_rules.sql`, check it with `python -m shortagesignal.tagging rules`, and ship it as a pull request. Rules are free, and they're checked against the hand audit.

## Run it again

To rerun today, open the **Actions** tab, then **Daily pipeline**, then **Run workflow**, on `main`.

That's safe at any time. Today's shortage snapshot is replaced rather than counted twice, recalls merge by recall number, and Claude only sees what isn't cached yet.

A failed run changes nothing. The run works on a staged copy of the files and only swaps them in when every step and every error-level check passes. It still adds a row to `run_log.csv`, and GitHub emails you.

## When a run fails

1. Open the failed run in **Actions**. The page shows the data checks table and the error at the end of **Run the pipeline**.
2. If a check failed, look it up in [the data checks](#the-data-checks) below.
3. Fix it in a pull request, merge it, then run the workflow again.

**If the data branch itself is broken,** restore it from a backup. Every run keeps its files for 30 days as an artifact named `data-<run id>`. Find the last good run's ID in its page's address, then run this in the codespace:

```
gh run download RUN_ID --name data-RUN_ID --dir /tmp/restore
cd /tmp/restore
git init -q -b data
git add -A
git commit -qm "data: restored from run RUN_ID"
git push --force https://github.com/Showrish/shortagesignal.git data
```

The data branch only ever holds one commit, since the tables keep their own history, so replacing it this way loses nothing the backup didn't have.

## The data checks

Every run ends with 16 checks, before anything is saved. **Errors** stop the run, so yesterday's data stays. **Warnings** only report, and the run still saves. Every check writes a row to `check_log.csv`.

| Check | Level | What it means | What to do |
|---|---|---|---|
| recall numbers are unique | error | The merge left two rows with the same recall number | Look at what FDA sent this run. Usually it's the same recall twice in a shape the merge didn't collapse. Fix `merge_recalls` in `ingest.py` |
| shortage keys are unique today | error | Two rows in today's snapshot share a key | FDA probably changed how it lists something. Check the key in `save_snapshot` |
| recall fields still arriving | error | One of the six required recall fields came back empty for every recall this run | FDA renamed or dropped a field. Check openFDA's docs and update the code |
| shortage fields still arriving | error | The same for the six required shortage fields | Same as above |
| recall table never shrinks | error | Fewer recalls than after the last good run | Something deleted rows, which should never happen. Find out why before rerunning, and restore the data branch if needed |
| shortage list didn't collapse | error | Today's list has under half the rows of the last run | Usually a bad response from openFDA. Rerun later. If it keeps happening, FDA changed the endpoint |
| NDCs are well formed | error | A cleaned NDC isn't in 5-4-2 or 5-4 form | A new format broke `ndc.py`. Add it as a test case and fix the parser |
| recalls are fresh | warning | The newest recall report is over 14 days old | FDA publishes weekly but sometimes pauses, like over holidays. If FDA is publishing and we're not getting it, check the query in `ingest.py` |
| shortage list is fresh | warning | The newest shortage update is over 14 days old | Same idea, for the shortage list |
| NDC directory is fresh | warning | The weekly refresh is over 10 days late | Look for the NDC step in recent runs' output |
| shortage statuses are known | warning | A status besides Current, Resolved, To Be Discontinued or Discontinued | If it's a real new status, add it to `KNOWN_STATUSES` in `checks.py` and check it lands on the right list |
| identified rate is steady | warning | The share of recalls with an NDC or a drug name fell more than 5 points since the last run | Run `sql/drug_names_by_source.sql` and compare the sources with the last run's numbers |
| recalls pulled | warning | The count spiked or went quiet | A spike can be real, like one firm recalling hundreds of products. Quiet means openFDA returned nothing |
| shortage rows | warning | The count spiked or went quiet | Compare with FDA's website before trusting it |
| unmatched recalls | warning | The count spiked or went quiet | A spike usually means a matching step broke |
| recalls missing a field | warning | The count spiked or went quiet | FDA may be sending blanks in a field it used to fill |

The last four are tracked counts. A spike means more than twice the usual and at least 20 over it, where usual is the median of the last 7 runs. Quiet means 0 after 5 runs in a row above 0.

## Claude: costs, credits and keys

The pipeline uses Claude Haiku for two jobs: root causes the rules can't tag, and drug names matching can't find. Each distinct text is asked once and cached, so a normal day costs a fraction of a cent. One run makes at most 2,000 root-cause calls and 3,000 drug-name calls, and stops calling after 15 minutes each, so a backfill can't run away. Each run's calls and cost are in `run_log.csv`.

**Credits** are prepaid in the Claude Console. The digest estimates what's left from the run log, and the Console shows the exact balance. After topping up, set `CLAUDE_CREDITS_USD` to the new balance and `CLAUDE_CREDITS_SINCE` to today.

**When credits run out,** the calls fail, but the run doesn't. Those recalls wait, and the waiting count shows up in the digest. Top up, and the next run catches up on its own.

**The pipeline's key** expires on the date in `CLAUDE_KEY_EXPIRES`, and the digest counts down to it. To replace it, create a key in the Console's Default workspace, update the `ANTHROPIC_API_KEY` Actions secret (and the codespace's, if you set one there), then update `CLAUDE_KEY_EXPIRES`.

**The chatbot's key** is separate, in the `dashboard` workspace, and the digest doesn't track it. When it expires, the Ask the data tab shows an error. Make a new key in that workspace and update the app's Secrets in Streamlit.

## The dashboard and the chatbot

The dashboard is `app/streamlit_app.py`, on Streamlit Community Cloud. It doesn't install the pipeline. It downloads the files it needs from the data branch at most once an hour, so a new run shows up within the hour without redeploying.

**Ask the data** is behind `ASK_PASSCODE` and capped at 50 questions a day, shared by everyone using the app. The count starts over each day, and when the app restarts. Claude writes one SQL query, which runs on a locked, in-memory copy of the tables, then answers from the rows. Each question costs about 0.05 cents. To score it after changing the prompt, run `python -m shortagesignal.ask eval`, which costs under a cent.

**Keeping it awake:** Streamlit's free tier puts the app to sleep when nobody visits. The keep-awake workflow visits every 6 hours with a real browser, since a plain ping doesn't count, and fails, which emails you, only if the app won't wake up. To check it, run **Keep the dashboard awake** from the Actions tab and read its log.

**If the dashboard is down,** open the app's **Manage app** panel on Streamlit and check the logs, then use **Reboot app**. If a file it needs is missing from the data branch, the last daily run probably failed.

## Power BI

The report is a Power BI project in `reports/powerbi/`, saved as text files so git can track it. Open `shortagesignal.pbip` in Power BI Desktop and click **Refresh**. If it asks how to connect to GitHub, choose **Anonymous**. The data cache (`cache.abf`) and local settings are git-ignored, so a fresh clone opens empty until the first refresh.

## Paused schedules

GitHub pauses scheduled workflows in a public repo after 60 days without activity in it. If the Monday digest stops arriving, open **Actions** and click **Enable workflow** on **Daily pipeline**, **Weekly digest** and **Keep the dashboard awake**.

## Working on the code

Use the codespace, or install locally with `pip install -e ".[dev]"`. Then:

```
git fetch origin data
git archive origin/data | tar -x -C data          # the latest data, into data/
pytest                                             # the tests
ruff check .                                       # the linter
python -m shortagesignal.ingest                    # a full run, with Claude off
python -m shortagesignal.run_sql sql/lag_by_root_cause.sql     # any SQL file, by table name
python -m shortagesignal.risk backtest             # the risk flag's backtest
python -m shortagesignal.dictionary                # rebuild docs/data_dictionary.md
SHORTAGESIGNAL_DATA=local streamlit run app/streamlit_app.py   # the dashboard on local data
```

Every change goes through an issue, a branch and a pull request. See [git_workflow.md](git_workflow.md).
