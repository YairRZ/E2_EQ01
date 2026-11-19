# Evidencias

Capturas de pantalla de la consola de AWS (PNG) y reportes generados por los scripts de `scripts/`.

| Archivo | Qué muestra | Punto de la rúbrica |
| --- | --- | --- |
| [01_s3_capas.png](01_s3_capas.png) | Bucket `cn-eq01-lago-…` con `raw/`, `curated/`, `athena-results/` | R1.1 |
| [02_athena_q3_sql.png](02_athena_q3_sql.png) | Consulta Q3 en el workgroup `cn-eq01` | R1.1 |
| [02_athena_q3.png](02_athena_q3.png) | Resultado de Q3: 0.94 KB escaneados gracias a la poda de particiones | R1.1 |
| [03_dynamodb_items.png](03_dynamodb_items.png) | Tabla `cn-eq01-expedientes`: META en `EN_PROCESO` y bitácora `RECIBIDO` con TTL | R1.2 |
| [03b_dynamodb_cifrado_ttl.png](03b_dynamodb_cifrado_ttl.png) | Tabla con CMK de KMS y TTL `expira_en` activo | R1.2, seguridad |
| [04_glue_tablas.png](04_glue_tablas.png) | Catálogo `cn_eq01`: 5 tablas (Parquet curado y JSON crudo) | R1.2 |
| [05_glue_job_ok.png](05_glue_job_ok.png) | Job `cn-eq01-curar` Succeeded: Flex, 2 × G.1X, 4 min 16 s, 0.0886 DPU-h | R1.3 |
| [06_curated_particiones.png](06_curated_particiones.png) | `curated/expedientes/anio=2026/` con `mes=9`, `mes=10`, `mes=11` | R1.3 |
| [07_lifecycle.png](07_lifecycle.png) | Reglas de ciclo de vida por capa (Estándar-IA, Glacier IR, Intelligent-Tiering, vencimiento) | R1.4 |
| [08_eventbridge_regla.png](08_eventbridge_regla.png) | Regla `cn-eq01-ingesta-manifest`: solo `raw/expedientes/*/manifest.json` | Eventos A |
| [09_api_202.png](09_api_202.png) | Terminal: `/enviar` responde 401 sin token y 202 con JWT de Cognito | Eventos B, seguridad |
| [09b_stepfunctions_duplicado.png](09b_stepfunctions_duplicado.png) | Reenvío del mismo expediente: ruta `DuplicadoRechazado` → `FinDuplicado` (idempotencia) | Eventos B |
| [09c_stepfunctions_ejecucion.png](09c_stepfunctions_ejecucion.png) | Detalle de esa ejecución: Standard, 1 s, 6 transiciones | Eventos B |
| [10_dlq_vacia.png](10_dlq_vacia.png) | DLQ `cn-eq01-ingesta-dlq` con 0 mensajes, cifrada con SSE-KMS | Eventos C |
| [11_stepfunctions_ejecuciones.png](11_stepfunctions_ejecuciones.png) | Máquina `cn-eq01-ingesta` (Standard): ejecuciones de la segunda corrida en verde; la primera (1 min 27 s) esperó la revisión humana de EXP-2026-0019 | Eventos D |
| [12_iam_roles.png](12_iam_roles.png) | 9 roles `cn-eq01`, uno por componente, cada uno confiado solo a su servicio (glue, lambda, events, states) | Roles |
| [12b_iam_roles_personas.png](12b_iam_roles_personas.png) | Consola IAM > Roles filtrado por `cn-eq`: 9 roles de servicio y los 4 roles de persona `cn-eq01-persona-*`, confiados solo a la cuenta del proyecto | Roles |
| [13_analista_accessdenied.png](13_analista_accessdenied.png) | Terminal asumiendo `cn-eq01-persona-analista`: lista `curated/` (Parquet por `anio/mes`); AccessDenied por Deny explícito al listar `raw/` y AccessDenied al escribir en `curated/` | Roles |
| [fase1_resultado.md](fase1_resultado.md) | Reporte generado por el script de despliegue | R1.1, R1.4 |
| [fase2_resultado.md](fase2_resultado.md) | Reporte de [`scripts/fase2_probar.sh`](../scripts/fase2_probar.sh): 3 expedientes por la API, ejecuciones en verde, duplicado rechazado y DLQ en 0 | Eventos B, C |
| [fase3_resultado.md](fase3_resultado.md), [precision_pipeline.md](precision_pipeline.md) | Reporte generado por el script: 29/30 decisiones y reglas contra [`esperado.csv`](../datos/expedientes/esperado.csv) con Claude Haiku 4.5 | Validación |
| [fase4_resultado.md](fase4_resultado.md) | Reporte generado por el script: bytes de Q1–Q4 (JSON crudo vs Parquet) | R1.1, R1.3 |
| [fase5_resultado.md](fase5_resultado.md) | Reporte de [`scripts/fase5_desplegar.sh`](../scripts/fase5_desplegar.sh): 16 pruebas reales asumiendo cada rol de persona + 8 acciones destructivas en el simulador de IAM (24/24) | Roles |
