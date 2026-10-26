-- Every recalled drug that was followed within a year by a shortage of the same drug, with
-- how many days it took, soonest first. The unit is one drug in one recall event, the same
-- as in lag_by_root_cause.sql.
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
SELECT u.event_id, u.drug_key, u.root_cause, u.recall_date, f.first_posted,
       DATE_DIFF('day', u.recall_date, f.first_posted) AS days
FROM units AS u
INNER JOIN followed AS f ON f.event_id = u.event_id AND f.drug_key = u.drug_key
WHERE u.recall_date >= DATE '2020-01-01'
ORDER BY days
