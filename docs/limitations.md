# Limitations

What ShortageSignal can't see, where it can be wrong, and how far its findings go. The numbers below are from the backtest of Oct 26, 2026. The latest ones are in [audit/risk_backtest.md](../audit/risk_backtest.md).

## What the data leaves out

- **The shortage feed mostly lists shortages that are still going.** FDA keeps resolved ones for a while, then they drop off. A shortage that ended years ago may not be there at all, so older recalls look less often followed by a shortage than they really were. The analysis starts in 2020 for this reason, and even then the early years are probably undercounted.
- **The pipeline's own shortage history is short.** Daily snapshots started in October 2026. Before that, all it knows is what FDA's feed still shows.
- **It's FDA's list only.** Other shortage lists, like ASHP's, count more shortages. A drug can be short in hospitals without being on FDA's list.
- **The shortage start date is FDA's first posting.** The real shortage often starts earlier, so the days from recall to shortage are probably too long.
- **Recalls only appear once FDA classifies and publishes them.** That can be weeks after the firm started the recall. FDA also corrects old reports, and the pipeline only re-pulls the last 60 days, so a correction to an older report is missed.
- **FDA's own annotations are often empty** for compounded or unusual products, which leaves only the free text to work from.

## Where matching can be wrong

- **About 24% of recalls have no drug name,** mostly compounded products and unusual descriptions. They can't link to a shortage by drug, so they're left out of the drug-level analysis.
- **Drug-only links are loose.** They mean the same drug from any company. 32 of the 45 recalled drugs that were followed by a shortage rest on this kind of link, so many of those shortages may have nothing to do with the recall.
- **Drug names don't always line up.** Salts and combination products can split one drug into two names, like quinapril and quinapril hydrochloride, or miss a match between them.
- **Company names are cleaned with rules.** Subsidiaries, renamed firms and unusual spellings can still be counted as different companies.

## Where the AI parts can be wrong

- **Root causes:** rules tag about 99% of recalls, and Claude tags the rest. Both were scored on the same 99 hand-audited recalls that the rules were tuned on, so those scores are optimistic. Claude's low and medium confidence answers go to a review list, but nobody reviews them automatically.
- **Drug names:** Claude named the drug for about 3,600 recalls. In the evaluation, 82% were right when salts are ignored, on the same 99 recalls. Its name is only used when Claude is fairly sure and the drug is known to exist, which catches most wrong answers but not all.
- **Ask the data:** the chatbot got 17 of 18 test questions right, but the developer wrote those questions and fixed the prompt after seeing the first results. Real questions are looser. Every answer shows its SQL so it can be checked, and the first live question did come back wrong before a fix.

The fresh hand labels in issue #47 are meant to give honest scores on recalls nothing was tuned on.

## How far the findings go

- **Shortages after a recall are rare.** About 1.3% of drugs recalled since 2020 (45 of 3,421) were followed within a year by a shortage of the same drug. With so few, every rate here has a wide range.
- **Followed doesn't mean caused.** Many of the 45 are drugs that are short again and again, like fentanyl, atropine and rocuronium. A recall of a fragile drug and a later shortage can both happen without one causing the other.
- **The signs were chosen by looking at this same data,** so the backtest is optimistic. An earlier version counted recall events instead of drugs and overstated the signal, with Sterility at about 3 times the average and high flags at about 4 times. Counting each drug in each event cut Sterility to 1.4 times and the old high flag to zero. The decision log has the details.
- **Recent recalls haven't had a full year to be followed,** so the rates for the latest year are understated.

## How far the risk flag goes

- **High is a status, not a prediction.** It means the drug is on FDA's shortage list right now, so the recall can make a shortage worse.
- **Watch is a weak signal.** Injectables were followed by a shortage of the same drug 2.1% of the time, against 0.9% for everything else. Most watch flags will never lead to a shortage.
- **The honest test hasn't happened yet.** `risk_log.csv` records each new recall's flag on the day it's given, to check against shortages that come later. It started in October 2026 and needs months before it says anything, and flags before Oct 26, 2026 used the old points.

## Keeping it running

- **It depends on openFDA.** The data checks catch fields that disappear, lists that collapse and stale data, but not a field that quietly changes meaning.
- **One person maintains it.** GitHub pauses the schedule after 60 days without activity in the repo, and the Claude credits are prepaid. The weekly digest warns about both.
- **The data branch keeps one commit,** and run backups last 30 days. Older states of the data can only be rebuilt from the tables' own history, like `recall_versions` and `shortage_snapshots`.
- **The dashboard runs on Streamlit's free tier,** so it can go to sleep when nobody has visited for a while and wake up on the next visit.

## Not medical advice

ShortageSignal is built on public openFDA data for analysis and learning. It isn't for medical or purchasing decisions.
