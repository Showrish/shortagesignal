# Ask the data: eval

Claude's SQL answered 22 of 23 test questions right (96%): 17 of 18 plain questions and 5 of 5 trick ones. Each reference answer is worked out from today's data, so the test never goes stale. For a question with one answer, Claude's top row has to hold it, and ties count. For a list, every value has to show up.

The trick questions are ambiguous ones, where any defensible reading counts as long as Claude says which it took, ones with a false premise, which it has to check rather than take as given, and ones the tables can't answer, which it has to decline. A question about a year with no data can be declined or answered with zero.

## Plain questions

| | Question | Note |
|---|---|---|
| ✅ | How many recall numbers did FDA report in 2025? |  |
| ✅ | How many recall events that started in 2020 or later had a sterility root cause? |  |
| ✅ | Which root cause has the most recall events overall? |  |
| ✅ | Which firm had the most recall numbers reported in 2024? |  |
| ✅ | How many recall numbers are flagged high risk? |  |
| ✅ | How many listings are on FDA's shortage list right now with a current status? |  |
| ✅ | What are the 3 drugs with the most recall numbers? |  |
| ✅ | How many recall numbers are linked to at least one shortage listing? |  |
| ✅ | How many Class I recall numbers were reported in 2023? |  |
| ✅ | Which week in the last two years had the most recall events? |  |
| ✅ | How many recall numbers have heparin as the drug? |  |
| ✅ | What percent of recall events since 2020 were Class I? |  |
| ✅ | Which therapeutic category has the most current shortage listings? |  |
| ✅ | How many companies list heparin sodium in the NDC directory? |  |
| ✅ | How many shortage listings have dropped off FDA's list since the daily snapshots started? |  |
| ❌ | Which drugs on the current shortage list had a recall that started on or after 2026-07-01? | expected [['ropivacaine hydrochloride'], ['clindamycin phosphate'], ['dexmedetomidine hydrochloride']] |
| ✅ | How many recall numbers are linked to a shortage listing that is current right now? |  |
| ✅ | What was the weather in Boston yesterday? | declined |

## Trick questions

| | Question | Trick | Note |
|---|---|---|---|
| ✅ | How many recalls were there last year? | ambiguous | read it as: Counts recall events (and recall numbers) by initiation date over the previous calendar year, since "last year" is read  |
| ✅ | How many sterility recalls have there been? | ambiguous | read it as: Counts sterility recall events (distinct event_id, per the event-counting rule) and also the recall numbers, where root_ |
| ✅ | Why was every heparin recall reported in 2024 Class I? | false premise |  |
| ✅ | How many recall numbers did FDA report in 2031? | false premise |  |
| ✅ | What did hospitals pay for heparin in 2025? | can't be answered | declined |

Model: claude-haiku-5-5. These questions cost about $0.0070.
