#!/usr/bin/env python3
"""Genera expedientes SINTÉTICOS para el Validador Inteligente de Cartas de Contenido Nacional.

Cada expediente = una carta (PDF de 2 páginas o JPG escaneado de 1 página) + su CFDI 4.0 en XML.
Todos los nombres, RFC, UUID, contratos y montos son ficticios. No hay datos reales de proveedores.

Además escribe `esperado.csv` con la decisión que DEBERÍA tomar el pipeline, para medir
qué tan bien funciona (evidencia de prueba).

Uso:
    python3 generar_expedientes.py --n 30 --salida expedientes --semilla 42

Requiere: reportlab, Pillow y `pdftoppm` (poppler) solo para los casos JPG.
En CloudShell no hace falta correrlo: los expedientes ya vienen generados en el repo.
"""
import argparse
import csv
import datetime as dt
import json
import random
import shutil
import subprocess
import tempfile
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Flowable, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

AQUI = Path(__file__).resolve().parent
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

RECEPTOR = {"rfc": "OEG150301AB1", "nombre": "OPERADORA ENERGETICA DEL GOLFO SA DE CV"}
PROVEEDORES = [
    ("SPT180512KL3", "SERVICIOS PETROLEROS DEL TROPICO SA DE CV", "Laura Méndez Ortiz"),
    ("ITC170823QW8", "INGENIERIA Y TUBERIAS DE CAMPECHE SA DE CV", "Jorge Alberto Ruiz Pech"),
    ("MEV190104ZX2", "MANTENIMIENTO ELECTRICO VILLAHERMOSA SA DE CV", "Ana Sofía Cruz Lara"),
    ("CIS160930RT5", "CONSTRUCCIONES INDUSTRIALES DEL SURESTE SA DE CV", "Ricardo Hernández Gil"),
    ("AIR200215MN7", "AISLAMIENTOS Y RECUBRIMIENTOS DEL GOLFO SA DE CV", "María Fernanda Torres"),
    ("PIN150707HJ4", "PERFORACION E INSTRUMENTACION NACIONAL SA DE CV", "Héctor Daniel Ochoa"),
]
BLOQUES = ["Bloque Norte", "Bloque Sur"]

# Casos de prueba: (nombre, decisión esperada, reglas que deberían dispararse)
CASOS = [
    ("ok", "VALIDADO", ""),
    ("ok", "VALIDADO", ""),
    ("ok", "VALIDADO", ""),
    ("ok_usd", "VALIDADO", ""),
    ("iva_incluido", "OBSERVACIONES", "FVR-AMT-001;FVR-AMT-002;FVR-REC-001"),
    ("monto_anual", "OBSERVACIONES", "FVR-AMT-002;FVR-REC-001"),
    ("codigo_invalido", "OBSERVACIONES", "FVR-CAT-001"),
    ("proporcion_mayor_1", "OBSERVACIONES", "FVR-PCT-001"),
    ("proporcion_decimales", "OBSERVACIONES", "FVR-PCT-002"),
    ("fecha_lejana", "OBSERVACIONES", "FVR-DAT-002"),
    ("sin_firma", "OBSERVACIONES", "FVR-FRM-003"),
    ("firma_dudosa", "REVISION_HUMANA", "FVR-FRM-003"),
    ("usd_sin_homologar", "OBSERVACIONES", "FVR-AMT-003;FVR-REC-001"),
    ("rfc_distinto", "OBSERVACIONES", "FVR-PRE-004"),
]


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Firma(Flowable):
    """Garabato que simula una firma autógrafa. intensidad: 'normal', 'tenue' o 'ninguna'."""

    def __init__(self, rnd, intensidad="normal", ancho=6 * cm, alto=2.2 * cm):
        super().__init__()
        self.rnd, self.intensidad, self.width, self.height = rnd, intensidad, ancho, alto

    def draw(self):
        if self.intensidad == "ninguna":
            return
        c = self.canv
        tenue = self.intensidad == "tenue"
        c.setStrokeColor(colors.Color(0.75, 0.78, 0.85) if tenue else colors.Color(0.05, 0.1, 0.45))
        c.setLineWidth(0.5 if tenue else 1.6)
        x, y = 0.3 * cm, self.height * 0.45
        trazos = 2 if tenue else 5
        escala = 0.35 if tenue else 1.0
        for _ in range(trazos):
            p = c.beginPath()
            p.moveTo(x, y)
            for _ in range(3):
                x2 = x + self.rnd.uniform(0.6, 1.3) * cm * escala
                p.curveTo(x + self.rnd.uniform(-0.3, 0.8) * cm * escala, y + self.rnd.uniform(0.2, 1.2) * cm * escala,
                          x2 - self.rnd.uniform(0, 0.5) * cm * escala, y - self.rnd.uniform(0.2, 1.0) * cm * escala,
                          x2, y + self.rnd.uniform(-0.3, 0.3) * cm * escala)
                x = x2
            c.drawPath(p, stroke=1, fill=0)
            x -= self.rnd.uniform(1.0, 2.0) * cm * escala
        if not tenue:
            c.line(0.2 * cm, 0.35 * cm, self.width * 0.9, 0.45 * cm)


def cfdi_xml(c):
    """CFDI 4.0 simplificado (estructura del Anexo 20 del SAT, sin sello real)."""
    conceptos = "\n".join(
        f'    <cfdi:Concepto ClaveProdServ="{k["clave_sat"]}" Cantidad="1" ClaveUnidad="E48" '
        f'Descripcion="{k["descripcion"]}" ValorUnitario="{k["importe"]}" Importe="{k["importe"]}" ObjetoImp="02"/>'
        for k in c["conceptos_cfdi"])
    tc = f' TipoCambio="{c["tipo_cambio"]}"' if c["moneda"] == "USD" else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="A" Folio="{c["folio"]}" Fecha="{c["fecha_cfdi"]}T10:15:00" Moneda="{c["moneda"]}"{tc}
  SubTotal="{c["subtotal"]}" Total="{c["total"]}" TipoDeComprobante="I" Exportacion="01" MetodoPago="PPD" LugarExpedicion="86000">
  <cfdi:Emisor Rfc="{c["rfc_cfdi"]}" Nombre="{c["proveedor"]}" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{RECEPTOR["rfc"]}" Nombre="{RECEPTOR["nombre"]}" UsoCFDI="G03" DomicilioFiscalReceptor="86000" RegimenFiscalReceptor="601"/>
  <cfdi:Conceptos>
{conceptos}
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="{c["iva"]}">
    <cfdi:Traslados><cfdi:Traslado Base="{c["subtotal"]}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="0.160000" Importe="{c["iva"]}"/></cfdi:Traslados>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{c["uuid"]}" FechaTimbrado="{c["fecha_cfdi"]}T10:16:02" RfcProvCertif="SAT970701NN3"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
'''


def carta_pdf(c, ruta, compacta, rnd):
    estilos = getSampleStyleSheet()
    base = 8.5 if compacta else 10.5
    n = ParagraphStyle("n", parent=estilos["Normal"], fontSize=base, leading=base * 1.35)
    t = ParagraphStyle("t", parent=estilos["Title"], fontSize=base + 4)
    der = ParagraphStyle("d", parent=n, alignment=2)
    f = dt.date.fromisoformat(c["fecha_carta"])
    h = []
    h.append(Paragraph(f'{c["lugar"]}, a {f.day} de {MESES[f.month - 1]} de {f.year}', der))
    h.append(Paragraph(f'Folio de carta: {c["folio_carta"]}', der))
    h.append(Spacer(1, 6))
    h.append(Paragraph("CARTA DE CONTENIDO NACIONAL", t))
    h.append(Paragraph(f'<b>{RECEPTOR["nombre"]}</b><br/>Presente', n))
    h.append(Spacer(1, 6))
    h.append(Paragraph(
        f'Por medio de la presente, <b>{c["proveedor"]}</b>, con RFC <b>{c["rfc_carta"]}</b>, representada en este acto por '
        f'<b>{c["representante"]}</b> en su carácter de representante legal, según consta en la escritura pública '
        f'número {c["escritura"]} otorgada ante la fe del Notario Público número {c["notario"]} de Villahermosa, Tabasco, '
        f'declara bajo protesta de decir verdad el contenido nacional de los bienes y servicios suministrados al amparo '
        f'del contrato <b>{c["contrato"]}</b> ({c["bloque"]}), correspondientes a la factura con folio fiscal '
        f'<b>{c["uuid"]}</b>, para el ejercicio fiscal <b>{c["anio_fiscal"]}</b>.', n))
    h.append(Spacer(1, 6))
    h.append(Paragraph(f'Domicilio para oír y recibir notificaciones: {c["domicilio"]}. '
                       f'Correo: {c["email"]}. Teléfono: {c["telefono"]}.', n))
    h.append(Spacer(1, 8))
    filas = [["Código SE", "Descripción del bien o servicio", "Proporción CN", "Monto (MXN, antes de IVA)"]]
    for k in c["conceptos_carta"]:
        filas.append([k["codigo_se"], Paragraph(k["descripcion"], n), k["proporcion_txt"], f'${k["monto"]:,.2f}'])
    filas.append(["", Paragraph("<b>Total</b>", n), "", f'${c["total_carta"]:,.2f}'])
    tabla = Table(filas, colWidths=[2.3 * cm, 8.2 * cm, 2.6 * cm, 4.2 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.88, 0.88, 0.88)),
        ("FONTSIZE", (0, 0), (-1, -1), base - 0.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    h.append(tabla)
    if not compacta:
        h.append(PageBreak())
    else:
        h.append(Spacer(1, 8))
    for parrafo in [
        "Declaramos que la información contenida en esta carta es verificable y que pondremos a disposición de la "
        "Secretaría de Economía la documentación soporte cuando ésta lo requiera.",
        "Nos comprometemos a conservar los registros que sustentan el contenido nacional declarado durante el plazo "
        "que establezcan las disposiciones aplicables.",
        "Conocemos las sanciones aplicables en caso de declarar información falsa, conforme a la normatividad vigente.",
        "Lo anterior conforme al punto 19 de la metodología para la medición del contenido nacional.",
    ]:
        h.append(Paragraph(parrafo, n))
        h.append(Spacer(1, 4))
    h.append(Spacer(1, 14))
    h.append(Paragraph("Atentamente,", n))
    h.append(Firma(rnd, c["firma"]))
    h.append(Paragraph(f'<b>{c["representante"]}</b><br/>Representante Legal<br/>{c["proveedor"]}', n))
    SimpleDocTemplate(str(ruta), pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                      title=f'Carta CN {c["folio_carta"]}', author="Sintético EQ01").build(h)


def a_jpg(pdf, jpg, rnd):
    from PIL import Image, ImageFilter
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-jpeg", "-r", "150", "-singlefile", str(pdf), f"{tmp}/p"], check=True)
        img = Image.open(f"{tmp}/p.jpg").convert("L")
    img = img.rotate(rnd.uniform(-1.2, 1.2), expand=True, fillcolor=245).filter(ImageFilter.GaussianBlur(0.4))
    img.convert("RGB").save(jpg, "JPEG", quality=78)


def construir(i, caso, rnd, catalogo):
    nombre, esperado, reglas = caso
    rfc, proveedor, representante = rnd.choice(PROVEEDORES)
    fecha_cfdi = dt.date(2026, rnd.choice([9, 10, 11]), rnd.randint(1, 14))
    delta = rnd.randint(-10, 20) if nombre != "fecha_lejana" else rnd.choice([-45, 52])
    fecha_carta = fecha_cfdi + dt.timedelta(days=delta)
    if fecha_carta.year != fecha_cfdi.year:
        fecha_carta = fecha_cfdi - dt.timedelta(days=abs(delta))
    moneda = "USD" if nombre in ("ok_usd", "usd_sin_homologar") else "MXN"
    tipo_cambio = q2(Decimal(str(rnd.uniform(17.2, 19.4)))) if moneda == "USD" else Decimal(1)
    tipo_cambio = Decimal(tipo_cambio).quantize(Decimal("0.0001"))

    n_conceptos = rnd.randint(1, 4)
    codigos = rnd.sample(catalogo, n_conceptos)
    conceptos_cfdi, conceptos_carta = [], []
    for k, cod in enumerate(codigos):
        importe = q2(Decimal(rnd.randint(18_000, 420_000)) + Decimal(rnd.randint(0, 99)) / 100)
        if moneda == "USD":
            importe = q2(importe / Decimal(18))
        conceptos_cfdi.append({"clave_sat": "72141100", "descripcion": cod["Actividad"].upper()[:80], "importe": importe})
        monto_mxn = q2(importe * tipo_cambio) if nombre != "usd_sin_homologar" else importe
        prop = rnd.choice(["0.350", "0.500", "0.725", "0.800", "1", "0.000", "0.615"])
        conceptos_carta.append({"codigo_se": cod["Código SE"], "descripcion": cod["Actividad"],
                                "proporcion_txt": prop, "monto": monto_mxn})
    subtotal = q2(sum(k["importe"] for k in conceptos_cfdi))
    iva = q2(subtotal * Decimal("0.16"))
    total = subtotal + iva

    if nombre == "iva_incluido":
        factor = total / subtotal
        for k in conceptos_carta:
            k["monto"] = q2(k["monto"] * factor)
        ajuste = q2(total - sum(k["monto"] for k in conceptos_carta))
        conceptos_carta[-1]["monto"] += ajuste
    if nombre == "monto_anual":
        for k in conceptos_carta:
            k["monto"] = q2(k["monto"] * 12)
    if nombre == "codigo_invalido":
        conceptos_carta[0]["codigo_se"] = rnd.choice(["Z9999", "A0999", "J7777"])
    if nombre == "proporcion_mayor_1":
        conceptos_carta[0]["proporcion_txt"] = "1.250"
    if nombre == "proporcion_decimales":
        conceptos_carta[0]["proporcion_txt"] = rnd.choice(["0.5", "0.75", "0.6000"])

    exp_id = f"EXP-2026-{i:04d}"
    c = {
        "expediente_id": exp_id, "caso": nombre, "decision_esperada": esperado, "reglas_esperadas": reglas,
        "uuid": str(uuid.UUID(int=rnd.getrandbits(128))).upper(), "folio": str(5000 + i),
        "folio_carta": f"CCN-{fecha_carta.year}-{i:04d}",
        "fecha_cfdi": fecha_cfdi.isoformat(), "fecha_carta": fecha_carta.isoformat(),
        "moneda": moneda, "tipo_cambio": tipo_cambio, "subtotal": subtotal, "iva": iva, "total": total,
        "rfc_cfdi": rfc, "rfc_carta": rfc if nombre != "rfc_distinto" else rnd.choice([p[0] for p in PROVEEDORES if p[0] != rfc]),
        "proveedor": proveedor, "representante": representante,
        "escritura": rnd.randint(10_000, 89_999), "notario": rnd.randint(1, 40),
        "contrato": f"CTO-OEG-2026-{rnd.randint(100, 999)}", "bloque": rnd.choice(BLOQUES),
        "anio_fiscal": fecha_cfdi.year, "lugar": "Villahermosa, Tabasco",
        "domicilio": f"Av. Paseo Tabasco {rnd.randint(100, 1999)}, Col. Centro, C.P. 86000, Villahermosa, Tabasco",
        "email": f"contacto{i:02d}@proveedor-ficticio.mx", "telefono": f"993 {rnd.randint(100, 999)} {rnd.randint(1000, 9999)}",
        "conceptos_cfdi": conceptos_cfdi, "conceptos_carta": conceptos_carta,
        "total_carta": q2(sum(k["monto"] for k in conceptos_carta)),
        "firma": {"sin_firma": "ninguna", "firma_dudosa": "tenue"}.get(nombre, "normal"),
    }
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--salida", default=str(AQUI / "expedientes"))
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--pct-jpg", type=float, default=0.3)
    a = ap.parse_args()
    rnd = random.Random(a.semilla)
    catalogo = json.loads((AQUI / "catalogo_se.json").read_text(encoding="utf-8"))
    salida = Path(a.salida)
    if salida.exists():
        shutil.rmtree(salida)
    salida.mkdir(parents=True)
    filas = []
    for i in range(1, a.n + 1):
        caso = CASOS[(i - 1) % len(CASOS)] if i <= len(CASOS) else rnd.choice(CASOS[:4] * 3 + CASOS[4:])
        c = construir(i, caso, rnd, catalogo)
        d = salida / c["expediente_id"]
        d.mkdir()
        (d / "cfdi.xml").write_text(cfdi_xml(c), encoding="utf-8")
        es_jpg = rnd.random() < a.pct_jpg and c["caso"] != "firma_dudosa"
        if es_jpg:
            carta_pdf(c, d / "_tmp.pdf", compacta=True, rnd=rnd)
            a_jpg(d / "_tmp.pdf", d / "carta.jpg", rnd)
            (d / "_tmp.pdf").unlink()
        else:
            carta_pdf(c, d / "carta.pdf", compacta=False, rnd=rnd)
        filas.append({"expediente_id": c["expediente_id"], "caso": c["caso"],
                      "formato_carta": "jpg" if es_jpg else "pdf", "moneda": c["moneda"],
                      "decision_esperada": c["decision_esperada"], "reglas_esperadas": c["reglas_esperadas"]})
    with open(salida / "esperado.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} expedientes en {salida}")


if __name__ == "__main__":
    main()
