# ADR-001. Entrada y almacenamiento

**Contexto:** se reciben cartas escaneadas y XML de proveedores externos, en ocasiones de varios MB, que deben conservarse 5 años junto con el estado de cada expediente.

**Decisión:** API Gateway con autenticación de Cognito entrega URLs prefirmadas; los archivos se almacenan en S3 (`raw/`), EventBridge inicia el flujo al llegar `manifest.json` y DynamoDB registra el estado.

| Alternativa | Costo x1 mensual | Riesgo |
| --- | --- | --- |
| URLs prefirmadas a S3 (elegida) | Menos de 1 USD | La URL vence a los 15 minutos; el proveedor debe solicitar una nueva |
| AWS Transfer Family (SFTP) | 220 USD aproximadamente (0.30 USD por hora) | Costo fijo elevado y administración de credenciales SFTP por proveedor |
| Carga en el cuerpo de la API y almacenamiento en DynamoDB | 1 USD aproximadamente | Límite de 10 MB en API Gateway y de 400 KB por ítem; una carta escaneada no cabe |

**Consecuencias:** costo cercano a cero y archivos que no transitan por Lambda. El proveedor realiza dos pasos (cargar y enviar). Se deben vigilar expedientes sin manifest, que expiran por TTL.

**Condición de cambio:** con más de 50 expedientes por minuto sostenidos se incorporará una cola SQS entre EventBridge y Step Functions; con más de 1,000 archivos diarios de un mismo proveedor se evaluará SFTP.

**Fecha y responsable:** 17 de noviembre de 2026, Yair Rodríguez (EQ01).

x1 = 500 expedientes al mes. Precios de lista de us-east-2, aproximados.
