# ADR-003. Formato de la zona curated

**Contexto:** el analista consulta con Athena decisiones, conceptos y hallazgos por periodo; Athena cobra por bytes escaneados y los resultados crudos del motor están en JSON anidado.

**Decisión:** el job de Glue `cn-eq01-curar` escribe Parquet con compresión Snappy, particionado por `anio/mes`, en las tablas `expedientes`, `conceptos`, `hallazgos` y `catalogo_se`, con proyección de particiones en Athena.

| Alternativa | Costo x1 a 12 meses | Riesgo |
| --- | --- | --- |
| Parquet particionado por `anio/mes` (elegida) | Glue Flex 17 USD; Athena y S3 menos de 1 USD | Archivos pequeños por partición; el job reescribe la partición del mes |
| Consultar el JSON de `raw/` directamente | 0 USD de Glue; Athena menos de 1 USD hoy, pero escanea 26 veces más bytes (21,326 contra 824 en Q1 y Q2) | El analista leería `raw/` con datos personales; el costo de Athena crece con el histórico de 5 años |
| Apache Iceberg en curated | Glue Flex 25 USD aproximadamente, por compactación y mantenimiento | Mayor complejidad operativa para un volumen que no requiere actualizaciones por registro |

**Consecuencias:** se separan los datos personales de la zona de negocio y Athena lee solo las columnas y particiones consultadas (Q3 escaneó 966 bytes). Se pierde la capacidad de actualizar un registro sin reescribir la partición. Se debe vigilar el número de archivos por partición.

**Condición de cambio:** si una partición mensual supera 1,000 archivos o el negocio exige borrar o corregir registros individuales (por ejemplo, por una solicitud de cancelación de datos personales), se migrará curated a Iceberg.

**Fecha y responsable:** 18 de noviembre de 2026, Yair Rodríguez (EQ01).

x1 = 500 expedientes al mes. Glue Flex a 0.29 USD por DPU-hora; Athena a 5 USD por TB con mínimo de 10 MB por consulta.
