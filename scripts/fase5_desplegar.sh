#!/usr/bin/env bash
# FASE 5 — Roles IAM por persona y prueba de mínimo privilegio.
# 1) Valida y despliega el stack cn-eq01-roles (dueño de datos, ingeniero, analista, auditor).
# 2) Asume cada rol con STS y prueba lo que PUEDE y lo que NO PUEDE hacer con llamadas reales de solo lectura.
# 3) Las acciones destructivas (borrar, cambiar políticas) se prueban con el simulador de IAM, sin ejecutarlas.
#    El simulador incluye la SCP del proyecto, que niega si falta la región; por eso se le pasa aws:RequestedRegion.
# 4) Escribe evidencias/fase5_resultado.md.
# Requiere los stacks cn-eq01-base, cn-eq01-ingesta y cn-eq01-curado.
# Uso:  bash scripts/fase5_desplegar.sh
set -uo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
BASE="cn-eq01-base"
STACK="cn-eq01-roles"
PLANTILLA="infra/fase5-roles.yaml"
SALIDA="evidencias/fase5_resultado.md"
mkdir -p evidencias

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta solución solo se despliega en us-east-2. Región actual: $REGION"
  exit 1
fi

salida() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

# ---------- 1. Validar y desplegar ----------
echo "1/3 Validando la plantilla ..."
aws cloudformation validate-template --region "$REGION" --template-body "file://$PLANTILLA" >/dev/null || exit 1
echo "    Desplegando el stack $STACK (crea 4 roles IAM; requiere CAPABILITY_NAMED_IAM) ..."
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$PLANTILLA" --capabilities CAPABILITY_NAMED_IAM \
  --tags proyecto=cn-eq01 fase=5 --no-fail-on-empty-changeset || exit 1

BUCKET=$(salida "$BASE" BucketLago)
DB=$(salida "$BASE" BaseGlue)
WG=$(salida "$BASE" WorkgroupAthena)
TABLA=$(salida "$BASE" TablaExpedientes)
DUENIO=$(salida "$STACK" RolDuenioDatosArn)
INGENIERO=$(salida "$STACK" RolIngenieroArn)
ANALISTA=$(salida "$STACK" RolAnalistaArn)
AUDITOR=$(salida "$STACK" RolAuditorArn)

# Objetos de prueba (se listan con tu sesión, no con los roles)
CARTA=$(aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix raw/expedientes/ \
  --query "Contents[?ends_with(Key,'carta.pdf')]|[0].Key" --output text)
CATALOGO_RAW=$(aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix raw/catalogo_se/ \
  --query "Contents[0].Key" --output text)
RESULTADO=$(aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix raw/resultados/ \
  --query "Contents[0].Key" --output text)
CURADO=$(aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix curated/expedientes/ \
  --query "Contents[?ends_with(Key,'.parquet')]|[0].Key" --output text)

echo "2/3 IAM tarda unos segundos en propagar los roles nuevos; esperando 15 s ..."
sleep 15

# ---------- 2. Pruebas reales asumiendo cada rol ----------
FILAS=()
como() {  # $1 ARN del rol; el resto es el comando aws a correr con esa identidad
  local arn="$1"; shift
  local creds
  creds=$(aws sts assume-role --region "$REGION" --role-arn "$arn" --role-session-name prueba-fase5 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text) || return 99
  read -r AK SK ST <<<"$creds"
  env -u AWS_PROFILE AWS_ACCESS_KEY_ID="$AK" AWS_SECRET_ACCESS_KEY="$SK" AWS_SESSION_TOKEN="$ST" \
    "$@" >/dev/null 2>/tmp/cn-eq01-fase5.err
}
prueba() {  # $1 persona  $2 descripción  $3 esperado (PERMITIDO|DENEGADO)  $4 ARN  $5.. comando
  local persona="$1" desc="$2" esperado="$3" arn="$4"; shift 4
  local obtenido ok
  if como "$arn" "$@"; then obtenido="PERMITIDO"
  elif grep -qiE "AccessDenied|not authorized|Forbidden|403" /tmp/cn-eq01-fase5.err; then obtenido="DENEGADO"
  else obtenido="ERROR: $(head -c 160 /tmp/cn-eq01-fase5.err | tr '\n' ' ')"; fi
  [[ "$obtenido" == "$esperado" ]] && ok="✅" || ok="❌"
  echo "    $ok $persona · $desc → $obtenido (esperado $esperado)"
  FILAS+=("| $persona | $desc | $esperado | $obtenido | $ok |")
}
athena_como() {  # $1 ARN  $2 SQL -> sale 0 si la consulta termina en SUCCEEDED (corre en un subshell)
  local arn="$1" sql="$2" creds
  creds=$(aws sts assume-role --region "$REGION" --role-arn "$arn" --role-session-name prueba-fase5-athena \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text) || return 99
  (
    read -r AK SK ST <<<"$creds"
    unset AWS_PROFILE
    export AWS_ACCESS_KEY_ID="$AK" AWS_SECRET_ACCESS_KEY="$SK" AWS_SESSION_TOKEN="$ST"
    qid=$(aws athena start-query-execution --region "$REGION" --work-group "$WG" \
          --query-string "$sql" --query QueryExecutionId --output text 2>/tmp/cn-eq01-fase5.err) || exit 1
    while true; do
      estado=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
               --query QueryExecution.Status.State --output text)
      [[ "$estado" == "QUEUED" || "$estado" == "RUNNING" ]] || break
      sleep 2
    done
    aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
      --query QueryExecution.Status.StateChangeReason --output text > /tmp/cn-eq01-fase5.err 2>&1
    [[ "$estado" == "SUCCEEDED" ]]
  )
}
prueba_athena() {  # $1 persona $2 desc $3 esperado $4 ARN $5 SQL
  local obtenido ok
  if athena_como "$4" "$5"; then obtenido="PERMITIDO"
  elif grep -qiE "AccessDenied|not authorized|Access denied|Insufficient" /tmp/cn-eq01-fase5.err; then obtenido="DENEGADO"
  else obtenido="ERROR: $(head -c 160 /tmp/cn-eq01-fase5.err | tr '\n' ' ')"; fi
  [[ "$obtenido" == "$3" ]] && ok="✅" || ok="❌"
  echo "    $ok $1 · $2 → $obtenido (esperado $3)"
  FILAS+=("| $1 | $2 | $3 | $obtenido | $ok |")
}

echo "    Pruebas con llamadas reales (solo lectura):"
# Analista
prueba_athena "Analista" "Consulta Athena sobre curated (Q3, Parquet)" PERMITIDO "$ANALISTA" \
  "SELECT COUNT(*) FROM $DB.expedientes WHERE anio = 2026 AND mes = 10"
prueba "Analista" "Listar raw/ en S3" DENEGADO "$ANALISTA" \
  aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" --prefix raw/ --max-items 1
prueba "Analista" "Leer una carta en raw/expedientes/" DENEGADO "$ANALISTA" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$CARTA"
prueba_athena "Analista" "Consulta Athena sobre raw (catalogo_se_raw)" DENEGADO "$ANALISTA" \
  "SELECT COUNT(*) FROM $DB.catalogo_se_raw"
prueba "Analista" "Leer la tabla DynamoDB" DENEGADO "$ANALISTA" \
  aws dynamodb describe-table --region "$REGION" --table-name "$TABLA"
# Ingeniero
prueba "Ingeniero" "Leer un resultado en raw/resultados/" PERMITIDO "$INGENIERO" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$RESULTADO"
prueba "Ingeniero" "Ver ejecuciones de Step Functions" PERMITIDO "$INGENIERO" \
  aws stepfunctions list-executions --region "$REGION" --max-items 1 \
  --state-machine-arn "arn:aws:states:$REGION:$(aws sts get-caller-identity --query Account --output text):stateMachine:cn-eq01-ingesta"
prueba "Ingeniero" "Leer una carta original en raw/expedientes/" DENEGADO "$INGENIERO" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$CARTA"
prueba "Ingeniero" "Listar roles IAM" DENEGADO "$INGENIERO" \
  aws iam list-roles --max-items 1
# Auditor
prueba "Auditor" "Ver cifrado del bucket" PERMITIDO "$AUDITOR" \
  aws s3api get-bucket-encryption --region "$REGION" --bucket "$BUCKET"
prueba "Auditor" "Ver ciclo de vida del bucket" PERMITIDO "$AUDITOR" \
  aws s3api get-bucket-lifecycle-configuration --region "$REGION" --bucket "$BUCKET"
prueba "Auditor" "Leer eventos de CloudTrail" PERMITIDO "$AUDITOR" \
  aws cloudtrail lookup-events --region "$REGION" --max-results 1
prueba "Auditor" "Leer un archivo de curated/" DENEGADO "$AUDITOR" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$CURADO"
# Dueño de datos
prueba "Dueño de datos" "Leer una carta original" PERMITIDO "$DUENIO" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$CARTA"
prueba "Dueño de datos" "Leer catálogo raw" PERMITIDO "$DUENIO" \
  aws s3api head-object --region "$REGION" --bucket "$BUCKET" --key "$CATALOGO_RAW"
prueba "Dueño de datos" "Listar roles IAM" DENEGADO "$DUENIO" \
  aws iam list-roles --max-items 1

# ---------- 3. Acciones destructivas: solo simulador de IAM ----------
echo "3/3 Simulador de IAM para acciones destructivas (no se ejecutan) ..."
BUCKET_ARN="arn:aws:s3:::$BUCKET"
SIM=()
simula() {  # $1 persona $2 ARN rol $3 acción $4 recurso $5 esperado(allowed|denied)
  local r ok
  r=$(aws iam simulate-principal-policy --policy-source-arn "$2" --action-names "$3" \
      --resource-arns "$4" \
      --context-entries "ContextKeyName=aws:RequestedRegion,ContextKeyValues=$REGION,ContextKeyType=string" \
                        "ContextKeyName=aws:SecureTransport,ContextKeyValues=true,ContextKeyType=boolean" \
      --query 'EvaluationResults[0].EvalDecision' --output text 2>&1)
  [[ "$r" == "$5" || ( "$5" == "denied" && "$r" == "explicitDeny" ) || ( "$5" == "denied" && "$r" == "implicitDeny" ) ]] && ok="✅" || ok="❌"
  echo "    $ok $1 · $3 en $(basename "$4") → $r"
  SIM+=("| $1 | \`$3\` | \`${4/$BUCKET_ARN/s3://lago}\` | $r | $ok |")
}
simula "Dueño de datos" "$DUENIO"    s3:DeleteObject        "$BUCKET_ARN/raw/expedientes/x" denied
simula "Dueño de datos" "$DUENIO"    s3:PutBucketPolicy     "$BUCKET_ARN"                   denied
simula "Ingeniero"      "$INGENIERO" s3:PutObject           "$BUCKET_ARN/curated/x"         allowed
simula "Ingeniero"      "$INGENIERO" kms:ScheduleKeyDeletion "$(salida "$BASE" LlaveKmsArn)" denied
simula "Analista"       "$ANALISTA"  s3:GetObject           "$BUCKET_ARN/curated/x"         allowed
simula "Analista"       "$ANALISTA"  s3:GetObject           "$BUCKET_ARN/raw/x"             denied
simula "Auditor"        "$AUDITOR"   s3:PutObject           "$BUCKET_ARN/raw/x"             denied
simula "Auditor"        "$AUDITOR"   s3:GetObject           "$BUCKET_ARN/curated/x"         denied

{
  echo "# Fase 5 — Roles por persona y mínimo privilegio"
  echo
  echo "- Fecha: $(date -u +%Y-%m-%dT%H:%M:%SZ) · Región: $REGION · Stack: \`$STACK\` · Plantilla: \`$PLANTILLA\`"
  echo "- Roles: \`cn-eq01-persona-duenio-datos\`, \`cn-eq01-persona-ingeniero\`, \`cn-eq01-persona-analista\`, \`cn-eq01-persona-auditor\`"
  echo "- Cada prueba asume el rol con \`sts assume-role\` y hace una llamada real de solo lectura."
  echo
  echo "## Pruebas reales"
  echo
  echo "| Persona | Acción | Esperado | Obtenido | ¿Coincide? |"
  echo "|---|---|---|---|---|"
  printf '%s\n' "${FILAS[@]}"
  echo
  echo "## Acciones destructivas (simulador de IAM, no se ejecutan)"
  echo
  echo "| Persona | Acción | Recurso | Decisión | ¿Coincide? |"
  echo "|---|---|---|---|---|"
  printf '%s\n' "${SIM[@]}"
} > "$SALIDA"
rm -f /tmp/cn-eq01-fase5.err
echo "Listo: $SALIDA"
echo "Captura sugerida: consola IAM > Roles, filtro 'cn-eq01-persona' (12b_iam_roles_personas.png) y la salida del AccessDenied del analista (13_analista_accessdenied.png)."
