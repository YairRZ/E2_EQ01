# Fase 4 — Resultado (2026-11-18T03:15:36Z)

- Stack: `cn-eq01-curado` en `us-east-2` · Job: `cn-eq01-curar` (Glue 4.0, Flex, 2 × G.1X)
- Ejecución: `jr_37fa3693fc87455c31f33edb7f23ec1df6d2b98d50a09c760de758de92106c4a` → **SUCCEEDED** en 256 s
- Disparo diario: `cn-eq01-curar-diario` (cron 07:00 UTC)

## Capa curated/ (Parquet particionado por anio/mes)
```
14594 curated/catalogo_se/part-00000-a5100a78-c3da-4198-9584-4bf81dc48426-c000.snappy.parquet
3603 curated/conceptos/anio=2026/mes=10/part-00000-edb253e1-70ce-461e-b6aa-507ef4c254e5.c000.snappy.parquet
3265 curated/conceptos/anio=2026/mes=11/part-00000-edb253e1-70ce-461e-b6aa-507ef4c254e5.c000.snappy.parquet
3183 curated/conceptos/anio=2026/mes=9/part-00000-edb253e1-70ce-461e-b6aa-507ef4c254e5.c000.snappy.parquet
0 curated/conceptos_$folder$
6200 curated/expedientes/anio=2026/mes=10/part-00000-aacf5575-fe6e-470c-a546-32f630e1edcd.c000.snappy.parquet
5916 curated/expedientes/anio=2026/mes=11/part-00000-aacf5575-fe6e-470c-a546-32f630e1edcd.c000.snappy.parquet
5951 curated/expedientes/anio=2026/mes=9/part-00000-aacf5575-fe6e-470c-a546-32f630e1edcd.c000.snappy.parquet
0 curated/expedientes_$folder$
```

## Consultas en Athena

### Q1 · raw/ (JSON): expedientes y subtotal por moneda, leyendo los CFDI sin curar

- Archivo: `sql/q1_raw_json_por_moneda.sql` · Estado: **SUCCEEDED** · Bytes escaneados: **21326** · Tiempo: 865 ms · QueryExecutionId: `48271f1b-31d2-48a6-9c38-313fc9cd5eba`

```sql
SELECT moneda,
       COUNT(*)                                  AS expedientes,
       SUM(CAST(subtotal AS decimal(18,2)))      AS subtotal
FROM cn_eq01.cfdi_raw
GROUP BY moneda
ORDER BY moneda
```

```
moneda	expedientes	subtotal	MXN	26	16177664.43	USD	4	88156.80
```

### Q2 · curated/ (Parquet): la misma pregunta que Q1; Athena lee solo las columnas moneda y subtotal

- Archivo: `sql/q2_curated_parquet_por_moneda.sql` · Estado: **SUCCEEDED** · Bytes escaneados: **824** · Tiempo: 475 ms · QueryExecutionId: `2947bde1-6a55-47e0-8bbb-06d019a77cc8`

```sql
SELECT moneda,
       COUNT(*)            AS expedientes,
       SUM(subtotal)       AS subtotal,
       SUM(subtotal_mxn)   AS subtotal_mxn
FROM cn_eq01.expedientes
GROUP BY moneda
ORDER BY moneda
```

```
moneda	expedientes	subtotal	subtotal_mxn	MXN	26	16177664.43	16177664.43	USD	4	88156.80	1664212.47
```

### Q3 · curated/ con poda de particiones: monto facturado por proveedor en octubre de 2026 (solo lee anio=2026/mes=10)

- Archivo: `sql/q3_curated_particion_octubre.sql` · Estado: **SUCCEEDED** · Bytes escaneados: **966** · Tiempo: 713 ms · QueryExecutionId: `8c433c6c-312e-44b8-a92f-0af236938e52`

```sql
SELECT e.proveedor_rfc,
       e.proveedor_nombre,
       COUNT(DISTINCT e.expediente_id)  AS expedientes,
       COUNT(*)                         AS conceptos,
       SUM(c.importe_mxn)               AS monto_mxn
FROM cn_eq01.expedientes e
JOIN cn_eq01.conceptos c
  ON c.expediente_id = e.expediente_id AND c.anio = e.anio AND c.mes = e.mes
WHERE e.anio = 2026 AND e.mes = 10
GROUP BY e.proveedor_rfc, e.proveedor_nombre
ORDER BY monto_mxn DESC
```

```
proveedor_rfc	proveedor_nombre	expedientes	conceptos	monto_mxn	CIS160930RT5	CONSTRUCCIONES INDUSTRIALES DEL SURESTE SA DE CV	3	9	2168470.49	PIN150707HJ4	PERFORACION E INSTRUMENTACION NACIONAL SA DE CV	2	8	1606382.12	MEV190104ZX2	MANTENIMIENTO ELECTRICO VILLAHERMOSA SA DE CV	4	8	1244469.46	SPT180512KL3	SERVICIOS PETROLEROS DEL TROPICO SA DE CV	1	4	972661.41	ITC170823QW8	INGENIERIA Y TUBERIAS DE CAMPECHE SA DE CV	1	4	736913.60	AIR200215MN7	AISLAMIENTOS Y RECUBRIMIENTOS DEL GOLFO SA DE CV	1	1	78484.10
```

### Q4 · curated/ (Parquet): códigos del catálogo SE por grupo; comparar contra 65,029 bytes de catalogo_se_raw (Fase 1)

- Archivo: `sql/q4_curated_catalogo_por_grupo.sql` · Estado: **SUCCEEDED** · Bytes escaneados: **354** · Tiempo: 435 ms · QueryExecutionId: `708237b0-671c-4415-8671-3cd18aeea629`

```sql
SELECT grupo,
       COUNT(*) AS codigos
FROM cn_eq01.catalogo_se
GROUP BY grupo
ORDER BY codigos DESC
```

```
grupo	codigos	Grupo J: General	187	Grupo E: Mecánico	80	Grupo I: Instrumentación	80	Grupo A:Perforación, servicios y equipo	79	Grupo F: Tuberías	60	Grupo H: Eléctrico	58	Grupo C: Estructura	44	Grupo B: Civil	27	Grupo G: Aislamiento y Recubrimientos	18	Grupo D: Calentamiento, Ventilación y Aire Acondicionado	9	Grupo X:Explotación de gas y petróleo	6
```

## Resumen de bytes escaneados

| Consulta | Estado | Bytes |
|---|---|---|
| `sql/q1_raw_json_por_moneda.sql` | SUCCEEDED | 21326 |
| `sql/q2_curated_parquet_por_moneda.sql` | SUCCEEDED | 824 |
| `sql/q3_curated_particion_octubre.sql` | SUCCEEDED | 966 |
| `sql/q4_curated_catalogo_por_grupo.sql` | SUCCEEDED | 354 |

Athena cobra un mínimo de 10 MB por consulta (5 USD por TB): cada consulta cuesta ~0.00005 USD.
