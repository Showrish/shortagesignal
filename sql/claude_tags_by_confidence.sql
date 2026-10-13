SELECT confidence, root_cause, COUNT(*) AS recalls
FROM read_parquet('data/recall_root_causes.parquet')
WHERE source = 'claude'
GROUP BY confidence, root_cause
ORDER BY recalls DESC