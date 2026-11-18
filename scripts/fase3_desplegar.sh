#!/usr/bin/env bash
# FASE 3 — Validación inteligente.
# Empaqueta las 6 Lambdas, las sube al lago con SSE-S3 (Lambda las lee aunque el bucket cifre con la CMK)
# y actualiza el stack cn-eq01-ingesta con infra/fase3-validacion.yaml:
# Textract asíncrono (TABLES + SIGNATURES) -> Bedrock (Claude Haiku 4.5, respaldo Nova Lite) -> firma,
# en paralelo con el CFDI; motor de reglas FVR; revisión humana con task token y cola SQS.
# Uso:  bash scripts/fase3_desplegar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-2}"
BASE="cn-eq01-base"
STACK="cn-eq01-ingesta"

if [[ "$REGION" != "us-east-2" ]]; then
  echo "Esta solución solo se despliega en us-east-2. Región actual: $REGION"
  exit 1
fi
BUCKET=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$BASE" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketLago'].OutputValue" --output text)
echo "1/3 Bucket del lago: $BUCKET"

hash_zip() { python3 -c 'import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()[:12])' "$1"; }
echo "2/3 Empaquetando y subiendo Lambdas ..."
subir() {  # $1 carpeta en src/ -> imprime el hash del zip subido (bash 3 de macOS: sin arreglos asociativos)
  local nombre zip_ h
  nombre=$(echo "$1" | tr '_' '-')
  zip_=/tmp/cn-eq01-$nombre.zip
  rm -f "$zip_"
  (cd "src/$1" && zip -q -X "$zip_" app.py)
  h=$(hash_zip "$zip_")
  aws s3 cp "$zip_" "s3://$BUCKET/despliegue/fase3/$nombre-$h.zip" --region "$REGION" --sse AES256 --only-show-errors
  echo "$h"
}
H_API=$(subir api); H_EXP=$(subir expediente); H_CFDI=$(subir leer_cfdi)
H_EST=$(subir estructurar_carta); H_FIRMA=$(subir verificar_firma); H_MOTOR=$(subir motor_reglas)
echo "   api=$H_API expediente=$H_EXP leer_cfdi=$H_CFDI estructurar=$H_EST firma=$H_FIRMA motor=$H_MOTOR"

echo "3/3 Actualizando $STACK con la Fase 3 (tarda 3-6 min) ..."
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/fase3-validacion.yaml --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides Proyecto=cn-eq01 \
    "HashApi=$H_API" "HashExpediente=$H_EXP" "HashLeerCfdi=$H_CFDI" \
    "HashEstructurar=$H_EST" "HashFirma=$H_FIRMA" "HashMotor=$H_MOTOR" \
  --tags proyecto=cn-eq01 entrega=E2_EQ01

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
echo "Listo. Siguiente paso: bash scripts/fase3_probar.sh"
