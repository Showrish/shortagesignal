-- How strong is each sign, counting each drug in each recall event once? For each group:
-- recalled drugs, how many were followed within a year by a shortage of the same drug, the
-- rate with its 95% range (a Wilson interval), and the lift over the average. The ranges
-- matter: there are only about 45 shortages in all, so small groups swing a lot by chance.
-- Splitting by period checks whether a sign holds in both halves of the data.
WITH units AS (
    SELECT k.event_id, k.drug_key,
           MIN(TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d'))::DATE AS recall_date,
           MODE(k.root_cause) AS root_cause,
           BOOL_OR(k.injectable) AS injectable
    FROM recall_risk AS k
    INNER JOIN recalls AS r ON r.recall_number = k.recall_number
    WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
    GROUP BY k.event_id, k.drug_key
),
followed AS (
    SELECT DISTINCT u.event_id, u.drug_key
    FROM units AS u
    INNER JOIN recall_risk AS k ON k.event_id = u.event_id AND k.drug_key = u.drug_key
    INNER JOIN links AS l ON l.recall_number = k.recall_number
    WHERE l.shortage_list_type = 'shortage'
      AND TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE
          BETWEEN u.recall_date AND u.recall_date + INTERVAL 365 DAY
),
scored AS (
    SELECT f.event_id IS NOT NULL AS was_followed,
           CASE WHEN u.root_cause = 'Sterility' THEN 'sterility' ELSE 'other cause' END AS cause,
           CASE WHEN u.injectable THEN 'injectable' ELSE 'not injectable' END AS form,
           CASE WHEN u.recall_date < DATE '2023-01-01' THEN '2020-22' ELSE '2023 on' END AS period
    FROM units AS u
    LEFT JOIN followed AS f ON f.event_id = u.event_id AND f.drug_key = u.drug_key
    WHERE u.recall_date >= DATE '2020-01-01'
),
groups AS (
    SELECT '1 all' AS split, 'all recalled drugs' AS segment, was_followed FROM scored
    UNION ALL SELECT '2 cause and form', cause || ', ' || form, was_followed FROM scored
    UNION ALL SELECT '3 form by period', form || ', ' || period, was_followed FROM scored
    UNION ALL SELECT '4 cause by period', cause || ', ' || period, was_followed FROM scored
),
counts AS (
    SELECT split, segment, COUNT(*)::DOUBLE AS n,
           (COUNT(*) FILTER (WHERE was_followed))::DOUBLE AS x
    FROM groups
    GROUP BY split, segment
),
overall AS (SELECT x / n AS rate FROM counts WHERE split = '1 all')
SELECT c.split, c.segment, c.n::BIGINT AS recalled_drugs, c.x::BIGINT AS followed,
       ROUND(100 * c.x / c.n, 1) AS pct,
       ROUND(100 * ((c.x / c.n + 1.9208 / c.n)
             - 1.96 * sqrt((c.x / c.n) * (1 - c.x / c.n) / c.n + 0.9604 / (c.n * c.n)))
             / (1 + 3.8416 / c.n), 1) AS pct_low,
       ROUND(100 * ((c.x / c.n + 1.9208 / c.n)
             + 1.96 * sqrt((c.x / c.n) * (1 - c.x / c.n) / c.n + 0.9604 / (c.n * c.n)))
             / (1 + 3.8416 / c.n), 1) AS pct_high,
       ROUND((c.x / c.n) / o.rate, 1) AS lift
FROM counts AS c, overall AS o
ORDER BY c.split, c.segment
