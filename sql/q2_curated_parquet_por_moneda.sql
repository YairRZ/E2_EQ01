-- Q2 · curated/ (Parquet): la misma pregunta que Q1; Athena lee solo las columnas moneda y subtotal
SELECT moneda,
       COUNT(*)            AS expedientes,
       SUM(subtotal)       AS subtotal,
       SUM(subtotal_mxn)   AS subtotal_mxn
FROM {db}.expedientes
GROUP BY moneda
ORDER BY moneda
