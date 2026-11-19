# Fase 2 — Resultado (2026-11-18T02:50:44Z)

- Stack: `cn-eq01-ingesta` en `us-east-2`
- API: `https://<API_ID>.execute-api.us-east-2.amazonaws.com`
- Máquina: `arn:aws:states:us-east-2:<ACCOUNT_ID>:stateMachine:cn-eq01-ingesta`
- DLQ: `https://sqs.us-east-2.amazonaws.com/<ACCOUNT_ID>/cn-eq01-ingesta-dlq`

## Respuestas de la API

| Expediente | HTTP | Mensaje |
| --- | --- | --- |
| EXP-2026-0001 | 202 | Expediente en cola de validación |
| EXP-2026-0002 | 202 | Expediente en cola de validación |
| EXP-2026-0003 | 202 | Expediente en cola de validación |
| EXP-2026-0001 (duplicado) | 202 | Expediente en cola de validación |

## Ejecuciones y estado en DynamoDB

| Expediente | Ejecución | Estado |
| --- | --- | --- |
| EXP-2026-0001 | SUCCEEDED | EN_PROCESO |
| EXP-2026-0002 | SUCCEEDED | EN_PROCESO |
| EXP-2026-0003 | SUCCEEDED | EN_PROCESO |
| EXP-2026-0001 duplicado | SUCCEEDED (DUPLICADO_RECHAZADO) | EN_PROCESO |

## DLQ: **0** mensajes (visibles + en vuelo)

La API respondió 202 y el flujo siguió aparte. El segundo manifest del primer expediente
no volvió a leer el CFDI: la ejecución terminó en verde con `DUPLICADO_RECHAZADO`
y el estado sigue en `EN_PROCESO`.

Capturas: `08_eventbridge_regla.png`, `09_api_202.png`, `10_dlq_vacia.png`, `03_dynamodb_items.png`.
