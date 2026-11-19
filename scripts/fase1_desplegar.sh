#!/usr/bin/env bash
# FASE 1 — Lago de datos y seguridad base.
# Despliega el stack cn-eq01-base, carga el catálogo SE en raw/ y corre una consulta de prueba en Athena.
# Uso en CloudShell:  bash scripts/fase1_desplegar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
STACK="cn-eq01-base"
SALIDA="evidencias/fase1_resultado.md"
mkdir -p evidencias

echo "1/4 Desplegando $STACK en $REGION (tarda 2-4 min)..."
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/fase1-base.yaml --no-fail-on-empty-changeset \
  --tags proyecto=cn-eq01 entrega=E2_EQ01

salida() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET=$(salida BucketLago); DB=$(salida BaseGlue); WG=$(salida WorkgroupAthena); TABLA=$(salida TablaExpedientes)
echo "   Bucket: $BUCKET | Glue DB: $DB | Workgroup: $WG | Tabla: $TABLA"

echo "2/4 Cargando catálogo SE (JSON lines) en raw/catalogo_se/ ..."
python3 - <<'EOF' > /tmp/catalogo_se.jsonl
import json
for r in json.load(open("datos/catalogo_se.json", encoding="utf-8")):
    print(json.dumps({"codigo_se": r["Código SE"], "actividad": r["Actividad"], "grupo": r["Grupo"]}, ensure_ascii=False))
EOF
aws s3 cp /tmp/catalogo_se.jsonl "s3://$BUCKET/raw/catalogo_se/catalogo_se.jsonl" --region "$REGION" --only-show-errors
# Marcador para que la capa curated/ se vea en la consola desde ahora (Glue la llena en la Fase 4)
echo "Capa curated: Parquet particionado por anio/mes (Fase 4)" | \
  aws s3 cp - "s3://$BUCKET/curated/_LEEME.txt" --region "$REGION" --only-show-errors

echo "3/4 Consulta de prueba en Athena..."
SQL="SELECT grupo, COUNT(*) AS codigos FROM ${DB}.catalogo_se_raw GROUP BY grupo ORDER BY codigos DESC"
QID=$(aws athena start-query-execution --region "$REGION" --work-group "$WG" \
  --query-string "$SQL" --query QueryExecutionId --output text)
while true; do
  ESTADO=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$QID" \
    --query QueryExecution.Status.State --output text)
  [[ "$ESTADO" == "QUEUED" || "$ESTADO" == "RUNNING" ]] || break
  sleep 2
done
BYTES=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$QID" \
  --query QueryExecution.Statistics.DataScannedInBytes --output text)
MS=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$QID" \
  --query QueryExecution.Statistics.EngineExecutionTimeInMillis --output text)

echo "4/4 Escribiendo $SALIDA ..."
{
  echo "# Fase 1 — Resultado ($(date -u +%FT%TZ))"
  echo
  echo "- Stack: \`$STACK\` en \`$REGION\`"
  echo "- Bucket del lago: \`$BUCKET\`"
  echo "- Tabla DynamoDB: \`$TABLA\` · Base de Glue: \`$DB\` · Workgroup de Athena: \`$WG\`"
  echo
  echo "## Capas del lago"
  echo '```'
  aws s3 ls "s3://$BUCKET/" --region "$REGION"
  echo '```'
  echo
  echo "## Consulta de prueba en Athena"
  echo '```sql'
  echo "$SQL"
  echo '```'
  echo "- Estado: **$ESTADO** · Bytes escaneados: **$BYTES** · Tiempo de motor: ${MS} ms"
  echo "- Athena cobra mínimo 10 MB por consulta: a 5 USD/TB esta consulta cuesta ~0.00005 USD."
  echo
  echo '```'
  aws athena get-query-results --region "$REGION" --query-execution-id "$QID" --output json | python3 -c '
import json,sys
for fila in json.load(sys.stdin)["ResultSet"]["Rows"]:
    print(" | ".join(c.get("VarCharValue","") for c in fila["Data"]))'
  echo '```'
  echo
  echo "## Cifrado y ciclo de vida"
  echo '```json'
  aws s3api get-bucket-encryption --bucket "$BUCKET" --region "$REGION"
  aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET" --region "$REGION" \
    --query 'Rules[].{id:ID,prefijo:Prefix||Filter.Prefix,transiciones:Transitions,expira_dias:Expiration.Days}'
  echo '```'
} > "$SALIDA"
cat "$SALIDA"
echo
echo "Listo. Toma las capturas 01_s3_capas.png y 07_lifecycle.png (ver evidencias/LEEME.md) y pásame $SALIDA."
