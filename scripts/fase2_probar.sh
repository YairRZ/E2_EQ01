#!/usr/bin/env bash
# FASE 2 — Prueba de ingesta.
# Crea un usuario de Cognito, sube 3 expedientes sintéticos por la API y repite
# el primero para comprobar que la segunda ejecución se rechaza por idempotencia.
# Uso en CloudShell, después de fase2_desplegar.sh:  bash scripts/fase2_probar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
STACK="cn-eq01-ingesta"
EMAIL="prueba.eq01@example.com"
SALIDA="evidencias/fase2_resultado.md"
mkdir -p evidencias

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta prueba solo corre en us-east-2. Región actual: $REGION"
  exit 1
fi

salida() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
API=$(salida ApiUrl)
POOL=$(salida UserPoolId)
CLIENT=$(salida UserPoolClientId)
MAQUINA=$(salida MaquinaArn)
DLQ=$(salida ColaDlqUrl)
if [[ -z "$API" || "$API" == "None" ]]; then
  echo "No está el stack $STACK. Corre antes: bash scripts/fase2_desplegar.sh"
  exit 1
fi

echo "1/4 Usuario de prueba en Cognito ($EMAIL) ..."
PASS=$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits+"-._"; print("Aa1!"+"".join(secrets.choice(a) for _ in range(16)))')
umask 077
printf '%s\n' "$PASS" > /tmp/cn-eq01-cognito.txt
if aws cognito-idp admin-get-user --region "$REGION" --user-pool-id "$POOL" --username "$EMAIL" >/dev/null 2>&1; then
  echo "   El usuario ya existía; se renueva la contraseña."
else
  aws cognito-idp admin-create-user --region "$REGION" --user-pool-id "$POOL" \
    --username "$EMAIL" --message-action SUPPRESS \
    --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true >/dev/null
fi
aws cognito-idp admin-set-user-password --region "$REGION" --user-pool-id "$POOL" \
  --username "$EMAIL" --password "$PASS" --permanent >/dev/null
TOKEN=$(aws cognito-idp admin-initiate-auth --region "$REGION" --user-pool-id "$POOL" \
  --client-id "$CLIENT" --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=$EMAIL,PASSWORD=$PASS" \
  --query AuthenticationResult.IdToken --output text)
echo "   Token listo. La contraseña quedó solo en /tmp/cn-eq01-cognito.txt"

echo "2/4 Subiendo 3 expedientes y repitiendo el primero ..."
export API TOKEN REGION MAQUINA DLQ SALIDA
python3 - <<'PY'
import json, os, pathlib, time, urllib.error, urllib.request

api = os.environ["API"].rstrip("/")
token = os.environ["TOKEN"]
region = os.environ["REGION"]
maquina = os.environ["MAQUINA"]
dlq = os.environ["DLQ"]
salida = pathlib.Path(os.environ["SALIDA"])
ids = ["EXP-2026-0001", "EXP-2026-0002", "EXP-2026-0003"]
raiz = pathlib.Path("datos/expedientes")

def http(metodo, url, cuerpo=None, headers=None, espera=None):
    req = urllib.request.Request(url, data=cuerpo, method=metodo)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def api_json(metodo, ruta, cuerpo=None):
    data = None if cuerpo is None else json.dumps(cuerpo).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    codigo, raw = http(metodo, api + ruta, data, headers)
    try:
        parsed = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        parsed = {"raw": raw.decode(errors="replace")[:300]}
    return codigo, parsed

def carta_de(exp):
    carpeta = raiz / exp
    for nombre, tipo in (("carta.pdf", "pdf"), ("carta.jpg", "jpg"), ("carta.jpeg", "jpeg"), ("carta.png", "png")):
        path = carpeta / nombre
        if path.exists():
            return path, tipo
    raise SystemExit(f"No hay carta en {carpeta}")

tipos = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
respuestas = []

def cargar(exp):
    carta, formato = carta_de(exp)
    codigo, cuerpo = api_json("POST", "/expedientes", {"expediente_id": exp, "formato_carta": formato})
    if codigo == 409:
        raise SystemExit(f"{exp} ya existe. Borra el ítem en DynamoDB o elige otros ids antes de repetir la prueba.")
    if codigo != 201:
        raise SystemExit(f"POST /expedientes {exp} respondió {codigo}: {cuerpo}")
    for campo, path, content_type in (
        ("carta", carta, tipos[formato]),
        ("cfdi", raiz / exp / "cfdi.xml", "application/xml"),
    ):
        st, _ = http("PUT", cuerpo["subir"][campo], path.read_bytes(), {"Content-Type": content_type})
        if st not in (200, 204):
            raise SystemExit(f"PUT {campo} de {exp} respondió {st}")
    codigo, envio = api_json("POST", f"/expedientes/{exp}/enviar")
    respuestas.append((exp, codigo, envio.get("mensaje", envio)))
    if codigo != 202:
        raise SystemExit(f"POST enviar {exp} respondió {codigo}: {envio}")
    print(f"   {exp} -> {codigo}")

for exp in ids:
    cargar(exp)

import subprocess
def aws(*args):
    r = subprocess.run(["aws", *args, "--region", region, "--output", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr.strip() or "falló aws " + " ".join(args))
    return json.loads(r.stdout or "{}")

def ejecuciones():
    data = aws("stepfunctions", "list-executions", "--state-machine-arn", maquina, "--max-results", "20")
    out = []
    for item in data.get("executions", []):
        det = aws("stepfunctions", "describe-execution", "--execution-arn", item["executionArn"])
        out.append(det)
    return out

def de_expediente(det, exp):
    try:
        entrada = json.loads(det.get("input") or "{}")
    except json.JSONDecodeError:
        return False
    key = ((entrada.get("detail") or {}).get("object") or {}).get("key", "")
    return f"/{exp}/" in key

print("3/4 Esperando las 3 ejecuciones en verde ...")
limite = time.time() + 240
vistos = {}
while time.time() < limite:
    for det in ejecuciones():
        for exp in ids:
            if de_expediente(det, exp) and det["status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
                vistos.setdefault(exp, det)
    if all(exp in vistos for exp in ids):
        break
    time.sleep(8)
else:
    raise SystemExit("Pasaron 4 minutos y no terminaron las 3 ejecuciones. Revisa Step Functions y la regla de EventBridge.")

fallos = [exp for exp, det in vistos.items() if det["status"] != "SUCCEEDED"]
if fallos:
    raise SystemExit(f"Ejecución en rojo: {fallos}. Revisa el estado en la consola antes de seguir.")
for exp in ids:
    print(f"   {exp} ejecución {vistos[exp]['status']}")

print("4/4 Repitiendo el primero para probar la idempotencia ...")
codigo, envio = api_json("POST", f"/expedientes/{ids[0]}/enviar")
respuestas.append((ids[0] + " (duplicado)", codigo, envio.get("mensaje", envio)))
if codigo != 202:
    raise SystemExit(f"El reenvío respondió {codigo}: {envio}")
arn_previos = {vistos[exp]["executionArn"] for exp in ids}
duplicado = None
limite = time.time() + 180
while time.time() < limite:
    for det in ejecuciones():
        if det["executionArn"] in arn_previos or not de_expediente(det, ids[0]):
            continue
        if det["status"] == "SUCCEEDED" and "DUPLICADO_RECHAZADO" in (det.get("output") or ""):
            duplicado = det
            break
        if det["status"] in ("FAILED", "TIMED_OUT", "ABORTED"):
            raise SystemExit(f"El duplicado terminó en {det['status']}, no en rechazo controlado.")
    if duplicado:
        break
    time.sleep(8)
else:
    raise SystemExit("El segundo manifest no produjo una ejecución DUPLICADO_RECHAZADO.")
print("   duplicado rechazado, ejecución en verde")

meta = {}
for exp in ids:
    item = aws("dynamodb", "get-item", "--table-name", "cn-eq01-expedientes",
               "--key", json.dumps({"pk": {"S": f"EXP#{exp}"}, "sk": {"S": "META"}}))
    meta[exp] = (item.get("Item") or {}).get("estado", {}).get("S", "SIN_ITEM")
attrs = aws("sqs", "get-queue-attributes", "--queue-url", dlq,
            "--attribute-names", "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible")
mensajes = attrs.get("Attributes", {})
n = int(mensajes.get("ApproximateNumberOfMessages", "0")) + int(mensajes.get("ApproximateNumberOfMessagesNotVisible", "0"))

lineas = [
    f"# Fase 2 — Resultado ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})",
    "",
    f"- Stack: `cn-eq01-ingesta` en `{region}`",
    f"- API: `{api}`",
    f"- Máquina: `{maquina}`",
    f"- DLQ: `{dlq}`",
    "",
    "## Respuestas de la API",
    "",
    "| Expediente | HTTP | Mensaje |",
    "| --- | --- | --- |",
]
for exp, codigo, mensaje in respuestas:
    lineas.append(f"| {exp} | {codigo} | {mensaje} |")
lineas += ["", "## Ejecuciones y estado en DynamoDB", "", "| Expediente | Ejecución | Estado |", "| --- | --- | --- |"]
for exp in ids:
    lineas.append(f"| {exp} | {vistos[exp]['status']} | {meta[exp]} |")
lineas.append(f"| {ids[0]} duplicado | {duplicado['status']} (DUPLICADO_RECHAZADO) | {meta[ids[0]]} |")
lineas += [
    "",
    f"## DLQ: **{n}** mensajes (visibles + en vuelo)",
    "",
    "La API respondió 202 y el flujo siguió aparte. El segundo manifest del primer expediente",
    "no volvió a leer el CFDI: la ejecución terminó en verde con `DUPLICADO_RECHAZADO`",
    f"y el estado sigue en `{meta[ids[0]]}`.",
    "",
    "Capturas: `08_eventbridge_regla.png`, `09_api_202.png` (esta salida), `10_dlq_vacia.png`, `03_dynamodb_items.png`.",
]
salida.write_text("\n".join(lineas) + "\n", encoding="utf-8")
print(salida.read_text(encoding="utf-8"))
if n != 0:
    raise SystemExit(f"La DLQ tiene {n} mensajes.")
if any(meta[exp] != "EN_PROCESO" for exp in ids):
    raise SystemExit(f"Estado inesperado en DynamoDB: {meta}")
PY

echo "Listo. Pásame $SALIDA y las capturas 08, 09, 10 y 03."
