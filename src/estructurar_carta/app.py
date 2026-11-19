"""Estructura la carta: Textract (ya ejecutado por Step Functions) -> texto/tablas/firmas -> Bedrock -> JSON.

Principio de diseño: la IA NO aprueba. Bedrock sólo convierte texto libre en campos con un esquema JSON fijo
(tool use con toolChoice obligatorio). Las decisiones las toma el motor de reglas determinístico.
Para auditoría guardamos el modelo, la versión del prompt, los tokens y la respuesta cruda.
"""
import json
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

S3 = boto3.client("s3")
TEXTRACT = boto3.client("textract")
BEDROCK = boto3.client("bedrock-runtime", config=Config(retries={"max_attempts": 4, "mode": "adaptive"}))
MODELO = os.environ["MODELO_BEDROCK"]
MODELO_RESPALDO = os.environ.get("MODELO_RESPALDO", "")
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")
PROMPT_VERSION = "carta-cn-v2"

ESQUEMA = {
    "type": "object",
    "properties": {
        "proveedor_nombre": {"type": "string"},
        "proveedor_rfc": {"type": "string", "description": "RFC del proveedor tal como aparece, sin espacios"},
        "representante_legal": {"type": "string"},
        "destinatario": {"type": "string", "description": "Empresa a la que va dirigida la carta (línea antes de 'Presente')"},
        "contrato": {"type": "string"},
        "bloque": {"type": "string"},
        "fecha_emision": {"type": "string", "description": "Fecha de la carta en formato YYYY-MM-DD"},
        "anio_fiscal": {"type": "integer"},
        "uuid_cfdi": {"type": "string", "description": "Folio fiscal (UUID) de la factura mencionada, en mayúsculas"},
        "domicilio": {"type": "string"},
        "email_contacto": {"type": "string"},
        "telefono_contacto": {"type": "string"},
        "instrumento_publico": {"type": "string", "description": "Escritura y notario"},
        "conceptos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo_se": {"type": "string",
                                  "description": "Código del catálogo SE: una letra mayúscula seguida de 4 dígitos (ej. I0200)"},
                    "descripcion": {"type": "string"},
                    "proporcion_texto": {"type": "string",
                                         "description": "Proporción de contenido nacional EXACTAMENTE como está escrita, "
                                                        "conservando todos los decimales (ej. '0.500', '0.5', '1')"},
                    "monto": {"type": "number", "description": "Monto en pesos, sin signos ni comas"},
                },
                "required": ["codigo_se", "descripcion", "proporcion_texto", "monto"],
            },
        },
        "total_declarado": {"type": "number", "description": "Total de la tabla; 0 si no aparece"},
        "declaraciones": {
            "type": "object",
            "properties": {k: {"type": "boolean"} for k in ("verificacion", "conservacion", "sanciones", "punto_19")},
        },
        "firmante_nombre": {"type": "string", "description": "Nombre impreso bajo la firma"},
        "confianza_extraccion": {"type": "string", "enum": ["alta", "media", "baja"]},
        "notas": {"type": "string"},
    },
    "required": ["proveedor_rfc", "destinatario", "representante_legal", "instrumento_publico", "fecha_emision",
                 "anio_fiscal", "uuid_cfdi", "conceptos", "confianza_extraccion"],
}

SISTEMA = (
    "Eres un extractor de datos de Cartas de Contenido Nacional mexicanas. Recibes el texto OCR y las tablas de una "
    "carta. Devuelve los campos con la herramienta registrar_carta. Reglas: no inventes datos; si un campo no aparece, "
    "deja una cadena vacía; copia la proporción de contenido nacional exactamente como está escrita; los montos van "
    "como número sin comas; el destinatario es la empresa a la que va dirigida la carta (aparece antes de 'Presente'); "
    "el código SE empieza con una letra: si el OCR muestra un dígito en esa posición, cópialo tal cual; no evalúes si "
    "la carta es correcta, sólo extrae."
)


class TextractIncompleto(Exception):
    pass


class BedrockOcupado(Exception):
    """Saturación temporal de Bedrock: Step Functions reintenta con espera creciente."""


def bloques_textract(job_id):
    bloques, token, estado = [], None, None
    while True:
        kw = {"JobId": job_id, "MaxResults": 1000}
        if token:
            kw["NextToken"] = token
        r = TEXTRACT.get_document_analysis(**kw)
        estado = r["JobStatus"]
        bloques += r.get("Blocks", [])
        token = r.get("NextToken")
        if not token:
            break
    if estado not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
        raise TextractIncompleto(estado)
    return bloques


def resumir(bloques):
    por_id = {b["Id"]: b for b in bloques}
    paginas = max([b.get("Page", 1) for b in bloques] or [1])
    lineas = {}
    for b in bloques:
        if b["BlockType"] == "LINE":
            lineas.setdefault(b.get("Page", 1), []).append(b["Text"])

    def texto_celda(celda):
        palabras = []
        for rel in celda.get("Relationships", []):
            if rel["Type"] == "CHILD":
                palabras += [por_id[i].get("Text", "") for i in rel["Ids"] if por_id.get(i, {}).get("BlockType") == "WORD"]
        return " ".join(palabras)

    tablas = []
    for b in bloques:
        if b["BlockType"] != "TABLE":
            continue
        celdas = [por_id[i] for rel in b.get("Relationships", []) if rel["Type"] == "CHILD" for i in rel["Ids"]
                  if por_id.get(i, {}).get("BlockType") == "CELL"]
        filas = {}
        for c in celdas:
            filas.setdefault(c["RowIndex"], {})[c["ColumnIndex"]] = texto_celda(c)
        tablas.append({"pagina": b.get("Page", 1),
                       "filas": [[f[k] for k in sorted(f)] for _, f in sorted(filas.items())]})
    firmas = [{"pagina": b.get("Page", 1), "confianza": round(b.get("Confidence", 0), 2),
               "bbox": {k.lower(): round(v, 4) for k, v in b["Geometry"]["BoundingBox"].items()}}
              for b in bloques if b["BlockType"] == "SIGNATURE"]
    return paginas, lineas, tablas, firmas


def extraer_con_bedrock(paginas, lineas, tablas, modelo=MODELO):
    texto = "\n\n".join(f"--- Página {p} ---\n" + "\n".join(lineas.get(p, [])) for p in range(1, paginas + 1))
    tablas_txt = "\n\n".join(f"Tabla (página {t['pagina']}):\n" + "\n".join(" | ".join(f) for f in t["filas"])
                             for t in tablas)
    kw = {
        "modelId": modelo,
        "system": [{"text": SISTEMA}],
        "messages": [{"role": "user", "content": [{"text": f"TEXTO OCR:\n{texto}\n\nTABLAS:\n{tablas_txt}"}]}],
        "inferenceConfig": {"maxTokens": 2000, "temperature": 0},
        "toolConfig": {"tools": [{"toolSpec": {"name": "registrar_carta",
                                               "description": "Registra los campos extraídos de la carta",
                                               "inputSchema": {"json": ESQUEMA}}}],
                       "toolChoice": {"tool": {"name": "registrar_carta"}}},
    }
    if GUARDRAIL_ID:
        kw["guardrailConfig"] = {"guardrailIdentifier": GUARDRAIL_ID, "guardrailVersion": GUARDRAIL_VERSION}
    t0 = time.time()
    r = BEDROCK.converse(**kw)
    latencia = int((time.time() - t0) * 1000)
    datos = next((c["toolUse"]["input"] for c in r["output"]["message"]["content"] if "toolUse" in c), None)
    meta = {"modelo": modelo, "prompt_version": PROMPT_VERSION, "latencia_ms": latencia,
            "tokens_entrada": r["usage"]["inputTokens"], "tokens_salida": r["usage"]["outputTokens"],
            "stop_reason": r.get("stopReason")}
    return datos, meta


def handler(ev, _ctx):
    exp = ev["expediente"]
    exp_id, bucket = exp["expediente_id"], exp["bucket"]
    bloques = bloques_textract(ev["job_id"])
    S3.put_object(Bucket=bucket, Key=f"raw/extracciones/textract/{exp_id}.json",
                  Body=json.dumps(bloques).encode(), ContentType="application/json")
    paginas, lineas, tablas, firmas = resumir(bloques)
    datos, meta = None, {}
    for modelo in [m for m in (MODELO, MODELO_RESPALDO) if m]:
        try:
            datos, meta = extraer_con_bedrock(paginas, lineas, tablas, modelo)
            break
        except ClientError as e:
            codigo = e.response["Error"]["Code"]
            if codigo in ("ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"):
                raise BedrockOcupado(codigo)  # Step Functions reintenta con backoff
            # Sin acceso al modelo, modelo no disponible o petición inválida: se intenta el de respaldo
            datos, meta = None, {"modelo": modelo, "prompt_version": PROMPT_VERSION, "error": codigo}
    carta = {"extraccion_ok": bool(datos and datos.get("conceptos")), **(datos or {}), "_meta": meta}
    S3.put_object(Bucket=bucket, Key=f"raw/extracciones/carta/{exp_id}.json",
                  Body=json.dumps(carta, ensure_ascii=False).encode(), ContentType="application/json")
    return {"carta": carta, "senales_firma": {"paginas": paginas, "firmas": firmas}}
