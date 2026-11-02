# How the AI parts were tested

ShortageSignal uses Claude Haiku for three jobs: tagging the root cause when the rules can't, naming the drug when matching can't, and answering questions in the dashboard's Ask the data tab. None of them shipped without a score against answers a person wrote. This page covers how each one was tested, what the scores were, and how far to trust them.

## The test sets

- **The first audit:** 99 random recalls, labeled by hand on Day 7. They became the answer key that the root-cause rules, Claude's prompts and the drug-name checks were tuned on, so scores on them are optimistic.
- **The fresh labels:** 30 recalls labeled blind on Nov 2, 2026, none of them from the first audit, so nothing was tuned on them. They were drawn as 10 tagged by the rules, 10 tagged by Claude and 10 named by Claude, at most one per recall event. The pipeline's answers were frozen when they were drawn, so the score is against exactly what the pipeline said then.
- **The chatbot's test questions:** 18 questions with a reference SQL query each, worked out again on each day's data, so the right answers never go stale.

## Root causes

**The job:** the rules in `sql/root_cause_rules.sql` tag about 99% of recalls (17,868 of 18,047). Claude tags the rest, about 180 recalls. It has to pick one of the 12 categories, which the tool's schema enforces, and say how sure it is. It's asked once per distinct reason text, and the answers are cached. Anything it isn't sure of goes to a review list.

| Test | Rules | Claude |
|---|---|---|
| First audit (tuned on) | 99 of 99 | 97 of 99, tagging every recall on its own |
| Fresh labels | **18 of 20 (90%)** | **5 of 9 (56%)** |

**How to read it:** the first audit never tested Claude on its real job, since the rules tagged every audited recall. The fresh labels did, and the leftovers are hard by nature: reasons that mix several problems or don't name one. Five of 9 has a wide range, roughly 27% to 81%. The rules' 90% (roughly 70% to 97%) is the honest number for them, down from the 100% they were tuned to.

**The disagreements** were mostly judgment calls at the edges of the categories: Other against CGMP twice, and CGMP against Particulates, Labeling against Container defect, Potency against CGMP, and CGMP against Labeling once each. Root-cause labels were left exactly as labeled, since changing judgment calls after seeing the pipeline's answers would bias the score.

**What it means:** Claude tags about 1% of recalls, so its weak spot barely moves the overall tagging. When it's unsure, the recall lands on the weekly review list.

## Drug names

**The job:** matching names the drug for 56% of recalls from NDC codes, FDA's own annotations and the product text. Claude reads the description for the rest. Its name is only used when it's fairly sure and the drug is known to exist, or, for a combination, when every part is. With Claude, 83% of recalls have a drug name.

| Test | Claude, ignoring salts | Matching, ignoring salts |
|---|---|---|
| First audit, 74 recalls with a clear drug (tuned on) | 70 of 74 (95%) alone, before any checks | 48 of 74 (65%) before Claude, 67 of 74 (91%) with Claude |
| Fresh labels | **14 of 15 (93%)** | **9 of 12 (75%)** |

"Ignoring salts" counts fentanyl and fentanyl citrate as the same drug, since recall text often leaves the salt off.

**Two things worth knowing about these numbers:**

- **The fresh drug labels were fixed once, in the open.** Nine of them broke the labeling rules, by giving a brand name instead of the generic, adding a purpose like expectorant, naming a kit with no drug, or making a typo. They were fixed to the rules after the first score, and each fixed row says so. Before the fix, the scores were 10 of 15 for Claude and 8 of 12 for matching. Both versions are kept, in `audit/fresh_labels.md` and `audit/fresh_labels_as_labeled.md`.
- **Accepting combinations was a trade.** Letting Claude name compounded combinations, when every part is a known drug, raised the first audit's score from 82% to 91% and named about 1,300 more recalls. It also let in 2 wrong answers on the first audit, both for Nature-Throid, where Claude listed the hormones on the label instead of thyroid.

**The real misses on the fresh labels were mostly in matching,** not Claude: a store brand accepted as a drug name (cvs), flavor and form words left in a name (menthol flavor cough drop), and an inactive ingredient named instead of the active one (edetate calcium disodium instead of salicylic acid). There were also caffeine dropped from a combination and two combinations left unnamed. They're tracked in issue #60.

## Ask the data

**The job:** Claude writes one read-only SQL query over a locked, in-memory copy of six tables. The app runs it, then Claude answers from the rows it got back, and the SQL is shown under every answer. Queries can only read, return at most 200 rows, and sit behind a passcode with 50 questions a day, on a separate key in a workspace with a $1 monthly limit.

**The test:** each of the 18 questions has a reference query that runs on the day's data. For a question with one answer, Claude's top row has to hold an accepted answer, and ties count. For a list, every value has to show up. One question can't be answered from the tables, and the right answer there is to decline.

**The result:** 17 of 18. The miss is a wording ambiguity: asked which drugs on the shortage list had a recall, Claude listed the shortage list's names, while the reference listed the recall's names.

**How it got there, since that's the useful part:**

1. The first run scored 11 of 16. Two misses were right answers that the scorer rejected, because Claude returned a ranked list with the answer on top. One was a tie, one came from an ambiguous question, and one was a real data quirk, with categories stored as lists. Fixing those gave 16 of 16.
2. The first live question still came back wrong. Asked which drugs on the shortage list were recalled lately, it said none, because Claude matched drug names across the two tables, and FDA's shortage names never equal the cleaned recall names. None of the 16 test questions crossed those two tables. A rule to always go through the links table, and two new test questions that do cross them, gave 17 of 18.

The lesson: **an eval only catches what it asks about.** The test questions were written by the developer, so real questions will do worse, which is why the SQL is always on screen.

## Costs

- **A normal day costs a fraction of a cent.** Each distinct text is asked once and cached, and every run's calls and cost are logged in `run_log.csv`.
- **One-time backfills were the big spend.** About $1.70 of the $5 prepaid had been used by Oct 18, most of it naming drugs for past recalls ($1.57).
- **Each chatbot question costs about 0.05 cents,** and each eval run costs under a cent.

## What these tests can't tell you

- **The samples are small.** There are 30 fresh recalls in all, and only 9 tagged by Claude.
- **One person labeled everything.** There's no second labeler, and some categories have fuzzy edges, like CGMP against Other.
- **The first audit tuned everything,** so only the fresh labels are a fair test, and they're one round.
- **The chatbot's questions came from the developer,** not from real users.

## Run them yourself

```
python -m shortagesignal.tagging eval     # root causes, on the first audit
python -m shortagesignal.extract eval     # drug names, on the first audit
python -m shortagesignal.fresh score      # both, on the fresh labels
python -m shortagesignal.ask eval         # the chatbot's 18 questions, costs under a cent
```

The results are saved in `audit/`: `tagging_results.md`, `extraction_results.md`, `fresh_labels.md` and `ask_eval.md`.
