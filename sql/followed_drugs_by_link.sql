-- The recalled drugs since 2020 that were followed within a year by a shortage of the same
-- drug, one row per drug: how many recall events it was followed in, its root causes, and
-- the strongest link behind it. A package or product link means the same NDC, drug and firm
-- means the same company, and drug only means any company, the loosest kind, where a few
-- could be coincidence. Repeat drugs and drug-only links both make the signal weaker.
WITH causes AS (
    -- each drug in each recall event's most common root cause. A tie goes to the cause that
    -- comes first A to Z, so the same data always gives the same answer, where MODE picked
    -- among tied causes at random and a rerun could move a drug from one cause to another.
    SELECT event_id, drug_key, first(root_cause ORDER BY n DESC, root_cause) AS root_cause
    FROM (
        SELECT k.event_id, k.drug_key, k.root_cause, COUNT(*) AS n
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
        GROUP BY k.event_id, k.drug_key, k.root_cause
    )
    GROUP BY event_id, drug_key
),
units AS (
    SELECT k.event_id, k.drug_key,
           MIN(TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d'))::DATE AS recall_date,
           any_value(c.root_cause) AS root_cause,
           BOOL_OR(k.injectable) AS injectable
    FROM recall_risk AS k
    INNER JOIN recalls AS r ON r.recall_number = k.recall_number
    INNER JOIN causes AS c ON c.event_id = k.event_id AND c.drug_key = k.drug_key
    WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
    GROUP BY k.event_id, k.drug_key
),
in_window AS (
    SELECT u.event_id, u.drug_key, u.root_cause, u.injectable, l.match_level,
           DATE_DIFF('day', u.recall_date, TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE) AS days
    FROM units AS u
    INNER JOIN recall_risk AS k ON k.event_id = u.event_id AND k.drug_key = u.drug_key
    INNER JOIN links AS l ON l.recall_number = k.recall_number
    WHERE l.shortage_list_type = 'shortage'
      AND u.recall_date >= DATE '2020-01-01'
      AND TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE
          BETWEEN u.recall_date AND u.recall_date + INTERVAL 365 DAY
)
SELECT drug_key AS drug,
       COUNT(DISTINCT event_id) AS recall_events,
       string_agg(DISTINCT root_cause, ', ') AS root_causes,
       BOOL_OR(injectable) AS injectable,
       CASE MIN(CASE match_level WHEN 'package' THEN 1 WHEN 'product' THEN 2
                                 WHEN 'drug_and_firm' THEN 3 ELSE 4 END)
            WHEN 1 THEN 'package' WHEN 2 THEN 'product' WHEN 3 THEN 'drug and firm'
            ELSE 'drug only' END AS strongest_link,
       MIN(days) AS fewest_days
FROM in_window
GROUP BY drug_key
ORDER BY recall_events DESC, drug
