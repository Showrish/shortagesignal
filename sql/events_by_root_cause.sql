SELECT rc.root_cause, COUNT(DISTINCT r.event_id) AS events, COUNT(*) AS recalls
FROM recalls AS r
INNER JOIN root_causes AS rc ON r.recall_number = rc.recall_number
GROUP BY rc.root_cause
ORDER BY events DESC