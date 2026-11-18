# Fase 1 — Resultado (2026-11-18T02:46:11Z)

- Stack: `cn-eq01-base` en `us-east-2`
- Bucket del lago: `cn-eq01-lago-143094436742-us-east-2`
- Tabla DynamoDB: `cn-eq01-expedientes` · Base de Glue: `cn_eq01` · Workgroup de Athena: `cn-eq01`

## Capas del lago
```
                           PRE athena-results/
                           PRE curated/
                           PRE raw/
```

## Consulta de prueba en Athena
```sql
SELECT grupo, COUNT(*) AS codigos FROM cn_eq01.catalogo_se_raw GROUP BY grupo ORDER BY codigos DESC
```
- Estado: **SUCCEEDED** · Bytes escaneados: **65029** · Tiempo de motor: 456 ms
- Athena cobra mínimo 10 MB por consulta: a 5 USD/TB esta consulta cuesta ~0.00005 USD.

```
grupo | codigos
Grupo J: General | 187
Grupo E: Mecánico | 80
Grupo I: Instrumentación | 80
Grupo A:Perforación, servicios y equipo | 79
Grupo F: Tuberías | 60
Grupo H: Eléctrico | 58
Grupo C: Estructura | 44
Grupo B: Civil | 27
Grupo G: Aislamiento y Recubrimientos | 18
Grupo D: Calentamiento, Ventilación y Aire Acondicionado | 9
Grupo X:Explotación de gas y petróleo | 6
```

## Cifrado y ciclo de vida
```json
{
    "ServerSideEncryptionConfiguration": {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "aws:kms",
                    "KMSMasterKeyID": "arn:aws:kms:us-east-2:143094436742:key/6dffe94c-929e-4fcc-91f7-b84a13ee0f35"
                },
                "BucketKeyEnabled": true,
                "BlockedEncryptionTypes": {
                    "EncryptionType": [
                        "SSE-C"
                    ]
                }
            }
        ]
    }
}
[
    {
        "id": "raw-expedientes-originales",
        "prefijo": "raw/expedientes/",
        "transiciones": [
            {
                "Days": 30,
                "StorageClass": "STANDARD_IA"
            },
            {
                "Days": 90,
                "StorageClass": "GLACIER_IR"
            }
        ],
        "expira_dias": 1825
    },
    {
        "id": "raw-extracciones-regenerables",
        "prefijo": "raw/extracciones/",
        "transiciones": [
            {
                "Days": 30,
                "StorageClass": "STANDARD_IA"
            }
        ],
        "expira_dias": 365
    },
    {
        "id": "raw-resultados",
        "prefijo": "raw/resultados/",
        "transiciones": [
            {
                "Days": 90,
                "StorageClass": "STANDARD_IA"
            }
        ],
        "expira_dias": 1825
    },
    {
        "id": "curated-intelligent-tiering",
        "prefijo": "curated/",
        "transiciones": [
            {
                "Days": 0,
                "StorageClass": "INTELLIGENT_TIERING"
            }
        ],
        "expira_dias": null
    },
    {
        "id": "athena-results-7-dias",
        "prefijo": "athena-results/",
        "transiciones": null,
        "expira_dias": 7
    },
    {
        "id": "glue-temporal-3-dias",
        "prefijo": "glue-temp/",
        "transiciones": null,
        "expira_dias": 3
    },
    {
        "id": "limpieza-general",
        "prefijo": "",
        "transiciones": null,
        "expira_dias": null
    }
]
```
