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

## 2026-10-12: two kinds of data checks
- **Chose:** error checks stop the run and keep yesterday's data, while warning checks let the run save and flag the problem
- **Why:** broken data, like duplicates or a field FDA stopped sending, must never be saved. Stale or unusual data still beats no data
- **Passed on:** stopping on every oddity, which would block the shortage snapshot over one slow week at FDA

## 2026-10-12: GitHub's failure email as the alert
- **Chose:** a failed check fails the run, and GitHub's built-in failure email does the alerting. Warnings show on the run page and in check_log.csv
- **Why:** it works with zero setup and no passwords stored anywhere. The weekly digest on Day 12 will summarize the warnings
- **Passed on:** a custom email on every run

## 2026-10-12: spike and silence rules
- **Chose:** tracked counts warn when they jump past twice their usual level by more than 20, or drop to zero after five busy runs in a row
- **Why:** a check that suddenly finds nothing can mean a broken check, not clean data
- **Passed on:** fixed limits, which go stale as the data grows

## 2026-10-12: a hand audit of 200 random recalls as the answer key
- **Chose:** 200 recalls picked at random with a fixed seed, reviewed by hand in a spreadsheet next to what the pipeline concluded
- **Why:** the only way to know how often the pipeline is right is to check it against a person. The fixed seed means anyone can rebuild the same sample
- **Passed on:** spot-checking interesting examples, which leans toward the easy cases

## 2026-10-12: a fixed list of 12 root causes
- **Chose:** 12 root-cause categories with written definitions, picked from a dropdown
- **Why:** the same categories become the labels Claude gets scored against on Day 8, so they have to be consistent
- **Passed on:** writing causes in free text

## 2026-10-12: NDC checks in the audit are automatic except the leftovers
- **Chose:** the audit sheet lists the NDCs found in the text, plus any code-like numbers the extractor skipped. ndc_ok gets filled in automatically when nothing is left over, so a person only checks rows with leftovers
- **Why:** some recalls list 10 to 15 NDCs, and comparing them by eye is slow and error-prone. The part that needs judgment is deciding whether a leftover number is a missed NDC or something like a lot number
- **Passed on:** checking every code by hand

## 2026-10-13: rules first, Claude for the rest
- **Chose:** SQL keyword rules tag what they can, and Claude Haiku only tags what the rules leave as NULL
- **Why:** rules are free, instant and easy to check. Claude handles the vague and unusual reasons, which is exactly where rules fail
- **Passed on:** sending every recall to Claude

## 2026-10-13: Claude answers through a tool
- **Chose:** Claude has to answer by calling a tool whose schema only allows the 12 category names, plus a confidence level
- **Why:** the answer is always one of the categories, so there's nothing to parse or clean up
- **Passed on:** free-text answers

## 2026-10-13: Claude gets the same rulebook as the hand audit
- **Chose:** the prompt includes the 12 definitions and the same tie-breaking rules used in the audit
- **Why:** Claude gets scored against the audit, so it should follow the same rules
- **Passed on:** letting Claude decide on its own what each category means

## 2026-10-13: Claude only runs in GitHub Actions
- **Chose:** the daily run calls Claude only when SHORTAGESIGNAL_USE_CLAUDE=1, which only the scheduled workflow sets. Answers are cached by recall number and reason text, and each run has a time budget
- **Why:** local test runs never spend money by accident, a recall is never sent twice, and the history backlog gets worked through over a few runs
- **Passed on:** tagging the whole history in one local run

## 2026-10-13: precautionary CGMP recalls, and re-checking the answer key
- **Chose:** recalls FDA labeled CGMP that only describe a risk ("manufactured under the same conditions as...", "conditions that could...", "potential contamination") stay CGMP, in both the rules and Claude's prompt. Claude's medium-confidence answers go to the review sheet too. After the first scoring, every row where the rules or Claude disagreed with my labels was re-checked against the written audit rules, with Claude suggesting the fixes, not against the taggers' answers. Labels that broke those rules were corrected, and the ones that held up led to the new rules.
- **Why:** nothing was found in a precautionary recall's product, so naming a specific defect overstates what happened. Medium-confidence answers were right only 7 of 15 times. Checking labels against the written rules keeps the answer key consistent without bending it toward the taggers.
- **Passed on:** leaving known slips in the answer key, and changing labels just to match the taggers
- **Caveat:** the rules were tuned on these same 99 rows, so their score on them is optimistic. Fresh hand labels are the honest test.

## 2026-10-13: rules for standard FDA labels found in Claude's unsure tags
- **Chose:** new rules for reasons Claude kept tagging with low or medium confidence. Skin abscesses after an injection count as Sterility. Stability data that doesn't support the expiry date, stability testing failures, crystallization, incorrect or undeclared excipients, incorrect product formulation, and not meeting the USP or OTC monograph count as Failed specification. Particle size stays Failed specification, while other particles count as Particulates.
- **Why:** after the first full run, 479 of Claude's 599 tags were unsure. Grouping them by firm and reason in SQL showed that 298 came from one event, a compounding pharmacy that recalled 298 products after reports of skin abscesses, and that most of the Failed specification ones used standard FDA labels the rules didn't know. Rules are free, consistent and need no review.
- **Passed on:** reviewing each unsure tag by hand

## 2026-10-14: Claude names drugs, but only from a known list
- **Chose:** recalls that matching can't name a drug for go to Claude Haiku, which answers through a tool with the ingredients, strength, dosage form, whether it was compounded, and its confidence. Matching uses the answer only when the confidence is high or medium and the name is a known drug: one in the NDC directory, on the shortage list, or attached by openFDA to a past recall. Claude's name is the last resort, after NDC, openFDA and text matching. Matching runs twice, before and after Claude, so the run log has exact before and after numbers. Each run makes at most 3,000 calls in 15 minutes, so the backlog clears over a couple of runs.
- **Why:** a made-up or misspelled name would create false links to shortages. Checking against real drug names stops Claude from inventing drugs, and the names on past recalls cover drugs that are off the market now, like ranitidine.
- **Passed on:** letting Claude's answer override the other methods, and fuzzy matching of Claude's names

## 2026-10-14: ask once per distinct text, and review by reason
- **Chose:** Claude is asked once per distinct reason when tagging and once per distinct product text when naming drugs. The tag review sheet has one row per reason, with how many recalls it covers. The run page now shows a table of the pipeline's main numbers under the data checks.
- **Why:** one pharmacy's recall produced 298 rows with the same reason. One answer per text is cheaper, always consistent, and lets a reviewer decide once.
- **Passed on:** one call per recall
## 2026-10-14: scoring Claude's drug names, ignoring salts
- **Chose:** the extraction eval reports two scores, the exact drug key and one that ignores salt words, so fentanyl and fentanyl citrate count as the same drug. Three answer-key labels were corrected after the first scoring, checked against the written audit rules: a typo (evorphanol), a missing PGE-1 in a combination, and a drug class (prostaglandin) instead of the drug (alprostadil).
- **Why:** recall text often leaves the salt off, so the hand labels did too, while Claude gave full names. Counting those as wrong understated Claude.
- **Result:** on the 74 audited recalls with a clear drug, the pipeline finds 65% before Claude and 82% with it, ignoring salts. None of the 13 answers Claude added were wrong. The known-drug check blocked 10 more, mostly compounded mixes that can't link to a shortage anyway, and it caught Claude's only real mistakes.
- **Passed on:** loosening the known-drug check for compounded mixes

## 2026-10-16: count recall events, not recall numbers
- **Chose:** the recall-to-shortage analysis counts recall events (FDA's event_id), dated by their earliest recall start date and tagged with the most common root cause among their products. It looks at events since 2020, and a shortage counts when FDA posted it within 365 days after the event.
- **Why:** one event can cover hundreds of products. Sterility has 6,410 recall numbers but only 501 events, so counting recall numbers would mostly describe a few big compounding-pharmacy recalls. FDA's shortage feed mostly lists shortages that are still going on, so older recalls can't be matched to shortages that ended long ago.
- **Result:** about 2% of recall events since 2020 were followed within a year by a shortage FDA still lists. Sterility stands out at 6.2%, about three times the average, usually 4 to 5 months later.
- **Limit:** only shortages FDA still lists are seen, and drug-level links can be coincidence. The daily snapshots since October 11, 2026 keep every shortage from now on.

## 2026-10-16: a points-based risk flag, not a trained model
- **Chose:** each recall gets 2 points for a Sterility root cause, 2 when only 1 or 2 companies list the drug in the NDC directory (1 point for 3 to 5), and 1 for an injectable. 4 or more is high, 2 or 3 is watch. Recalls reported in the last 30 days go into risk_log.csv with the flag they got that day.
- **Why:** with about 40 positive events since 2020, a model would learn to always say no shortage. Points are easy to explain and check, and the backtest reports each level's lift over the average. The log makes a fair test possible later, on recalls the flag had never seen.
- **Passed on:** a trained classifier
- **Limit:** the Sterility points came from the same data the backtest uses, so its numbers are optimistic. Repackagers that don't say so in their name still count as companies.

## 2026-10-16: an XmR control chart on weekly recall events
- **Chose:** weekly recall events by FDA report week, with limits from the two years before the last 13 weeks, using the moving range (an XmR chart).
- **Why:** weekly counts vary more than a Poisson c-chart assumes, so a c-chart would flag too many ordinary weeks. Counting events keeps one big recall from looking like a crisis week.
- **Passed on:** a c-chart, and counting recall numbers
