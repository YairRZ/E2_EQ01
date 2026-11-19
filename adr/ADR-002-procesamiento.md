# ADR-002. Procesamiento

**Contexto:** cada expediente debe leerse, estructurarse y validarse en minutos, con un volumen irregular y sin costo significativo en periodos sin actividad.

**Decisión:** Step Functions orquesta funciones Lambda arm64, Textract y Bedrock (Claude Haiku 4.5, con Amazon Nova Lite de respaldo); Glue Flex transforma los resultados a Parquet una vez al día.

| Alternativa | Costo 12 meses x1 | Costo 12 meses x3 | Riesgo |
| --- | --- | --- | --- |
| Serverless con Step Functions y Lambda (elegida) | 303 USD | 852 USD | El costo crece en proporción a las páginas procesadas por Textract (75 % del total) |
| Contenedor ECS Fargate en operación continua | 460 USD | 1,200 USD | Se paga 24/7 sin actividad; requiere mantenimiento de la imagen |
| EC2 con OCR propio, sin Textract ni Bedrock | 330 USD | 650 USD más horas de analista | Baja precisión en firmas y tablas; mayor carga de revisión humana y mantenimiento del servidor |

| Concepto de la alternativa elegida | x1 mensual (USD) | x3 mensual (USD) |
| --- | --- | --- |
| Textract, 2 páginas por expediente | 18.50 | 55.50 |
| Bedrock, Claude Haiku 4.5 | 3.25 | 9.75 |
| Glue Flex diario | 1.45 | 2.20 |
| KMS, una llave | 1.00 | 1.00 |
| Step Functions, Lambda arm64, API Gateway, CloudWatch Logs y Athena | 0.95 | 2.25 |
| Almacenamiento S3 y DynamoDB | 0.10 | 0.30 |
| **Total mensual** | **25.25** | **71.00** |
| **Total a 12 meses** | **303** | **852** |

**Consecuencias:** pago por uso y ausencia de servidores. Se depende de las cuotas de Textract. Se deben vigilar el costo por expediente y la tasa de revisión humana. En las pruebas, Claude Haiku 4.5 usó unos 2,300 tokens de entrada y 740 de salida por carta (0.006 USD) y acertó 29 de 30 decisiones.

**Condición de cambio:** con más de 20,000 páginas mensuales o un costo superior a 0.10 USD por expediente se negociará el precio de Textract o se evaluará un OCR propio.

**Fecha y responsable:** 17 de noviembre de 2026, Yair Rodríguez (EQ01).

x1 = 500 expedientes al mes; x3 = 1,500. Precios de lista de us-east-2 al 17 de noviembre de 2026.
