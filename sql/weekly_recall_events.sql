-- Recall events and recall numbers per week, by the week FDA reported them.
-- Weeks start on Monday. Weeks with no recalls are filled in with zeros by risk.py,
-- which also leaves out the current week until it's over.
SELECT date_trunc('week', TRY_STRPTIME(report_date, '%Y%m%d'))::DATE AS week,
       COUNT(DISTINCT event_id) AS events,
       COUNT(*) AS recalls
FROM recalls
WHERE TRY_STRPTIME(report_date, '%Y%m%d') IS NOT NULL
GROUP BY 1
ORDER BY 1
