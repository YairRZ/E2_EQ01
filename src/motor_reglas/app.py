"""Motor de reglas FVR: el ÚNICO componente que decide.

Entrada (Step Functions): CFDI leído (leer_cfdi), carta estructurada (estructurar_carta) y firma (verificar_firma).
Salida: VALIDADO / OBSERVACIONES / REVISION_HUMANA con la lista de hallazgos por regla.

  - Una regla con resultado REJECT     -> OBSERVACIONES (se devuelve al proveedor con el mensaje)
  - Sólo reglas con HUMAN_REVIEW       -> REVISION_HUMANA (un analista decide)
  - Ninguna regla incumplida           -> VALIDADO

Reglas deterministas, sin IA. Montos con Decimal y tolerancia de 1.00 MXN contra el subtotal del CFDI.
Guarda el resultado en raw/resultados/{id}.json y en DynamoDB (sk = RESULTADO).
"""
import datetime as dt
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation

import boto3

S3 = boto3.client("s3")
TABLA = boto3.resource("dynamodb").Table(os.environ["TABLA"])
BUCKET = os.environ["LAGO_BUCKET"]
CATALOGO_KEY = os.environ.get("CATALOGO_KEY", "raw/catalogo_se/catalogo_se.jsonl")
TOLERANCIA = Decimal(os.environ.get("TOLERANCIA_MXN", "1.00"))
DIAS_MAX = int(os.environ.get("DIAS_MAX_CARTA_CFDI", "30"))
RETENCION_AUDIT_DIAS = int(os.environ.get("RETENCION_AUDIT_DIAS", "1825"))
VERSION_REGLAS = "fvr-v1"

REJECT, HUMAN = "REJECT", "HUMAN_REVIEW"
_catalogo = None


def catalogo():
    global _catalogo
    if _catalogo is None:
        cuerpo = S3.get_object(Bucket=BUCKET, Key=CATALOGO_KEY)["Body"].read().decode("utf-8")
        _catalogo = {json.loads(l)["codigo_se"].strip().upper() for l in cuerpo.splitlines() if l.strip()}
    return _catalogo


def dec(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return Decimal(str(v).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def limpio(s):
    return re.sub(r"[\s\-]", "", str(s or "")).upper()


# El OCR confunde la letra inicial del código SE con un dígito parecido (I0200 -> 10200, G0601 -> 60601).
OCR_LETRA = {"1": "I", "6": "G", "0": "O", "8": "B", "5": "S", "2": "Z", "7": "T"}


def en_catalogo(codigo, cat):
    """Devuelve el código del catálogo que corresponde, corrigiendo sólo la confusión dígito/letra de la primera
    posición; None si no existe. Un código inválido real (Z9999, A0999) sigue sin encontrarse."""
    c = limpio(codigo)
    if c in cat:
        return c
    if c[:1] in OCR_LETRA and len(c) == 5 and c[1:].isdigit():
        alterno = OCR_LETRA[c[0]] + c[1:]
        if alterno in cat:
            return alterno
    return None


def distancia(a, b):
    """Levenshtein: distingue un error de OCR (1-2 caracteres) de un documento distinto."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def fecha(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def evaluar(cfdi, carta, firma):
    hallazgos = []

    def h(regla, resultado, mensaje, esperado="", observado=""):
        hallazgos.append({"regla_id": regla, "resultado": resultado, "mensaje": mensaje,
                          "valor_esperado": str(esperado), "valor_observado": str(observado)})

    # ---------- Precondiciones ----------
    if not cfdi.get("valido"):
        h("FVR-PRE-001", REJECT, "El CFDI no es válido o no corresponde a un CFDI 4.0.",
          "CFDI 4.0 válido", "; ".join(cfdi.get("errores", [])))
    if not carta.get("extraccion_ok") or carta.get("confianza_extraccion") == "baja":
        h("FVR-PRE-002", HUMAN, "No fue posible leer la carta con confianza suficiente.",
          "extracción completa", carta.get("confianza_extraccion") or "sin extracción")
        return hallazgos, 2  # sin datos confiables no se evalúa el resto

    uuid_c, uuid_f = limpio(carta.get("uuid_cfdi")), limpio(cfdi.get("uuid"))
    d = distancia(uuid_c, uuid_f)
    if d:
        h("FVR-PRE-003", HUMAN if d <= 2 and uuid_c else REJECT,
          "El folio fiscal (UUID) de la carta no coincide con el del CFDI.", uuid_f, uuid_c)
    rfc_c, rfc_f = limpio(carta.get("proveedor_rfc")), limpio(cfdi.get("emisor_rfc"))
    d = distancia(rfc_c, rfc_f)
    if d:
        h("FVR-PRE-004", HUMAN if d <= 1 and rfc_c else REJECT,
          "El RFC del proveedor en la carta no coincide con el emisor del CFDI.", rfc_f, rfc_c)

    # ---------- Fechas ----------
    f_carta, f_cfdi = fecha(carta.get("fecha_emision")), fecha(cfdi.get("fecha"))
    anio_fiscal = carta.get("anio_fiscal")
    if not f_carta or not f_cfdi:
        h("FVR-DAT-001", HUMAN, "No se pudo leer la fecha de la carta o del CFDI.", "fecha válida",
          carta.get("fecha_emision", ""))
    else:
        if f_carta.year != f_cfdi.year or (anio_fiscal and int(anio_fiscal) != f_cfdi.year):
            h("FVR-DAT-001", REJECT, "La carta debe corresponder al ejercicio fiscal del CFDI.",
              f_cfdi.year, f"{f_carta.year} (ejercicio declarado {anio_fiscal})")
        dias = abs((f_carta - f_cfdi).days)
        if dias > DIAS_MAX:
            h("FVR-DAT-002", REJECT, f"La carta y el CFDI deben tener como máximo {DIAS_MAX} días de diferencia.",
              f"<= {DIAS_MAX} días", f"{dias} días")

    # ---------- Catálogo y proporción ----------
    conceptos = carta.get("conceptos") or []
    cat = catalogo()
    invalidos = [c.get("codigo_se", "") for c in conceptos if en_catalogo(c.get("codigo_se"), cat) is None]
    if invalidos:
        h("FVR-CAT-001", REJECT, "Código no encontrado en el catálogo de la Secretaría de Economía.",
          "código del catálogo SE", ", ".join(invalidos))
    for c in conceptos:
        texto = str(c.get("proporcion_texto", "")).strip()
        p = dec(texto)
        if p is None:
            h("FVR-PCT-001", HUMAN, "No se pudo leer la proporción de contenido nacional.", "0 a 1", texto)
            continue
        if p < 0 or p > 1:
            h("FVR-PCT-001", REJECT, "La proporción de contenido nacional debe estar entre 0 y 1.",
              "0 a 1", f"{c.get('codigo_se')}: {texto}")
        elif p < 1 and not re.fullmatch(r"0\.\d{3}", texto):
            h("FVR-PCT-002", REJECT, "La proporción menor a 1 debe expresarse con tres decimales.",
              "0.###", f"{c.get('codigo_se')}: {texto}")

    # ---------- Montos y conciliación con el CFDI ----------
    tc = dec(cfdi.get("tipo_cambio")) if cfdi.get("moneda") == "USD" else Decimal(1)
    subtotal, total = dec(cfdi.get("subtotal")), dec(cfdi.get("total"))
    montos = [dec(c.get("monto")) for c in conceptos]
    if None in montos or subtotal is None or tc is None:
        h("FVR-REC-001", HUMAN, "No se pudieron leer los montos para conciliar con el CFDI.", subtotal, montos)
        return hallazgos, 16
    total_carta = sum(montos, Decimal(0))
    subtotal_mxn = (subtotal * tc).quantize(Decimal("0.01"))
    total_mxn = (total * tc).quantize(Decimal("0.01")) if total is not None else None
    if total_mxn is not None and abs(total_carta - total_mxn) <= TOLERANCIA and total_mxn != subtotal_mxn:
        h("FVR-AMT-001", REJECT, "Los montos de la carta incluyen IVA; deben declararse antes de impuestos.",
          f"{subtotal_mxn} (subtotal)", f"{total_carta} (igual al total con IVA)")
    if total_carta > subtotal_mxn + TOLERANCIA:
        h("FVR-AMT-002", REJECT, "La suma de la carta excede el subtotal de la factura (monto anual o con IVA).",
          f"<= {subtotal_mxn}", total_carta)
    if cfdi.get("moneda") == "USD" and abs(total_carta - subtotal) <= TOLERANCIA:
        h("FVR-AMT-003", REJECT, "Los montos están en dólares; deben convertirse a pesos con el tipo de cambio del CFDI.",
          f"{subtotal_mxn} MXN (TC {tc})", f"{total_carta} (igual al subtotal en USD)")
    if abs(total_carta - subtotal_mxn) > TOLERANCIA:
        h("FVR-REC-001", REJECT, "La suma de la carta no concilia con el subtotal del CFDI en pesos.",
          f"{subtotal_mxn} ± {TOLERANCIA}", total_carta)

    # ---------- Formalidad, texto legal y firma ----------
    faltan = [k for k in ("destinatario", "representante_legal", "instrumento_publico") if not str(carta.get(k) or "").strip()]
    if faltan:
        h("FVR-FRM-001", REJECT, "Faltan datos formales de la carta (destinatario, representante o instrumento notarial).",
          "presentes", ", ".join(faltan))
    decl = carta.get("declaraciones") or {}
    faltan = [k for k in ("verificacion", "conservacion", "sanciones", "punto_19") if decl.get(k) is not True]
    if faltan:
        h("FVR-FRM-002", REJECT, "Faltan declaraciones obligatorias (veracidad, conservación, sanciones o punto 19).",
          "las cuatro declaraciones", ", ".join(faltan))
    estado_firma = (firma or {}).get("estado", "AUSENTE")
    if estado_firma == "AUSENTE":
        h("FVR-FRM-003", REJECT, "La carta no tiene la firma autógrafa del representante legal.", "PRESENTE", estado_firma)
    elif estado_firma == "DUDOSA":
        h("FVR-FRM-003", HUMAN, "La firma es tenue o está fuera de la zona esperada; requiere revisión.",
          "PRESENTE", f"DUDOSA ({(firma or {}).get('confianza')})")
    return hallazgos, 16


def decidir(hallazgos):
    if any(x["resultado"] == REJECT for x in hallazgos):
        return "OBSERVACIONES"
    if hallazgos:
        return "REVISION_HUMANA"
    return "VALIDADO"


def handler(ev, _ctx):
    exp = ev["expediente"]
    exp_id = exp["expediente_id"]
    cfdi = ev.get("cfdi") or {}
    carta = (ev.get("extraccion") or {}).get("carta") or {}
    firma = ev.get("firma") or {}
    hallazgos, evaluadas = evaluar(cfdi, carta, firma)
    decision = decidir(hallazgos)
    ahora = dt.datetime.now(dt.timezone.utc).isoformat()
    resultado = {
        "expediente_id": exp_id, "decision": decision, "hallazgos": hallazgos, "reglas_evaluadas": evaluadas,
        "version_reglas": VERSION_REGLAS, "evaluado_en": ahora,
        "firma_estado": firma.get("estado"), "firma_confianza": firma.get("confianza"),
        "modelo_bedrock": (carta.get("_meta") or {}).get("modelo"),
        "prompt_version": (carta.get("_meta") or {}).get("prompt_version"),
        "total_carta": str(sum((dec(c.get("monto")) or Decimal(0)) for c in carta.get("conceptos") or [])),
        "conceptos_carta": [{"codigo_se": c.get("codigo_se"), "descripcion": c.get("descripcion"),
                             "proporcion_texto": c.get("proporcion_texto"), "monto": c.get("monto")}
                            for c in carta.get("conceptos") or []],
    }
    S3.put_object(Bucket=BUCKET, Key=f"raw/resultados/{exp_id}.json",
                  Body=json.dumps(resultado, ensure_ascii=False).encode(), ContentType="application/json")
    TABLA.put_item(Item={"pk": f"EXP#{exp_id}", "sk": "RESULTADO", "decision": decision,
                         "hallazgos": json.dumps(hallazgos, ensure_ascii=False), "evaluado_en": ahora,
                         "version_reglas": VERSION_REGLAS, "firma_estado": str(firma.get("estado"))})
    TABLA.update_item(Key={"pk": f"EXP#{exp_id}", "sk": "META"},
                      UpdateExpression="SET estado = :e, gsi1pk = :g, gsi1sk = :t, actualizado_en = :t, decision = :e",
                      ExpressionAttributeValues={":e": decision, ":g": f"ESTADO#{decision}", ":t": ahora})
    TABLA.put_item(Item={"pk": f"EXP#{exp_id}", "sk": f"AUDIT#{ahora}#DECISION_MOTOR", "evento": "DECISION_MOTOR",
                         "en": ahora, "detalle": json.dumps({"decision": decision, "reglas": [x["regla_id"] for x in hallazgos]}),
                         "expira_en": int(time.time()) + RETENCION_AUDIT_DIAS * 86400})
    return {"expediente_id": exp_id, "decision": decision, "hallazgos": hallazgos}
