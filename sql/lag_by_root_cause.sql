-- For each root cause: how many drugs recalled since 2020 were followed within a year by a
-- shortage of that same drug that FDA still lists, and the median number of days it took.
--
-- The unit is one drug in one recall event. A pharmacy recalling 298 products that cover
-- 40 drugs counts as 40, not 298 (that would be one decision counted 298 times) and not 1
-- (that would ask whether anything in the batch went short, which is too loose). A shortage
-- happens to a drug, so the question is whether this drug went short after this recall.
-- Recalls whose drug couldn't be named are left out, since there's no drug to follow.
WITH units AS (
    SELECT k.event_id, k.drug_key,
           MIN(TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d'))::DATE AS recall_date,
           MODE(k.root_cause) AS root_cause
    FROM recall_risk AS k
    INNER JOIN recalls AS r ON r.recall_number = k.recall_number
    WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
    GROUP BY k.event_id, k.drug_key
),
followed AS (
    -- the first shortage of the same drug posted within a year after the recall. Links only
    -- join a recall to shortages of its own drug, by package, product, drug and firm, or drug.
    SELECT u.event_id, u.drug_key,
           MIN(TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y'))::DATE AS first_posted
    FROM units AS u
    INNER JOIN recall_risk AS k ON k.event_id = u.event_id AND k.drug_key = u.drug_key
    INNER JOIN links AS l ON l.recall_number = k.recall_number
    WHERE l.shortage_list_type = 'shortage'
      AND TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE
          BETWEEN u.recall_date AND u.recall_date + INTERVAL 365 DAY
    GROUP BY u.event_id, u.drug_key
)
SELECT u.root_cause,
       COUNT(*) AS recalled_drugs,
       COUNT(f.event_id) AS followed,
       ROUND(100.0 * COUNT(f.event_id) / COUNT(*), 1) AS pct_followed,
       MEDIAN(DATE_DIFF('day', u.recall_date, f.first_posted)) AS median_days
FROM units AS u
LEFT JOIN followed AS f ON f.event_id = u.event_id AND f.drug_key = u.drug_key
WHERE u.recall_date >= DATE '2020-01-01'   -- older recalls can't be followed by shortages still listed today
GROUP BY u.root_cause
ORDER BY pct_followed DESC
