"""Lectura determinística del CFDI 4.0 (XML). No usa IA: el XML ya es estructurado.

Valida estructura mínima (versión, UUID, emisor, conceptos) y coherencia aritmética
(suma de conceptos = SubTotal; SubTotal + IVA = Total). Guarda el JSON en raw/extracciones/cfdi/.
Pendiente (fase 2): validación contra el XSD oficial del SAT y consulta de estatus del CFDI en el SAT.
"""
import json
import os
import xml.etree.ElementTree as ET  # expat moderno no resuelve entidades externas (sin XXE)
from decimal import Decimal, InvalidOperation

import boto3

S3 = boto3.client("s3")
NS = {"cfdi": "http://www.sat.gob.mx/cfd/4", "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital"}


def _d(v):
    try:
        return Decimal(v)
    except (InvalidOperation, TypeError):
        return None


def parsear(xml_bytes):
    errores = []
    raiz = ET.fromstring(xml_bytes)
    if raiz.tag != f'{{{NS["cfdi"]}}}Comprobante':
        return {"valido": False, "errores": ["El XML no es un Comprobante CFDI 4.0"]}
    a = raiz.attrib
    emisor = raiz.find("cfdi:Emisor", NS)
    receptor = raiz.find("cfdi:Receptor", NS)
    timbre = raiz.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    traslados = raiz.findall("cfdi:Impuestos/cfdi:Traslados/cfdi:Traslado", NS)
    conceptos = [{"descripcion": c.get("Descripcion", ""), "importe": str(_d(c.get("Importe")) or 0),
                  "clave_prod_serv": c.get("ClaveProdServ", "")}
                 for c in raiz.findall("cfdi:Conceptos/cfdi:Concepto", NS)]
    if a.get("Version") != "4.0":
        errores.append(f"Versión de CFDI no soportada: {a.get('Version')}")
    if timbre is None or not timbre.get("UUID"):
        errores.append("Sin TimbreFiscalDigital/UUID")
    if emisor is None or not emisor.get("Rfc"):
        errores.append("Sin RFC del emisor")
    if not conceptos:
        errores.append("Sin conceptos")
    subtotal, total = _d(a.get("SubTotal")), _d(a.get("Total"))
    iva = sum((_d(t.get("Importe")) or Decimal(0)) for t in traslados if t.get("Impuesto") == "002")
    if subtotal is None or total is None:
        errores.append("SubTotal/Total ilegibles")
    else:
        suma = sum(Decimal(c["importe"]) for c in conceptos)
        if abs(suma - subtotal) > Decimal("0.05"):
            errores.append(f"Suma de conceptos {suma} != SubTotal {subtotal}")
        if abs(subtotal + iva - total) > Decimal("0.05"):
            errores.append(f"SubTotal + IVA {subtotal + iva} != Total {total}")
    moneda = a.get("Moneda", "MXN")
    tc = _d(a.get("TipoCambio")) if moneda == "USD" else Decimal(1)
    if moneda not in ("MXN", "USD"):
        errores.append(f"Moneda {moneda} fuera de alcance")
    return {
        "valido": not errores, "errores": errores,
        "version": a.get("Version"), "uuid": (timbre.get("UUID") if timbre is not None else "").upper(),
        "serie": a.get("Serie"), "folio": a.get("Folio"), "fecha": (a.get("Fecha") or "")[:10],
        "moneda": moneda, "tipo_cambio": str(tc) if tc is not None else None,
        "subtotal": str(subtotal), "iva": str(iva), "total": str(total),
        "emisor_rfc": emisor.get("Rfc", "") if emisor is not None else "",
        "emisor_nombre": emisor.get("Nombre", "") if emisor is not None else "",
        "receptor_rfc": receptor.get("Rfc", "") if receptor is not None else "",
        "conceptos": conceptos,
    }


def handler(ev, _ctx):
    obj = S3.get_object(Bucket=ev["bucket"], Key=ev["cfdi_key"])
    try:
        cfdi = parsear(obj["Body"].read())
    except ET.ParseError as e:
        cfdi = {"valido": False, "errores": [f"XML mal formado: {e}"]}
    cfdi["expediente_id"] = ev["expediente_id"]
    S3.put_object(Bucket=ev["bucket"], Key=f"raw/extracciones/cfdi/{ev['expediente_id']}.json",
                  Body=json.dumps(cfdi, ensure_ascii=False).encode(), ContentType="application/json")
    return cfdi
