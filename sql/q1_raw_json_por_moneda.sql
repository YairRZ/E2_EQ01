-- Q1 · raw/ (JSON): expedientes y subtotal por moneda, leyendo los CFDI sin curar
SELECT moneda,
       COUNT(*)                                  AS expedientes,
       SUM(CAST(subtotal AS decimal(18,2)))      AS subtotal
FROM {db}.cfdi_raw
GROUP BY moneda
ORDER BY moneda
