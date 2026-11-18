# ShortageSignal

A daily, automated pipeline on real FDA data that links drug recalls to drug shortages, checks its own data, uses Claude to fill the gaps that rules can't, and shows what it finds on a live dashboard.

**[Live dashboard](https://shortagesignal.streamlit.app)** · runs every day at 12:23 UTC on GitHub Actions · costs a fraction of a cent a day

![The live dashboard's Risk flags tab](docs/images/dashboard.png)

## What it found

As of Nov 16, 2026, on drugs reported in a recall from 2020 to Nov 2025 that have had a full year since their report, counting each drug in each recall event once. The dashboard always has the latest numbers. They describe this dataset, not every shortage: FDA's feed drops resolved shortages after a while, so older years are undercounted.

- **Shortages after a recall are rare.** 27 recalled drugs (0.9%) were followed within that year by a shortage of the same drug given the same way, and 41 (1.2%) if any listing with the same drug name counts.
- **Injectables are the one sign that held up.** 1.7% of recalled injectables were followed by a shortage of the same route, against 0.4% of other recalls whose route can be read. Watch flags caught 20 of the 27 for 40% of the review work, about 4 flags a week, and the gap shows up in both 2020-22 and 2023 on.
- **The warning comes months ahead.** For watch flags that were followed, the shortage was posted a median of 154 days after the recall's report.
- **Sterility problems add nothing once injectables are accounted for.** Sterile injectables came in at 1.4%, against 2.2% for other injectables. Sterility only looked strong because most sterility recalls are injectables.
- **Followed doesn't mean caused.** Only 4 outcomes were the same company's product, so a recall rarely becomes that company's own shortage. A recalled injectable is more a marker of a fragile drug than a cause.
- **The first versions overstated it.** Counting recall events instead of drugs made sterility look 3 times riskier than average, and starting each year when the firm began the recall, weeks before FDA reported it, counted shortages no flag could have seen. The [decision log](docs/decision_log.md) has how each was caught.

## What it does

Every day, GitHub Actions runs the pipeline end to end:

1. **Pulls from openFDA:** the last 60 days of recalls, merged by recall number with a full edit history, a dated snapshot of the shortage list, and, once a week, the NDC directory.
2. **Identifies each recall's drug** from its NDC codes, FDA's own annotations and the product text, then **links recalls to shortage listings** at four strengths: the same package, the same product, the same drug and company, or the same drug.
3. **Asks Claude Haiku to name the drug** when matching can't. That takes recalls with a drug name from 56% to 83%, and a name is only used when Claude is fairly sure and the drug is known to exist.
4. **Tags each recall's root cause.** SQL rules tag 99%, and Claude tags the rest, limited to 12 categories by a tool schema.
5. **Flags each recall:** high when its drug is already on the shortage list, watch for an injectable. Every new flag is logged the day it's given, and the Monday digest checks the log against shortages that come later. It also charts weekly recall events against a normal range.
6. **Runs 16 data checks before saving anything.** Errors keep yesterday's data, and warnings flag the run.
7. **Saves every table to the `data` branch,** which the dashboard, the Power BI report and the Monday digest all read.

```mermaid
flowchart LR
    subgraph pull ["1. Pull, every day"]
        direction TB
        recalls["Recalls<br>last 60 days"]
        shortages["Shortage list<br>daily snapshot"]
        ndc["NDC directory<br>weekly"]
        recalls ~~~ shortages ~~~ ndc
    end
    subgraph understand ["2. Understand each recall"]
        direction TB
        name["Name the drug<br>NDC, text, then Claude"]
        link["Link to shortages<br>four match strengths"]
        cause["Tag the root cause<br>rules, then Claude"]
        flag["Flag the risk,<br>chart weekly recalls"]
        name --> link --> cause --> flag
    end
    subgraph check ["3. Check"]
        direction TB
        checks{"16 data<br>checks"}
        keep["Error: save nothing,<br>keep yesterday's data"]
        checks -- error --> keep
    end
    subgraph use ["4. Save and use"]
        direction LR
        data[("data branch")]
        dash["Streamlit dashboard"]
        pbi["Power BI report"]
        digest["Monday digest"]
        data --> dash & pbi & digest
    end
    pull --> understand --> check
    check -- pass --> use
```

## See it

- **[The dashboard](https://shortagesignal.streamlit.app)** has recent risk flags, the weekly control chart, what follows a recall, and **Ask the data**, where Claude writes one read-only SQL query over the tables and answers from the rows, with the query shown. That tab is behind a passcode.
- **The Power BI report** is in [`reports/powerbi/`](reports/powerbi). Open `shortagesignal.pbip` in Power BI Desktop and click Refresh, and it pulls the latest data straight from GitHub.
- **The Monday digest** is posted as a GitHub issue labeled `digest`, with an Excel list of the items that need a person's look.

## How the AI was tested

Each of Claude's three jobs was scored against answers a person wrote: first on a 99-recall hand audit that everything was tuned on, then on 30 fresh recalls labeled blind.

| Job | First audit (tuned on) | Fresh labels |
|---|---|---|
| Root causes, rules | 99 of 99 | 18 of 20 |
| Root causes, Claude, on what the rules can't tag | not tested | 5 of 9 |
| Drug names, Claude, ignoring salts | 70 of 74 | 15 of 15 |
| Ask the data | 17 of 18 test questions | |

The fresh labels are the honest numbers, and the samples are small. [docs/ai_evals.md](docs/ai_evals.md) has the details, including the 10 drug labels that were fixed in the open and the chatbot's first live question that came back wrong.

## Built with

Python, SQL on DuckDB, Parquet, GitHub Actions, Claude Haiku through the Anthropic API with tool use, Streamlit, Power BI, openpyxl, pytest and ruff.

## Run it

Open it in **GitHub Codespaces** (Code, then Codespaces), and everything installs from `.devcontainer/`. Or install it locally with `pip install -e ".[dev]"`. Then:

```
git fetch origin data
git archive origin/data | tar -x -C data       # the latest data, into data/
pytest                                          # 124 tests
python -m shortagesignal.ingest                 # a full run, with Claude off
SHORTAGESIGNAL_DATA=local streamlit run app/streamlit_app.py
```

The [runbook](docs/runbook.md) has every other command, and what to do when something breaks.

## Docs

| Doc | What's in it |
|---|---|
| [Runbook](docs/runbook.md) | What runs when, keys and settings, rerunning a day, what each data check means and what to do |
| [Data dictionary](docs/data_dictionary.md) | Every file and column, built from the data itself |
| [AI evals](docs/ai_evals.md) | How Claude's three jobs were tested, and what the scores mean |
| [Limitations](docs/limitations.md) | What the data leaves out, where it can be wrong, how far the findings go |
| [Decision log](docs/decision_log.md) | Every choice and why, including the ones that were reversed |
| [Git workflow](docs/git_workflow.md) | Issues, branches, pull requests and CI |

## How the repo works

`main` is protected, and every change goes through an issue, a branch and a pull request that CI has to pass. The work is planned in four batches, each a milestone on the Issues tab.

```
src/shortagesignal/   the pipeline: ingest, identify, match, extract, tagging, risk, checks, digest, ask
sql/                  the root-cause rules and every analysis query
app/                  the Streamlit dashboard
reports/powerbi/      the Power BI project
audit/                the hand labels and every eval result
docs/                 the runbook, data dictionary, AI evals, limitations and decision log
tests/                the tests
.github/workflows/    the daily run, the weekly digest, and CI
```

## Disclaimer

Built on public openFDA data for analysis and learning. It isn't medical advice.

Built by Showrish Reddy Sampath · [LinkedIn](https://www.linkedin.com/in/showrish-reddy-sampath-b508a22a6) · [GitHub](https://github.com/Showrish)
