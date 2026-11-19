"""Verificación de PRESENCIA de firma autógrafa en la última página (validación independiente de la IA).

Textract detecta que hay una firma (bloque SIGNATURE) con una confianza; NO autentica a quién pertenece.
  PRESENTE -> hay firma en la última página, en la mitad inferior, con confianza >= UMBRAL_ALTO
  DUDOSA   -> hay firma pero con confianza entre UMBRAL_BAJO y UMBRAL_ALTO, o fuera de la zona esperada
  AUSENTE  -> no hay ninguna firma con confianza >= UMBRAL_BAJO en la última página
"""
import os

UMBRAL_ALTO = float(os.environ.get("UMBRAL_FIRMA_ALTO", "50"))
UMBRAL_BAJO = float(os.environ.get("UMBRAL_FIRMA_BAJO", "10"))


def evaluar(senales):
    ultima = senales.get("paginas", 1)
    en_ultima = [f for f in senales.get("firmas", []) if f["pagina"] == ultima and f["confianza"] >= UMBRAL_BAJO]
    if not en_ultima:
        return {"estado": "AUSENTE", "confianza": 0, "pagina": ultima, "candidatas": 0}
    mejor = max(en_ultima, key=lambda f: f["confianza"])
    zona_ok = mejor["bbox"]["top"] >= 0.15  # debajo del encabezado
    estado = "PRESENTE" if mejor["confianza"] >= UMBRAL_ALTO and zona_ok else "DUDOSA"
    return {"estado": estado, "confianza": mejor["confianza"], "pagina": ultima,
            "candidatas": len(en_ultima), "bbox": mejor["bbox"]}


def handler(ev, _ctx):
    return evaluar(ev["senales"])
