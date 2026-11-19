#!/usr/bin/env bash
# FASE 3 — Prueba de la validación inteligente con los 30 expedientes sintéticos.
# 1) Marca cada expediente como REPROCESAR en DynamoDB (único estado, junto con ERROR, que acepta re-registro).
# 2) Re-escribe su manifest.json en S3: el evento "Object Created" vuelve a disparar EventBridge -> Step Functions.
# 3) Espera las decisiones y compara contra datos/expedientes/esperado.csv.
# Evidencia: evidencias/fase3_resultado.md y evidencias/precision_pipeline.md
# Uso:  bash scripts/fase3_probar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
salida() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
  --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text; }
BUCKET=$(salida cn-eq01-base BucketLago)
TABLA=$(salida cn-eq01-base TablaExpedientes)
MAQUINA=$(salida cn-eq01-ingesta MaquinaArn)
DLQ=$(salida cn-eq01-ingesta ColaDlqUrl)
IDS=$(ls -d datos/expedientes/EXP-* | xargs -n1 basename)
INICIO=$(date -u +%FT%TZ)

echo "1/3 Reprocesando $(echo "$IDS" | wc -l | tr -d ' ') expedientes por el flujo de eventos ..."
for ID in $IDS; do
  aws dynamodb update-item --region "$REGION" --table-name "$TABLA" \
    --key "{\"pk\":{\"S\":\"EXP#$ID\"},\"sk\":{\"S\":\"META\"}}" \
    --update-expression "SET estado = :r, gsi1pk = :g REMOVE task_token" \
    --expression-attribute-values '{":r":{"S":"REPROCESAR"},":g":{"S":"ESTADO#REPROCESAR"}}' >/dev/null
  aws s3 cp "s3://$BUCKET/raw/expedientes/$ID/manifest.json" "s3://$BUCKET/raw/expedientes/$ID/manifest.json" \
    --region "$REGION" --metadata-directive REPLACE --content-type application/json \
    --metadata "reproceso=$INICIO" --only-show-errors
  sleep 2   # escalona los arranques: Textract tiene un límite bajo de trabajos por segundo
done

echo "2/3 Esperando decisiones (Textract + Bedrock tardan 1-3 min por expediente) ..."
for _ in $(seq 1 90); do
  PEND=$(aws dynamodb scan --region "$REGION" --table-name "$TABLA" \
    --filter-expression "sk = :m AND estado IN (:r, :p)" \
    --expression-attribute-values '{":m":{"S":"META"},":r":{"S":"REPROCESAR"},":p":{"S":"EN_PROCESO"}}' \
    --select COUNT --query Count --output text)
  echo "   pendientes: $PEND"
  [[ "$PEND" == "0" ]] && break
  sleep 20
done

echo "3/3 Comparando contra esperado.csv ..."
TMP=$(mktemp -d)
aws s3 cp "s3://$BUCKET/raw/resultados/" "$TMP/resultados/" --recursive --region "$REGION" --only-show-errors
aws s3 cp "s3://$BUCKET/raw/extracciones/carta/" "$TMP/carta/" --recursive --region "$REGION" --only-show-errors || true
aws dynamodb scan --region "$REGION" --table-name "$TABLA" --filter-expression "sk = :m" \
  --expression-attribute-values '{":m":{"S":"META"}}' --output json > "$TMP/meta.json"
aws stepfunctions list-executions --region "$REGION" --state-machine-arn "$MAQUINA" --max-results 100 \
  --query "executions[].[name,status,startDate]" --output json > "$TMP/ejecuciones.json" 2>/dev/null || echo "[]" > "$TMP/ejecuciones.json"
DLQ_N=$(aws sqs get-queue-attributes --region "$REGION" --queue-url "$DLQ" \
  --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text)

python3 - "$TMP" "$INICIO" "$DLQ_N" <<'PY'
import csv, json, pathlib, sys, collections, datetime as dt
tmp, inicio, dlq = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
esperado = {r["expediente_id"]: r for r in csv.DictReader(open("datos/expedientes/esperado.csv", encoding="utf-8"))}
res = {p.stem: json.loads(p.read_text()) for p in (tmp / "resultados").glob("*.json")}
carta = {p.stem: json.loads(p.read_text()) for p in (tmp / "carta").glob("*.json")} if (tmp / "carta").exists() else {}
meta = {i["expediente_id"]["S"]: i for i in json.loads((tmp / "meta.json").read_text())["Items"] if "expediente_id" in i}
t0 = dt.datetime.fromisoformat(inicio.replace("Z", "+00:00"))
ejec = collections.Counter(s for _, s, f in json.loads((tmp / "ejecuciones.json").read_text())
                           if dt.datetime.fromisoformat(str(f).replace("Z", "+00:00")) >= t0)
filas, dec_ok, reglas_ok = [], 0, 0
modelos = collections.Counter()
for exp, e in sorted(esperado.items()):
    r = res.get(exp, {})
    obtenida = r.get("decision", "SIN_RESULTADO")
    estado = meta.get(exp, {}).get("estado", {}).get("S", "?")
    reglas = sorted({h["regla_id"] for h in r.get("hallazgos", [])})
    esp_reglas = sorted(filter(None, e["reglas_esperadas"].split(";")))
    ok_d = obtenida == e["decision_esperada"]
    ok_r = reglas == esp_reglas
    dec_ok += ok_d; reglas_ok += ok_r
    modelos[(carta.get(exp, {}).get("_meta") or {}).get("modelo", r.get("modelo_bedrock") or "?")] += 1
    filas.append(f"| {exp} | {e['caso']} | {e['formato_carta']} | {e['decision_esperada']} | {obtenida} | {estado} | "
                 f"{'✅' if ok_d else '❌'} | {', '.join(esp_reglas) or '—'} | {', '.join(reglas) or '—'} | {'✅' if ok_r else '❌'} | {r.get('firma_estado','')} |")
n = len(esperado)
cab = ["| Expediente | Caso | Formato | Decisión esperada | Decisión del motor | Estado actual | ¿Coincide? | Reglas esperadas | Reglas disparadas | ¿Coinciden? | Firma |",
       "|---|---|---|---|---|---|---|---|---|---|---|"]
resumen = [f"- Decisión correcta: **{dec_ok}/{n}** ({dec_ok*100//n} %)",
           f"- Reglas exactas: **{reglas_ok}/{n}** ({reglas_ok*100//n} %)",
           f"- Ejecuciones de Step Functions desde {inicio}: {dict(ejec)}",
           f"- Mensajes en la DLQ: {dlq}",
           f"- Modelo que estructuró la carta: {dict(modelos)}"]
pathlib.Path("evidencias/precision_pipeline.md").write_text(
    "# Precisión del pipeline contra esperado.csv\n\n" + "\n".join(resumen) + "\n\n" + "\n".join(cab + filas) + "\n", encoding="utf-8")
pathlib.Path("evidencias/fase3_resultado.md").write_text(
    f"# Fase 3 — Resultado ({inicio})\n\nReproceso de los 30 expedientes por EventBridge → Step Functions "
    "(CFDI ‖ Textract → Bedrock → firma) → motor de reglas FVR → revisión humana.\n\n" + "\n".join(resumen) +
    "\n\nDetalle por expediente: `evidencias/precision_pipeline.md`.\n"
    "Revisión humana pendiente: `bash scripts/fase3_revisar.sh`\n", encoding="utf-8")
print("\n".join(resumen))
PY
echo
bash scripts/fase3_revisar.sh || true
echo "Evidencia: evidencias/fase3_resultado.md y evidencias/precision_pipeline.md"
