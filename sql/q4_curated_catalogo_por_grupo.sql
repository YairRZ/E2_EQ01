-- Q4 · curated/ (Parquet): códigos del catálogo SE por grupo; comparar contra 65,029 bytes de catalogo_se_raw (Fase 1)
SELECT grupo,
       COUNT(*) AS codigos
FROM {db}.catalogo_se
GROUP BY grupo
ORDER BY codigos DESC
