-- Q3 · curated/ con poda de particiones: monto facturado por proveedor en octubre de 2026 (solo lee anio=2026/mes=10)
SELECT e.proveedor_rfc,
       e.proveedor_nombre,
       COUNT(DISTINCT e.expediente_id)  AS expedientes,
       COUNT(*)                         AS conceptos,
       SUM(c.importe_mxn)               AS monto_mxn
FROM {db}.expedientes e
JOIN {db}.conceptos c
  ON c.expediente_id = e.expediente_id AND c.anio = e.anio AND c.mes = e.mes
WHERE e.anio = 2026 AND e.mes = 10
GROUP BY e.proveedor_rfc, e.proveedor_nombre
ORDER BY monto_mxn DESC
