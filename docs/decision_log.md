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
