# Fase 5 — Roles por persona y mínimo privilegio

- Fecha: 2026-11-18T18:49:12Z · Región: us-east-2 · Stack: `cn-eq01-roles` · Plantilla: `infra/fase5-roles.yaml`
- Roles: `cn-eq01-persona-duenio-datos`, `cn-eq01-persona-ingeniero`, `cn-eq01-persona-analista`, `cn-eq01-persona-auditor`
- Cada prueba asume el rol con `sts assume-role` y hace una llamada real de solo lectura.

## Pruebas reales

| Persona | Acción | Esperado | Obtenido | ¿Coincide? |
|---|---|---|---|---|
| Analista | Consulta Athena sobre curated (Q3, Parquet) | PERMITIDO | PERMITIDO | ✅ |
| Analista | Listar raw/ en S3 | DENEGADO | DENEGADO | ✅ |
| Analista | Leer una carta en raw/expedientes/ | DENEGADO | DENEGADO | ✅ |
| Analista | Consulta Athena sobre raw (catalogo_se_raw) | DENEGADO | DENEGADO | ✅ |
| Analista | Leer la tabla DynamoDB | DENEGADO | DENEGADO | ✅ |
| Ingeniero | Leer un resultado en raw/resultados/ | PERMITIDO | PERMITIDO | ✅ |
| Ingeniero | Ver ejecuciones de Step Functions | PERMITIDO | PERMITIDO | ✅ |
| Ingeniero | Leer una carta original en raw/expedientes/ | DENEGADO | DENEGADO | ✅ |
| Ingeniero | Listar roles IAM | DENEGADO | DENEGADO | ✅ |
| Auditor | Ver cifrado del bucket | PERMITIDO | PERMITIDO | ✅ |
| Auditor | Ver ciclo de vida del bucket | PERMITIDO | PERMITIDO | ✅ |
| Auditor | Leer eventos de CloudTrail | PERMITIDO | PERMITIDO | ✅ |
| Auditor | Leer un archivo de curated/ | DENEGADO | DENEGADO | ✅ |
| Dueño de datos | Leer una carta original | PERMITIDO | PERMITIDO | ✅ |
| Dueño de datos | Leer catálogo raw | PERMITIDO | PERMITIDO | ✅ |
| Dueño de datos | Listar roles IAM | DENEGADO | DENEGADO | ✅ |

## Acciones destructivas (simulador de IAM, no se ejecutan)

| Persona | Acción | Recurso | Decisión | ¿Coincide? |
|---|---|---|---|---|
| Dueño de datos | `s3:DeleteObject` | `s3://lago/raw/expedientes/x` | explicitDeny | ✅ |
| Dueño de datos | `s3:PutBucketPolicy` | `s3://lago` | explicitDeny | ✅ |
| Ingeniero | `s3:PutObject` | `s3://lago/curated/x` | allowed | ✅ |
| Ingeniero | `kms:ScheduleKeyDeletion` | `arn:aws:kms:us-east-2:<ACCOUNT_ID>:key/<KMS_KEY_ID>` | explicitDeny | ✅ |
| Analista | `s3:GetObject` | `s3://lago/curated/x` | allowed | ✅ |
| Analista | `s3:GetObject` | `s3://lago/raw/x` | explicitDeny | ✅ |
| Auditor | `s3:PutObject` | `s3://lago/raw/x` | explicitDeny | ✅ |
| Auditor | `s3:GetObject` | `s3://lago/curated/x` | explicitDeny | ✅ |
