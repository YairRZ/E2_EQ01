#!/usr/bin/env bash
# FASE 4 — Curado con Glue y consultas en Athena.
# 1) Carga por la API los 30 expedientes sintéticos (salta los que ya existen).
# 2) Sube glue/curar.py y despliega el stack cn-eq01-curado (rol, job Flex, disparo diario, tablas).
# 3) Corre el job raw/ -> curated/ (Parquet particionado por anio/mes).
# 4) Corre las consultas de sql/ en el workgroup cn-eq01 y anota los bytes escaneados.
# Requiere los stacks cn-eq01-base y cn-eq01-ingesta.
# Uso:  bash scripts/fase4_desplegar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
BASE="cn-eq01-base"
INGESTA="cn-eq01-ingesta"
STACK="cn-eq01-curado"
EMAIL="prueba.eq01@example.com"
SALIDA="evidencias/fase4_resultado.md"
mkdir -p evidencias

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta solución solo se despliega en us-east-2. Región actual: $REGION"
  exit 1
fi

salida() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}
BUCKET=$(salida "$BASE" BucketLago)
DB=$(salida "$BASE" BaseGlue)
WG=$(salida "$BASE" WorkgroupAthena)
API=$(salida "$INGESTA" ApiUrl)
POOL=$(salida "$INGESTA" UserPoolId)
CLIENT=$(salida "$INGESTA" UserPoolClientId)
echo "Bucket: $BUCKET | Glue DB: $DB | Workgroup: $WG"

# ---------- 1. Carga de los 30 expedientes ----------
echo "1/4 Cargando los expedientes sintéticos por la API ..."
PASS=$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits+"-._"; print("Aa1!"+"".join(secrets.choice(a) for _ in range(16)))')
umask 077
printf '%s\n' "$PASS" > /tmp/cn-eq01-cognito.txt
aws cognito-idp admin-set-user-password --region "$REGION" --user-pool-id "$POOL" \
  --username "$EMAIL" --password "$PASS" --permanent >/dev/null
TOKEN=$(aws cognito-idp admin-initiate-auth --region "$REGION" --user-pool-id "$POOL" \
  --client-id "$CLIENT" --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=$EMAIL,PASSWORD=$PASS" \
  --query AuthenticationResult.IdToken --output text)
umask 022
export API TOKEN
python3 - <<'PY'
import json, os, pathlib, urllib.error, urllib.request
api, token = os.environ["API"].rstrip("/"), os.environ["TOKEN"]
raiz = pathlib.Path("datos/expedientes")
tipos = {"pdf": "application/pdf", "jpg": "image/jpeg"}

def http(metodo, url, cuerpo=None, headers=None):
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
    st, raw = http(metodo, api + ruta, data, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return st, json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        return st, {"raw": raw.decode(errors="replace")[:300]}

nuevos = existentes = 0
for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir()):
    exp = carpeta.name
    carta = next((carpeta / f"carta.{t}" for t in tipos if (carpeta / f"carta.{t}").exists()), None)
    if carta is None:
        continue
    formato = carta.suffix[1:]
    st, cuerpo = api_json("POST", "/expedientes", {"expediente_id": exp, "formato_carta": formato})
    if st == 409:
        existentes += 1
        continue
    if st != 201:
        raise SystemExit(f"POST /expedientes {exp} respondió {st}: {cuerpo}")
    for campo, path, ct in (("carta", carta, tipos[formato]), ("cfdi", carpeta / "cfdi.xml", "application/xml")):
        s, _ = http("PUT", cuerpo["subir"][campo], path.read_bytes(), {"Content-Type": ct})
        if s not in (200, 204):
            raise SystemExit(f"PUT {campo} de {exp} respondió {s}")
    st, envio = api_json("POST", f"/expedientes/{exp}/enviar")
    if st != 202:
        raise SystemExit(f"POST enviar {exp} respondió {st}: {envio}")
    nuevos += 1
print(f"   Nuevos: {nuevos} · ya existían: {existentes}")
PY

TOTAL_EXP=$(ls -d datos/expedientes/EXP-* | wc -l | tr -d ' ')
echo "   Esperando a que Step Functions escriba los $TOTAL_EXP CFDI en raw/extracciones/cfdi/ ..."
for _ in $(seq 1 36); do
  N=$(aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix raw/extracciones/cfdi/ \
      --query 'length(Contents || `[]`)' --output text)
  [[ "$N" -ge "$TOTAL_EXP" ]] && break
  sleep 5
done
echo "   CFDI en raw/extracciones/cfdi/: $N"

# ---------- 2. Despliegue del stack de curado ----------
echo "2/4 Subiendo glue/curar.py y desplegando $STACK ..."
H=$(python3 -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("glue/curar.py").read_bytes()).hexdigest()[:12])')
aws s3 cp glue/curar.py "s3://$BUCKET/despliegue/fase4/curar-${H}.py" --region "$REGION" --only-show-errors
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/fase4-curado.yaml --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides Proyecto=cn-eq01 "HashScript=$H" \
  --tags proyecto=cn-eq01 entrega=E2_EQ01
JOB=$(salida "$STACK" JobCurar)

# ---------- 3. Ejecución del job ----------
echo "3/4 Ejecutando el job $JOB (Flex puede tardar unos minutos en arrancar) ..."
RUN=$(aws glue start-job-run --region "$REGION" --job-name "$JOB" --query JobRunId --output text)
while true; do
  ESTADO=$(aws glue get-job-run --region "$REGION" --job-name "$JOB" --run-id "$RUN" --query JobRun.JobRunState --output text)
  case "$ESTADO" in SUCCEEDED|FAILED|ERROR|TIMEOUT|STOPPED) break ;; esac
  sleep 15
done
SEG=$(aws glue get-job-run --region "$REGION" --job-name "$JOB" --run-id "$RUN" --query JobRun.ExecutionTime --output text)
echo "   $RUN -> $ESTADO (${SEG}s)"
if [[ "$ESTADO" != "SUCCEEDED" ]]; then
  aws glue get-job-run --region "$REGION" --job-name "$JOB" --run-id "$RUN" --query JobRun.ErrorMessage --output text
  exit 1
fi

# ---------- 4. Consultas en Athena ----------
echo "4/4 Consultas en Athena (workgroup $WG) ..."
consulta() {  # $1 archivo .sql -> imprime bloque markdown con SQL, bytes, tiempo y resultado
  local sql qid estado bytes ms
  sql=$(grep -v "^--" "$1" | sed "s/{db}/$DB/g")
  qid=$(aws athena start-query-execution --region "$REGION" --work-group "$WG" \
        --query-string "$sql" --query QueryExecutionId --output text)
  while true; do
    estado=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
             --query QueryExecution.Status.State --output text)
    [[ "$estado" == "QUEUED" || "$estado" == "RUNNING" ]] || break
    sleep 2
  done
  bytes=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
          --query QueryExecution.Statistics.DataScannedInBytes --output text)
  ms=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
       --query QueryExecution.Statistics.EngineExecutionTimeInMillis --output text)
  echo "### $(head -1 "$1" | sed 's/^-- *//')"
  echo
  echo "- Archivo: \`$1\` · Estado: **$estado** · Bytes escaneados: **$bytes** · Tiempo: $ms ms · QueryExecutionId: \`$qid\`"
  echo
  echo '```sql'
  echo "$sql"
  echo '```'
  echo
  echo '```'
  aws athena get-query-results --region "$REGION" --query-execution-id "$qid" --max-items 15 \
    --query 'ResultSet.Rows[].Data[].VarCharValue' --output text 2>/dev/null | head -40 || true
  echo '```'
  echo
  printf '%s\t%s\t%s\n' "$1" "$estado" "$bytes" >> /tmp/cn-eq01-bytes.tsv
}

: > /tmp/cn-eq01-bytes.tsv
{
  echo "# Fase 4 — Resultado ($(date -u +%FT%TZ))"
  echo
  echo "- Stack: \`$STACK\` en \`$REGION\` · Job: \`$JOB\` (Glue 4.0, Flex, 2 × G.1X)"
  echo "- Ejecución: \`$RUN\` → **$ESTADO** en ${SEG} s"
  echo "- Disparo diario: \`cn-eq01-curar-diario\` (cron 07:00 UTC)"
  echo
  echo "## Capa curated/ (Parquet particionado por anio/mes)"
  echo '```'
  aws s3 ls "s3://$BUCKET/curated/" --recursive --region "$REGION" | grep -v '_LEEME' | awk '{print $3, $4}'
  echo '```'
  echo
  echo "## Consultas en Athena"
  echo
  for f in sql/q*.sql; do consulta "$f"; done
  echo "## Resumen de bytes escaneados"
  echo
  echo "| Consulta | Estado | Bytes |"
  echo "|---|---|---|"
  while IFS=$'\t' read -r f e b; do echo "| \`$f\` | $e | $b |"; done < /tmp/cn-eq01-bytes.tsv
  echo
  echo "Athena cobra un mínimo de 10 MB por consulta (5 USD por TB): cada consulta cuesta ~0.00005 USD."
} > "$SALIDA"

cat "$SALIDA"
echo
echo "Listo. Evidencia en $SALIDA"
