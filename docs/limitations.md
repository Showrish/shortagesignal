# Limitations

What ShortageSignal can't see, where it can be wrong, and how far its findings go. The numbers below are from the backtest of Nov 16, 2026. Every daily run works the backtest out again, and the dashboard shows the latest numbers.

## What the data leaves out

- **The shortage feed mostly lists shortages that are still going.** FDA keeps resolved ones for a while, then they drop off. A shortage that ended years ago may not be there at all, so older recalls look less often followed by a shortage than they really were. The analysis starts in 2020 for this reason, and even then the early years are probably undercounted.
- **The pipeline's own shortage history is short.** Daily snapshots started in October 2026. Before that, all it knows is what FDA's feed still shows.
- **It's FDA's list only.** Other shortage lists, like ASHP's, count more shortages. A drug can be short in hospitals without being on FDA's list.
- **The shortage start date is FDA's first posting.** The real shortage often starts earlier, so the days from recall to shortage are probably too long.
- **Recalls only appear once FDA classifies and publishes them.** That can be weeks after the firm started the recall. FDA also corrects old reports, and the pipeline only re-pulls the last 60 days, so a correction to an older report is missed.
- **FDA's own annotations are often empty** for compounded or unusual products, which leaves only the free text to work from.

## Where matching can be wrong

- **About 17% of recalls have no drug name,** mostly compounded products and unusual descriptions. They can't link to a shortage by drug, so they're left out of the drug-level analysis.
- **Drug-only links are loose.** They mean the same drug from any company. 32 of the 45 recalled drugs that were followed by a shortage rest on this kind of link, so many of those shortages may have nothing to do with the recall.
- **Drug names don't always line up.** Salts and combination products can split one drug into two names, like quinapril and quinapril hydrochloride, or miss a match between them.
- **Company names are cleaned with rules.** Subsidiaries, renamed firms and unusual spellings can still be counted as different companies.

## Where the AI parts can be wrong

The full results are in [ai_evals.md](ai_evals.md). In short:

- **Root causes:** rules tag about 99% of recalls, and Claude tags the rest. On 30 fresh recalls nothing was tuned on, the rules were right 18 of 20 times and Claude 5 of 9, on the hardest leftovers. That's a small sample with wide ranges. Claude's low and medium confidence answers go to a review list, but nobody reviews them automatically.
- **Drug names:** Claude named the drug for about 4,900 recalls. On the fresh labels its names were right 15 of 15 times when salts are ignored, against 9 of 12 for matching. Its name is only used when Claude is fairly sure and the drug is known to exist, or, for a combination like a compounded semaglutide with cyanocobalamin, when every part is. That catches most wrong answers, but not all.
- **Ask the data:** the chatbot got 17 of 18 test questions right, but the developer wrote those questions and fixed the prompt after seeing the first results. Real questions are looser. Every answer shows its SQL so it can be checked, and the first live question did come back wrong before a fix.
- **One person labeled everything,** with no second labeler, and some root-cause categories have fuzzy edges.

## How far the findings go

- **Shortages after a recall are rare.** Of the 2,868 recalled drugs since 2020 whose route can be read and that have had a full year since their report, 27 (0.9%) were followed within that year by a shortage of the same drug given the same way, and 41 of 3,302 (1.2%) through any link. With so few, every rate has a wide range. Watch flags caught 20 of the 27, which could be anywhere from about 55% to 87%.
- **Followed doesn't mean caused.** Only 4 outcomes were the same company's product, by cleaned company name, so a recall rarely becomes that company's own shortage. A subsidiary and its parent count as different companies, so 4 is a lower bound. A recall of a fragile drug and a later shortage can both happen without one causing the other.
- **The signs were chosen by looking at this same data,** so the backtest is optimistic, and its split by period is a consistency check, not a holdout. Earlier versions overstated the signal twice: counting recall events instead of drugs put Sterility at about 3 times the average, and starting each year when the firm began the recall, before FDA reported it, counted shortages no flag could have seen. The decision log has the details.
- **The backtest only counts recalls with a full year after their report,** and starts each year on the report date, the first day a flag could exist. That fixes incomplete follow-up and look-ahead, not the missing resolved shortages above, which still undercount older years.
- **Matching decides what counts as followed.** The backtest counts it three ways: any link, the same route (the headline) and the same company. The route is read from the text, and it couldn't be read for 434 recalled drugs, which same route leaves out, while 6 more outcomes linked only to shortage listings whose route couldn't be read. A blind hand check of 30 links, a pilot, backs this up. The same ingredient held on 29 of 30. Where the code read both routes, it agreed with the hand label on 21 of 22, and of the 6 where it couldn't read one, 5 were the same route by hand, so same route misses some outcomes rather than inventing them. The company comparison never called two different companies the same, 9 of 9, but missed 5 pairs that were, like Hospira and "Hospira, Inc., a Pfizer Company", so same company is a lower bound. With 30 links, each of these has a wide range. The details are in audit/link_check.md.

## How far the risk flag goes

- **High is a status, not a prediction.** It means the drug is on FDA's shortage list right now, so the recall can make a shortage worse.
- **Watch is a weak signal.** Injectables were followed by a shortage of the same drug given the same way 1.7% of the time, against 0.4% for other recalls whose route can be read. Most watch flags will never lead to a shortage.
- **The honest test is still running.** `risk_log.csv` records each new recall's flag on the day it's given, along with the drug and event it was matched to that day, and `python -m shortagesignal.risk check-log` checks them against shortages that come later, which the Monday digest reports too. The verdict needs a full year, so it comes after Oct 26, 2027, but the check also reports 30, 90 and 180 days, each counted only on flags old enough to have finished it, and the lead time on its own. Flags before Oct 26, 2026 used the old points and are kept apart. Flags logged before mid-November 2026 have no saved drug name, so they're judged on today's. Which shortage listings count still comes from today's matching of the logged recalls.

## Keeping it running

- **A few recalls come without a real recall number.** FDA occasionally gives N/A or nothing. Each of those is stored under its own NA- key, made from its event and product text, so they don't overwrite each other. If FDA later edits such a recall's product text, it shows up as a new row rather than an update.
- **It depends on openFDA.** The data checks catch fields that disappear, lists that collapse and stale data, but not a field that quietly changes meaning.
- **One person maintains it.** GitHub pauses the schedule after 60 days without activity in the repo, and the Claude credits are prepaid. The weekly digest warns about both.
- **The data branch keeps one commit,** and run backups last 30 days. Older states of the data can only be rebuilt from the tables' own history, like `recall_versions` and `shortage_snapshots`.
- **The dashboard runs on Streamlit's free tier,** which puts apps to sleep without visitors. A workflow opens it every 4 hours to keep it awake, but if Streamlit changes how sleeping works, the first visitor may still see a wake-up button.

## Not medical advice

ShortageSignal is built on public openFDA data for analysis and learning. It isn't for medical or purchasing decisions.
