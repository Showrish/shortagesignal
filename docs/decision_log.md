# Decision log

One entry per decision: what was chosen, why, and what was passed on.

## 2026-10-11: openFDA as the data source
- **Chose:** openFDA drug enforcement reports (recalls) and drug shortages
- **Why:** official FDA data, free, no key needed, and it keeps updating (recalls weekly, shortages daily)
- **Passed on:** scraping FDA web pages (breaks when a page changes) and paid shortage databases

## 2026-10-11: bulk files for history, live API for daily updates
- **Chose:** openFDA's bulk download files for the one-time full history, and the live API for daily pulls
- **Why:** one zip per dataset instead of paging 1,000 records at a time, and API paging stops at 25,000 records
- **Passed on:** paging the API for everything

## 2026-10-11: DuckDB for storage and SQL
- **Chose:** DuckDB, a database that lives in a single file
- **Why:** no server to run, fast SQL on millions of rows, and already familiar from CreditIQ and WeatherCastML
- **Passed on:** PostgreSQL (needs a running server) and Snowflake (the trial expires and usage costs money)

## 2026-10-11: SQL for the logic, Python as glue
- **Chose:** cleaning, matching and checks written in SQL, with Python only downloading data and running queries
- **Why:** SQL is easier to read, review and explain than the same logic spread across Python code
- **Passed on:** doing the transformations in pandas

## 2026-10-11: run the repo like a team project
- **Chose:** protected main, one branch and pull request per issue, CI with linting and tests, releases per batch
- **Why:** every change gets checked before it lands, and the history reads like a real project
- **Passed on:** committing straight to main

## 2026-10-11: code on main, data on a separate branch
- **Chose:** the pipeline writes its data to a `data` branch that only it touches
- **Why:** daily data commits would bury the code changes in main's history. Companies keep data in a warehouse, and a dedicated branch is the free version of that
- **Passed on:** committing data to main, and paid cloud storage

## 2026-10-11: an installable package
- **Chose:** the code lives in `src/shortagesignal` and installs in editable mode
- **Why:** the pipeline, the tests and the scripts all import the same code, with no path tricks
- **Passed on:** a folder of loose scripts

## 2026-10-11: develop in GitHub Codespaces
- **Chose:** a cloud dev environment defined in `.devcontainer/`, opened from the browser
- **Why:** the laptop changes every 5 days. The environment and its packages live in the cloud and rebuild themselves from the repo, and the free tier covers this project
- **Passed on:** reinstalling tools on every laptop, and a portable setup on a USB drive

## 2026-10-11: Day 1 data findings
- **Recalls:** 18,002 rows from June 2012. 51% carry an NDC, about 80% for 2024 to 2026
- **Shortages:** 1,582 rows, but only 19 Resolved. The feed mostly keeps current shortages
- **What changes:** history undercounts the recall to shortage link. Main historical view is current shortages preceded by a recall, and daily snapshots become the real history
- **Reasons:** 56% start with a standard label, which needs case and spelling cleanup. Claude handles the rest
- **Check next:** placeholder-looking 2012-01-01 dates, and counting shortages by drug, not rows
## 2026-10-11: Parquet files for storage, DuckDB as the engine
- **Chose:** one Parquet file per table, read and written by DuckDB
- **Why:** Parquet is compact and readable by DuckDB, Streamlit and Power BI. A DuckDB database file is one big binary that changes on every run
- **Passed on:** keeping the .duckdb file as the source of truth

## 2026-10-11: re-pull 60 days of recalls and merge by recall number
- **Chose:** each run re-pulls the last 60 days of reports and keeps the latest version of each recall
- **Why:** FDA sometimes corrects past reports. The window catches corrections without re-downloading all 18k rows every day
- **Passed on:** pulling only since yesterday (misses corrections) and a full re-download every day (wasteful)

## 2026-10-11: nested fields stored as JSON text
- **Chose:** every column is text, with nested fields saved as JSON strings
- **Why:** the shape of nested fields changes between pulls, which breaks merging old and new data
- **Passed on:** keeping DuckDB's nested types

## 2026-10-11: daily shortage snapshots
- **Chose:** save the full shortage list every day with its date, keyed by package NDC, or a hash of name, company and presentation when there's no NDC
- **Why:** the feed only shows current status, so the history has to come from our own snapshots. Rerunning on the same day replaces that day's rows instead of doubling them
- **Passed on:** overwriting one current list

## 2026-10-11: keep every version of a recall
- **Chose:** a recall_versions table that saves a recall again only when FDA changes its content, next to a recalls table with the latest version for analysis
- **Why:** nothing is ever lost, a bad pull can be undone, and FDA's edits become data, like a recall moving from Class II to Class I
- **Passed on:** keeping only the latest version

## 2026-10-11: shortage key is package NDC + list type + company
- **Chose:** key each shortage row by package NDC, list type (shortage or discontinuation) and company, and merge rows FDA lists twice under the same key, recording the count in fda_listings
- **Why:** the first real run found 30 duplicate NDC keys. The same package can sit on the shortage list and the discontinuation list at once, or be listed under two companies
- **Passed on:** the package NDC alone

## 2026-10-11: daily run on GitHub Actions
- **Chose:** a scheduled GitHub Actions workflow at 12:00 UTC, plus a manual Run workflow button
- **Why:** free for public repos, nothing to host, and it runs with every laptop off
- **Passed on:** a cron job on a personal computer, and paid cloud schedulers

## 2026-10-11: the data branch keeps only the latest data
- **Chose:** each run force-pushes one commit with the current files to the data branch, and uploads a 30-day backup of that run's data
- **Why:** Parquet files rewritten every day would bloat git history fast. The tables already keep their own history in the snapshots and recall versions
- **Passed on:** normal commits on the data branch, and committing data to main

## 2026-10-11: all-or-nothing runs
- **Chose:** every run works on a staged copy and swaps the files in only if every step succeeds. A run log row gets written either way
- **Why:** a failure halfway can never leave recalls updated but shortages stale
- **Passed on:** writing each file as soon as its step finishes

## 2026-10-11: lean shortage history, full current table
- **Chose:** the daily history keeps 19 tracking columns, and today's full rows, including FDA's openfda block, go to shortages_current
- **Why:** keeping every field every day would push the history file past GitHub's 100 MB file limit within months
- **Passed on:** snapshotting every column

## 2026-10-12: NDCs normalized to 11 digits, matched at product level
- **Chose:** convert every NDC to the 11-digit 5-4-2 form (ndc11), and keep its labeler and product part (ndc9) for matching
- **Why:** FDA writes NDCs in three 10-digit layouts, so the same package can look different in two datasets. Product level matches the same drug across package sizes
- **Passed on:** matching NDCs as raw text

## 2026-10-12: short and dash-less NDCs only count after the word NDC
- **Chose:** two-part product codes and dash-less codes are only read right after "NDC". Dash-less 10-digit codes get their layout from the NDC directory, and ones that fit two packages are skipped
- **Why:** two-part codes look like lot numbers, and 10 dash-less digits fit three different layouts
- **Passed on:** reading every number that looks like a code

## 2026-10-12: firm keys
- **Chose:** company names uppercased, with punctuation, legal words (Inc, LLC, Ltd) and filler words (Pharmaceuticals, Laboratories, USA) removed
- **Why:** "Pfizer Inc." and "PFIZER INC" are the same company and need the same key
- **Passed on:** fuzzy matching for now. Day 5 decides whether it's needed

## 2026-10-12: parsing in Python, joins in SQL
- **Chose:** NDC and company name parsing written in Python with unit tests, while joins and counts stay in SQL
- **Why:** layout rules are clearer and easier to test in Python, and matching tables is what SQL is for
- **Passed on:** regex-only parsing inside SQL

## 2026-10-12: identified and linked are two separate numbers
- **Chose:** report how many recalls we can identify (we know which drug it is) separately from how many link to a shortage
- **Why:** most recalled drugs never go short, so a low link rate is normal. A low identification rate is the real data problem
- **Passed on:** one combined match rate

## 2026-10-12: four link strengths, keep the strongest
- **Chose:** link by package NDC, product NDC, same drug and company, or same drug from any company, keeping the strongest link for each recall and shortage pair
- **Why:** a shortage is about the drug, not one company's package. Stronger links are more certain, and the level says how sure each one is
- **Passed on:** NDC-only links, which would miss every recall without an NDC

## 2026-10-12: a name from the text only counts if the drug exists
- **Chose:** a drug name taken from a recall's description counts only if it's a generic name in the NDC directory or on the shortage list, or a known brand name
- **Why:** descriptions start with all sorts of text, and checking against known drugs keeps junk out
- **Passed on:** trusting whatever phrase a description starts with

## 2026-10-12: drug keys keep salts and drop forms
- **Chose:** drug names lose form, strength and packaging words but keep salts, so clindamycin phosphate and clindamycin palmitate stay different
- **Why:** different salts are often different products, like an injection and an oral liquid
- **Passed on:** stripping salts too

## 2026-10-12: shortage IDs from every listing ever seen
- **Chose:** shortage IDs and drug keys come from all the snapshots, not just today's list
- **Why:** a shortage that drops off FDA's list still needs to match the recalls from before it resolved
- **Passed on:** today's list only
