#!/usr/bin/env bash
# FASE 3 — Revisión humana.
#   Sin argumentos: lista los expedientes en REVISION_HUMANA con sus hallazgos.
#   Con argumentos: resuelve uno y la ejecución de Step Functions continúa.
#     bash scripts/fase3_revisar.sh EXP-2026-0012 OBSERVACIONES "Firma tenue; se pide carta con firma legible"
#     bash scripts/fase3_revisar.sh EXP-2026-0012 VALIDADO "Firma cotejada contra el original"
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
TABLA=$(aws cloudformation describe-stacks --region "$REGION" --stack-name cn-eq01-base \
  --query "Stacks[0].Outputs[?OutputKey=='TablaExpedientes'].OutputValue" --output text)

if [[ $# -eq 0 ]]; then
  echo "Expedientes en revisión humana:"
  aws dynamodb query --region "$REGION" --table-name "$TABLA" --index-name gsi1-estado \
    --key-condition-expression "gsi1pk = :g" --expression-attribute-values '{":g":{"S":"ESTADO#REVISION_HUMANA"}}' \
    --query "Items[].[expediente_id.S, gsi1sk.S]" --output table
  exit 0
fi

EXP="$1"; DECISION="$2"; COMENTARIO="${3:-}"
case "$DECISION" in VALIDADO|OBSERVACIONES) ;; *) echo "La decisión debe ser VALIDADO u OBSERVACIONES"; exit 1 ;; esac
TOKEN=$(aws dynamodb get-item --region "$REGION" --table-name "$TABLA" \
  --key "{\"pk\":{\"S\":\"EXP#$EXP\"},\"sk\":{\"S\":\"META\"}}" --query "Item.task_token.S" --output text)
if [[ -z "$TOKEN" || "$TOKEN" == "None" ]]; then
  echo "$EXP no está esperando revisión humana."
  exit 1
fi
SALIDA=$(python3 -c 'import json,sys; print(json.dumps({"decision": sys.argv[1], "analista": sys.argv[2], "comentario": sys.argv[3]}, ensure_ascii=False))' \
  "$DECISION" "${ANALISTA:-analista.eq01}" "$COMENTARIO")
aws stepfunctions send-task-success --region "$REGION" --task-token "$TOKEN" --task-output "$SALIDA"
echo "$EXP resuelto como $DECISION. La ejecución continúa y registra la decisión en DynamoDB."
