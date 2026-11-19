# Precisión del pipeline contra esperado.csv

- Decisión correcta: **29/30** (96 %)
- Reglas exactas: **29/30** (96 %)
- Ejecuciones de Step Functions desde 2026-11-18T06:10:51Z: {'SUCCEEDED': 29, 'RUNNING': 1}
- Mensajes en la DLQ: 0
- Modelo que estructuró la carta: {'us.anthropic.claude-haiku-4-5-20251001-v1:0': 30}

| Expediente | Caso | Formato | Decisión esperada | Decisión del motor | Estado actual | ¿Coincide? | Reglas esperadas | Reglas disparadas | ¿Coinciden? | Firma |
|---|---|---|---|---|---|---|---|---|---|---|
| EXP-2026-0001 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0002 | ok | jpg | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0003 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0004 | ok_usd | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0005 | iva_incluido | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-AMT-001, FVR-AMT-002, FVR-REC-001 | FVR-AMT-001, FVR-AMT-002, FVR-REC-001 | ✅ | PRESENTE |
| EXP-2026-0006 | monto_anual | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-AMT-002, FVR-REC-001 | FVR-AMT-002, FVR-REC-001 | ✅ | PRESENTE |
| EXP-2026-0007 | codigo_invalido | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-CAT-001 | FVR-CAT-001 | ✅ | PRESENTE |
| EXP-2026-0008 | proporcion_mayor_1 | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PCT-001 | FVR-PCT-001 | ✅ | PRESENTE |
| EXP-2026-0009 | proporcion_decimales | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PCT-002 | FVR-PCT-002 | ✅ | PRESENTE |
| EXP-2026-0010 | fecha_lejana | jpg | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-DAT-002 | FVR-DAT-002, FVR-PRE-003 | ❌ | PRESENTE |
| EXP-2026-0011 | sin_firma | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-FRM-003 | FVR-FRM-003 | ✅ | AUSENTE |
| EXP-2026-0012 | firma_dudosa | pdf | REVISION_HUMANA | OBSERVACIONES | OBSERVACIONES | ❌ | FVR-FRM-003 | FVR-FRM-003 | ✅ | AUSENTE |
| EXP-2026-0013 | usd_sin_homologar | jpg | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-AMT-003, FVR-REC-001 | FVR-AMT-003, FVR-REC-001 | ✅ | PRESENTE |
| EXP-2026-0014 | rfc_distinto | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PRE-004 | FVR-PRE-004 | ✅ | PRESENTE |
| EXP-2026-0015 | proporcion_decimales | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PCT-002 | FVR-PCT-002 | ✅ | PRESENTE |
| EXP-2026-0016 | rfc_distinto | jpg | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PRE-004 | FVR-PRE-004 | ✅ | PRESENTE |
| EXP-2026-0017 | ok | jpg | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0018 | ok | jpg | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0019 | firma_dudosa | pdf | REVISION_HUMANA | REVISION_HUMANA | REVISION_HUMANA | ✅ | FVR-FRM-003 | FVR-FRM-003 | ✅ | DUDOSA |
| EXP-2026-0020 | usd_sin_homologar | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-AMT-003, FVR-REC-001 | FVR-AMT-003, FVR-REC-001 | ✅ | PRESENTE |
| EXP-2026-0021 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0022 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0023 | rfc_distinto | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-PRE-004 | FVR-PRE-004 | ✅ | PRESENTE |
| EXP-2026-0024 | iva_incluido | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-AMT-001, FVR-AMT-002, FVR-REC-001 | FVR-AMT-001, FVR-AMT-002, FVR-REC-001 | ✅ | PRESENTE |
| EXP-2026-0025 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0026 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0027 | ok | jpg | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0028 | ok_usd | jpg | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0029 | ok | pdf | VALIDADO | VALIDADO | VALIDADO | ✅ | — | — | ✅ | PRESENTE |
| EXP-2026-0030 | fecha_lejana | pdf | OBSERVACIONES | OBSERVACIONES | OBSERVACIONES | ✅ | FVR-DAT-002 | FVR-DAT-002 | ✅ | PRESENTE |
