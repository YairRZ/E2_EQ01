# Fase 3 — Resultado (2026-11-18T06:10:51Z)

Reproceso de los 30 expedientes por EventBridge → Step Functions (CFDI ‖ Textract → Bedrock → firma) → motor de reglas FVR → revisión humana.

- Decisión correcta: **29/30** (96 %)
- Reglas exactas: **29/30** (96 %)
- Ejecuciones de Step Functions desde 2026-11-18T06:10:51Z: {'SUCCEEDED': 29, 'RUNNING': 1}
- Mensajes en la DLQ: 0
- Modelo que estructuró la carta: {'us.anthropic.claude-haiku-4-5-20251001-v1:0': 30}

Detalle por expediente: `evidencias/precision_pipeline.md`.
Revisión humana pendiente: `bash scripts/fase3_revisar.sh`
