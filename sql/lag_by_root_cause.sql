WITH events AS (
    SELECT r.event_id,
           MIN(TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d'))::DATE AS event_date,
           MODE(rc.root_cause) AS root_cause
    FROM recalls AS r
    INNER JOIN root_causes AS rc ON r.recall_number = rc.recall_number
    GROUP BY r.event_id
),
followed AS (
    SELECT e.event_id,
           MIN(TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y'))::DATE AS first_posted
    FROM events AS e
    INNER JOIN recalls AS r ON r.event_id = e.event_id
    INNER JOIN links AS l ON l.recall_number = r.recall_number
    WHERE l.shortage_list_type = 'shortage'
      AND TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE
          BETWEEN e.event_date AND e.event_date + INTERVAL 365 DAY
    GROUP BY e.event_id
)
SELECT e.root_cause,
       COUNT(*) AS events,
       COUNT(f.event_id) AS followed,
       ROUND(100.0 * COUNT(f.event_id) / COUNT(*), 1) AS pct_followed,
       MEDIAN(DATE_DIFF('day', e.event_date, f.first_posted)) AS median_days
FROM events AS e
LEFT JOIN followed AS f ON f.event_id = e.event_id
WHERE e.event_date >= DATE '2020-01-01'   -- older recalls can't be followed by shortages still listed today
GROUP BY e.root_cause
ORDER BY pct_followed DESC