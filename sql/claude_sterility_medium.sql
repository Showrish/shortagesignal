SELECT r.recalling_firm, r.reason_for_recall, COUNT(*) AS recalls
FROM recalls AS r
INNER JOIN read_parquet('data/recall_root_causes.parquet') AS t ON t.recall_number = r.recall_number
WHERE t.source = 'claude' AND t.confidence = 'medium' AND t.root_cause = 'Sterility'
GROUP BY r.recalling_firm, r.reason_for_recall
ORDER BY recalls DESC