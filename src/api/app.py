"""API de ingesta (API Gateway HTTP API + autorizador JWT de Cognito).

Rutas:
  POST /expedientes                 -> crea expediente y devuelve URLs prefirmadas (PUT) para carta y CFDI
  POST /expedientes/{id}/enviar     -> verifica que ambos archivos existan y escribe manifest.json (dispara el flujo)
  GET  /expedientes/{id}            -> estado y resultado del expediente (DynamoDB)

El navegador / script sube los archivos DIRECTO a S3 con la URL prefirmada: la Lambda nunca recibe el binario,
así no pagamos por transferir megas a través de Lambda ni chocamos con el límite de 10 MB de API Gateway.
"""
import datetime as dt
import json
import os
import re
import uuid
from decimal import Decimal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = os.environ["LAGO_BUCKET"]
TABLA = boto3.resource("dynamodb").Table(os.environ["TABLA"])
S3 = boto3.client("s3", config=Config(signature_version="s3v4", region_name=os.environ["AWS_REGION"],
                                       s3={"addressing_style": "virtual"}))
PREFIJO = "raw/expedientes"
FORMATOS = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
MAX_CARTA = 10 * 1024 * 1024
MAX_CFDI = 1 * 1024 * 1024
RE_ID = re.compile(r"^EXP-[0-9]{4}-[0-9A-Za-z]{4,12}$")


def _r(status, cuerpo):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(cuerpo, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))}


def _usuario(evento):
    claims = evento.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    return claims.get("email") or claims.get("username") or claims.get("sub", "desconocido")


def crear(evento):
    cuerpo = json.loads(evento.get("body") or "{}")
    formato = str(cuerpo.get("formato_carta", "pdf")).lower()
    if formato not in FORMATOS:
        return _r(400, {"error": f"formato_carta debe ser uno de {sorted(FORMATOS)}"})
    exp_id = cuerpo.get("expediente_id") or f"EXP-{dt.date.today().year}-{uuid.uuid4().hex[:8].upper()}"
    if not RE_ID.match(exp_id):
        return _r(400, {"error": "expediente_id inválido (formato EXP-AAAA-XXXX)"})
    ext = "jpg" if formato == "jpeg" else formato
    carta_key = f"{PREFIJO}/{exp_id}/carta.{ext}"
    cfdi_key = f"{PREFIJO}/{exp_id}/cfdi.xml"
    ahora = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        TABLA.put_item(
            Item={"pk": f"EXP#{exp_id}", "sk": "META", "expediente_id": exp_id, "estado": "PENDIENTE_CARGA",
                  "gsi1pk": "ESTADO#PENDIENTE_CARGA", "gsi1sk": ahora, "creado_en": ahora,
                  "creado_por": _usuario(evento), "carta_key": carta_key, "cfdi_key": cfdi_key},
            ConditionExpression="attribute_not_exists(pk)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _r(409, {"error": f"El expediente {exp_id} ya existe"})
        raise
    urls = {
        "carta": S3.generate_presigned_url("put_object", ExpiresIn=900, Params={
            "Bucket": BUCKET, "Key": carta_key, "ContentType": FORMATOS[formato]}),
        "cfdi": S3.generate_presigned_url("put_object", ExpiresIn=900, Params={
            "Bucket": BUCKET, "Key": cfdi_key, "ContentType": "application/xml"}),
    }
    return _r(201, {"expediente_id": exp_id, "subir": urls, "content_type_carta": FORMATOS[formato],
                    "expira_en_segundos": 900})


def enviar(evento, exp_id):
    item = TABLA.get_item(Key={"pk": f"EXP#{exp_id}", "sk": "META"}).get("Item")
    if not item:
        return _r(404, {"error": "Expediente no encontrado"})
    tamanos = {}
    for nombre, key, maximo in (("carta", item["carta_key"], MAX_CARTA), ("cfdi", item["cfdi_key"], MAX_CFDI)):
        try:
            tamanos[nombre] = S3.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
        except ClientError:
            return _r(400, {"error": f"Falta subir el archivo '{nombre}'"})
        if tamanos[nombre] > maximo:
            return _r(413, {"error": f"El archivo '{nombre}' excede {maximo // 1024 // 1024} MB"})
    manifest = {"expediente_id": exp_id, "carta_key": item["carta_key"], "cfdi_key": item["cfdi_key"],
                "tamanos_bytes": tamanos, "enviado_por": _usuario(evento),
                "enviado_en": dt.datetime.now(dt.timezone.utc).isoformat()}
    S3.put_object(Bucket=BUCKET, Key=f"{PREFIJO}/{exp_id}/manifest.json",
                  Body=json.dumps(manifest, ensure_ascii=False).encode(), ContentType="application/json")
    return _r(202, {"expediente_id": exp_id, "mensaje": "Expediente en cola de validación"})


def consultar(exp_id):
    r = TABLA.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": f"EXP#{exp_id}"})
    if not r["Items"]:
        return _r(404, {"error": "Expediente no encontrado"})
    salida = {}
    for it in r["Items"]:
        it.pop("task_token", None)
        salida.setdefault("auditoria" if it["sk"].startswith("AUDIT#") else it["sk"].lower(), []).append(it)
    return _r(200, salida)


def handler(evento, _ctx):
    ruta = evento.get("routeKey", "")
    exp_id = (evento.get("pathParameters") or {}).get("id", "")
    if exp_id and not RE_ID.match(exp_id):
        return _r(400, {"error": "expediente_id inválido"})
    if ruta == "POST /expedientes":
        return crear(evento)
    if ruta == "POST /expedientes/{id}/enviar":
        return enviar(evento, exp_id)
    if ruta == "GET /expedientes/{id}":
        return consultar(exp_id)
    return _r(404, {"error": "Ruta no encontrada"})
