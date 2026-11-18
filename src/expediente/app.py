"""Estado del expediente en DynamoDB (tabla única). La invoca Step Functions con distintas `accion`:

  registrar           -> primer paso: lee manifest.json, aplica idempotencia y marca EN_PROCESO.
                         Devuelve {"duplicado": true} o {"invalido": true} en lugar de fallar la ejecución.
  solicitar_revision  -> guarda el task token (.waitForTaskToken) y avisa a la cola de revisión humana
  decision_humana     -> registra la decisión del analista
  revision_vencida    -> nadie revisó en 7 días
  error               -> registra fallo técnico

Diseño de llaves:  pk = EXP#<id>   sk = META | RESULTADO | AUDIT#<timestamp>#<evento>
GSI1 (bandeja por estado): gsi1pk = ESTADO#<estado>, gsi1sk = fecha
"""
import datetime as dt
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

TABLA = boto3.resource("dynamodb").Table(os.environ["TABLA"])
S3 = boto3.client("s3")
SQS = boto3.client("sqs")
COLA_REVISION = os.environ.get("COLA_REVISION_URL", "")
RETENCION_AUDIT_DIAS = int(os.environ.get("RETENCION_AUDIT_DIAS", "1825"))


class ExpedienteDuplicado(Exception):
    pass


class ManifestInvalido(Exception):
    pass


def _ahora():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def auditar(exp_id, evento, detalle):
    ts = _ahora()
    TABLA.put_item(Item={
        "pk": f"EXP#{exp_id}", "sk": f"AUDIT#{ts}#{evento}", "evento": evento, "en": ts,
        "detalle": json.dumps(detalle, ensure_ascii=False, default=str)[:20000],
        "expira_en": int(time.time()) + RETENCION_AUDIT_DIAS * 86400,  # TTL: limpieza automática y gratuita
    })


def estado(exp_id, nuevo, extra=None, condicion=None, valores=None):
    sets = ["estado = :e", "gsi1pk = :g", "gsi1sk = :t", "actualizado_en = :t"]
    vals = {":e": nuevo, ":g": f"ESTADO#{nuevo}", ":t": _ahora()}
    for i, (k, v) in enumerate((extra or {}).items()):
        sets.append(f"{k} = :x{i}")
        vals[f":x{i}"] = v
    kw = {"Key": {"pk": f"EXP#{exp_id}", "sk": "META"}, "UpdateExpression": "SET " + ", ".join(sets),
          "ExpressionAttributeValues": {**vals, **(valores or {})}}
    if condicion:
        kw["ConditionExpression"] = condicion
    TABLA.update_item(**kw)


def registrar(ev, ctx_ejecucion):
    det = ev["evento"]["detail"]
    bucket, key = det["bucket"]["name"], det["object"]["key"]
    manifest = json.loads(S3.get_object(Bucket=bucket, Key=key)["Body"].read())
    exp_id = manifest.get("expediente_id", "")
    if not exp_id or key != f"raw/expedientes/{exp_id}/manifest.json":
        raise ManifestInvalido(f"manifest inconsistente: {key}")
    try:
        # Idempotencia: si el mismo manifest llega dos veces (reintento de EventBridge o re-subida)
        # sólo la primera ejecución avanza. REPROCESAR lo marca un administrador para volver a validar.
        estado(exp_id, "EN_PROCESO", {"ejecucion": ctx_ejecucion, "carta_key": manifest["carta_key"],
                                      "cfdi_key": manifest["cfdi_key"], "expediente_id": exp_id},
               condicion="attribute_not_exists(estado) OR estado IN (:p1, :p2, :p3)",
               valores={":p1": "PENDIENTE_CARGA", ":p2": "ERROR", ":p3": "REPROCESAR"})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ExpedienteDuplicado(f"{exp_id} ya fue procesado o está en proceso")
        raise
    auditar(exp_id, "RECIBIDO", {"manifest": manifest, "ejecucion": ctx_ejecucion})
    return {"expediente_id": exp_id, "bucket": bucket, "carta_key": manifest["carta_key"],
            "cfdi_key": manifest["cfdi_key"], "formato_carta": manifest["carta_key"].rsplit(".", 1)[-1]}


def handler(ev, _ctx):
    accion = ev.get("accion")
    if accion == "registrar":
        # Step Functions decide con estos campos. Una excepción aquí se vería como
        # fallo técnico y reintentaría un duplicado, que es justo lo que hay que rechazar.
        try:
            return registrar(ev, ev.get("ejecucion", ""))
        except ExpedienteDuplicado as e:
            return {"duplicado": True, "mensaje": str(e)}
        except ManifestInvalido as e:
            return {"invalido": True, "mensaje": str(e)}

    exp_id = ev.get("expediente_id") or ev.get("entrada", {}).get("expediente", {}).get("expediente_id")
    if accion == "solicitar_revision":
        estado(exp_id, "REVISION_HUMANA", {"task_token": ev["task_token"],
                                            "motivo_revision": ev.get("resultado", {}).get("hallazgos", [])})
        if COLA_REVISION:
            SQS.send_message(QueueUrl=COLA_REVISION, MessageBody=json.dumps(
                {"expediente_id": exp_id, "hallazgos": ev.get("resultado", {}).get("hallazgos", [])},
                ensure_ascii=False))
        auditar(exp_id, "REVISION_SOLICITADA", ev.get("resultado", {}))
        return {"ok": True}
    if accion == "decision_humana":
        rev = ev.get("revision", {})
        final = rev.get("decision", "OBSERVACIONES")
        estado(exp_id, final, {"decision_final": final, "revisado_por": rev.get("analista", "?"),
                               "comentario_revision": rev.get("comentario", "")})
        TABLA.update_item(Key={"pk": f"EXP#{exp_id}", "sk": "META"}, UpdateExpression="REMOVE task_token")
        auditar(exp_id, "DECISION_HUMANA", rev)
        return {"decision_final": final}
    if accion == "revision_vencida":
        estado(exp_id, "REVISION_VENCIDA")
        auditar(exp_id, "REVISION_VENCIDA", {})
        return {"ok": True}
    if accion == "error":
        err = ev.get("error", {})
        if exp_id:
            estado(exp_id, "ERROR", {"error": str(err.get("Error", ""))[:200], "causa": str(err.get("Cause", ""))[:1000]})
            auditar(exp_id, "ERROR", err)
        return {"ok": True}
    raise ValueError(f"accion desconocida: {accion}")
