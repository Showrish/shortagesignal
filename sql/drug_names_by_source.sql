SELECT id_source, COUNT(*) AS recalls
FROM recall_drugs
GROUP BY id_source
ORDER BY recalls DESC